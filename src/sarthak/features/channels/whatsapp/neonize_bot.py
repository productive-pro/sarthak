"""
Sarthak AI — WhatsApp bot via neonize (QR-login, personal account).

Lifecycle
---------
  start_neonize_bot()      — called by orchestrator/service on startup
  stop_neonize_bot()       — graceful shutdown
  send_message_standalone  — send to the configured JID (used by agents)
  is_connected()           — True when a neonize client is live

Message flow:
  incoming text → _handle_message() → command dispatch / orchestrator
                → reply sent back via _send()

Reconnect: exponential backoff 5 s → 10 s → … → 300 s cap.
Stops cleanly when _stop_event is set.

Commands: /today /digest /srs /roadmap /notes /status /spaces /help
Everything else → free text → orchestrator (buffered stream reply)
"""
from __future__ import annotations

import asyncio
import collections
import logging
import threading
import time
from typing import Any

import structlog

from sarthak.core.config import load_config
from sarthak.features.channels import load_history_messages, save_chat_turn, stream_dispatch
from sarthak.features.channels.whatsapp import SESSION_DB as _SESSION_DB, SESSION_NAME as _SESSION_NAME

# Max chars per WA message — WhatsApp silently truncates above ~4096
_WA_MESSAGE_LIMIT = 3800

log = structlog.get_logger(__name__)


# Process-wide singletons
_client: Any = None
_async_loop: asyncio.AbstractEventLoop | None = None
_bot_thread: threading.Thread | None = None
_stop_event = threading.Event()

_MIN_HEALTHY_SECS = 30  # reset backoff only after a stable connection


def _wa_cfg() -> dict:
    """Return the [whatsapp] config section (cached via load_config)."""
    return load_config().get("whatsapp", {})


def _backoff_max() -> int:
    """Max reconnect wait in seconds (config: whatsapp.reconnect_backoff_max)."""
    return int(_wa_cfg().get("reconnect_backoff_max", 300))


def _backoff_init() -> int:
    """Initial reconnect wait in seconds (config: whatsapp.reconnect_backoff_init)."""
    return int(_wa_cfg().get("reconnect_backoff_init", 5))

# Track IDs of messages we sent ourselves so we don't echo-respond to them.
# WhatsApp delivers our own sent messages back to all linked devices (IsFromMe=True).
_SENT_IDS: collections.deque[str] = collections.deque(maxlen=200)

# ── Suppress noisy whatsmeow EOF log ─────────────────────────────────────────
# neonize routes Go/whatsmeow logs through Python's "neonize" logger.
# "failed to close WebSocket: EOF" is harmless — filter it out.

class _WhatsmeowEOFFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        return "failed to close WebSocket" not in record.getMessage()

logging.getLogger("neonize").addFilter(_WhatsmeowEOFFilter())

# ── Command table (mirrors Meta bot) ──────────────────────────────────────────
_COMMANDS: dict[str, str] = {
    "/today":   "today",
    "/digest":  "digest",
    "/srs":     "srs_due",
    "/roadmap": "roadmap",
    "/notes":   "my_notes",
    "/status":  "status",
    "/start":   "today",
    "/menu":    "menu",
}

_NUMERIC_MENU: dict[str, str] = {
    "1": "today",
    "2": "digest",
    "3": "srs_due",
    "4": "roadmap",
    "5": "my_notes",
    "6": "status",
    "7": "spaces",
}

_HELP_TEXT = (
    "*Sarthak AI — WhatsApp*\n\n"
    "*Quick Menu*\n"
    "1) Today\n"
    "2) Digest\n"
    "3) SRS\n"
    "4) Roadmap\n"
    "5) Notes\n"
    "6) Status\n"
    "7) Spaces\n\n"
    "/today    — Today's learning dashboard\n"
    "/digest   — Daily digest (all spaces)\n"
    "/srs      — SRS cards due today\n"
    "/roadmap  — Roadmap progress\n"
    "/notes    — Recent notes (14 days)\n"
    "/status   — Service status\n"
    "/spaces   — List spaces\n"
    "/help     — This message\n\n"
    "Or just send any question for a streamed AI response."
)


# ── Send helpers ──────────────────────────────────────────────────────────────

def is_connected() -> bool:
    """True when a live neonize client is active."""
    return _client is not None


def _send(jid: Any, text: str) -> None:
    """Send a plain-text reply chunked to _WA_MESSAGE_LIMIT. jid is a neonize JID object."""
    if _client is None:
        return
    chunks = [text[i: i + _WA_MESSAGE_LIMIT] for i in range(0, len(text), _WA_MESSAGE_LIMIT)]
    for chunk in chunks:
        try:
            resp = _client.send_message(jid, chunk)
            # Record sent ID so on_message skips the echo WhatsApp delivers back.
            try:
                _SENT_IDS.append(resp.ID)
            except Exception:
                pass
        except Exception as exc:
            log.warning("neonize_send_failed", error=str(exc))
            break


async def send_message_standalone(text: str) -> None:
    """Send to the configured JID without an active request context.

    Used by the agent scheduler/runner for push notifications.
    No-op if whatsapp is disabled or not yet connected.
    """
    cfg = load_config()
    if not cfg.get("whatsapp", {}).get("enabled"):
        return
    raw_jid  = cfg.get("whatsapp", {}).get("jid", "")
    jid_user = str(raw_jid).strip() if raw_jid else ""
    if not jid_user:
        log.warning("whatsapp_standalone_skipped", reason="jid not set in config")
        return
    if _client is None:
        log.warning("whatsapp_standalone_skipped", reason="neonize not connected")
        return
    try:
        from neonize.utils.jid import build_jid  # type: ignore
        jid = build_jid(jid_user)
        _send(jid, text)
    except Exception as exc:
        log.warning("whatsapp_standalone_failed", error=str(exc))


# ── Auth guard ────────────────────────────────────────────────────────────────

def _is_allowed(jid_user: str, is_group: bool = False, is_from_me: bool = False) -> bool:
    """Restrict to the configured JID; optionally block group chats.

    whatsapp.jid       — bare number; TOML int or str, normalised here.
    whatsapp.allow_groups — if false (default) group messages are dropped.
    """
    def _normalise(user: str) -> str:
        # Accept equivalent identity formats:
        #   9190...               (bare phone)
        #   9190...@s.whatsapp.net
        #   1893...@lid
        #   1893...:59@lid        (device suffix)
        v = str(user or "").strip().lower()
        if "@" in v:
            v = v.split("@", 1)[0]
        if ":" in v:
            v = v.split(":", 1)[0]
        return v

    wa = _wa_cfg()
    if is_group and str(wa.get("allow_groups", "false")).lower() in ("false", "0", ""):
        return False
    if is_from_me:
        # For companion mode, self-originated messages can appear with LID while
        # config may store a phone JID. Allow them through.
        return True
    raw     = wa.get("jid", "")
    allowed = _normalise(str(raw).strip() if raw else "")
    current = _normalise(jid_user)
    return not allowed or current == allowed


# ── Message handlers ──────────────────────────────────────────────────────────

async def _handle_message(jid: Any, text: str) -> None:
    """Route one incoming message: command or free text → reply → send."""
    session_id = f"wa-qr:{jid.User}"
    wa         = _wa_cfg()
    clean_text = text.strip()
    cmd        = clean_text.split()[0].lower() if clean_text.startswith("/") else ""
    menu_key   = clean_text.lower()

    # Set presence to available while processing if configured
    if str(wa.get("send_presence", "false")).lower() not in ("false", "0", ""):
        try:
            if _client:
                await asyncio.to_thread(_client.send_presence, "available")
        except Exception:
            pass

    if cmd == "/help":
        _send(jid, _HELP_TEXT)
        return

    if cmd == "/menu" or menu_key in ("menu", "help"):
        _send(jid, _HELP_TEXT)
        return

    if menu_key in _NUMERIC_MENU:
        mapped = _NUMERIC_MENU[menu_key]
        if mapped == "spaces":
            from sarthak.features.ai.tools.spaces import tool_spaces_list
            _send(jid, tool_spaces_list())
            await save_chat_turn(session_id, text, "(menu) spaces")
            return
        reply = await _run_handler(mapped)
        _send(jid, reply)
        await save_chat_turn(session_id, text, reply)
        return

    if cmd == "/spaces":
        from sarthak.features.ai.tools.spaces import tool_spaces_list
        _send(jid, tool_spaces_list())
        return

    if cmd in _COMMANDS:
        reply = await _run_handler(_COMMANDS[cmd])
        _send(jid, reply)
        await save_chat_turn(session_id, text, reply)
        return

    reply = await _stream_and_buffer(text, session_id)
    _send(jid, reply)
    await save_chat_turn(session_id, text, reply)


async def _stream_and_buffer(question: str, session_id: str) -> str:
    """Collect the full streaming orchestrator reply into a single string."""
    history = await load_history_messages(session_id)
    final = ""
    try:
        async for partial in stream_dispatch(
            question, session_id=session_id, message_history=history
        ):
            final = partial
    except Exception as exc:
        log.error("neonize_stream_failed", error=str(exc))
        final = f"Error: {exc}"
    return final or "(no response)"


async def _run_handler(run_key: str) -> str:
    """Reuse the Telegram command handlers (no Telegram-specific deps).

    _CTX_HANDLERS accept (pool, ctx); ctx=None triggers get_active_space() fallback.
    _RUN_HANDLERS accept (pool,);  pool=None is fine — they call get_activity_repo().
    """
    from sarthak.features.channels.telegram.bot import _RUN_HANDLERS, _CTX_HANDLERS
    try:
        if run_key in _CTX_HANDLERS:
            return await _CTX_HANDLERS[run_key](None, None)
        if run_key in _RUN_HANDLERS:
            return await _RUN_HANDLERS[run_key](None)
    except AttributeError as exc:
        # ctx.user_data called on ctx=None — handler needs an active space.
        log.warning("neonize_handler_needs_ctx", run_key=run_key, error=str(exc))
        return "No active space. Set one via the web UI or send /spaces."
    except Exception as exc:
        log.error("neonize_run_handler_failed", run_key=run_key, error=str(exc))
        return f"Error: {exc}"
    return f"Unknown command: {run_key}"


# ── neonize client factory + event wiring ────────────────────────────────────

def _make_client(loop: asyncio.AbstractEventLoop, connected_flag: threading.Event) -> Any:
    """Build a fresh NewClient with all event handlers wired.

    connected_flag is set by ConnectedEv so the retry loop can distinguish
    'was authenticated then disconnected' from 'never authenticated (QR shown)'.
    """
    from neonize.client import NewClient  # type: ignore
    from neonize.events import ConnectedEv, MessageEv, DisconnectedEv, LoggedOutEv  # type: ignore

    client = NewClient(_SESSION_NAME)

    @client.event(ConnectedEv)
    def on_connected(_, ev) -> None:
        connected_flag.set()
        log.info("neonize_authenticated")

    @client.event(DisconnectedEv)
    def on_disconnect(_, ev) -> None:
        log.info("neonize_disconnected")

    @client.event(LoggedOutEv)
    def on_logout(_, ev) -> None:
        log.warning("neonize_logged_out", hint="Re-scan QR via 'sarthak configure'")
        connected_flag.clear()

    @client.event(MessageEv)
    def on_message(_, ev) -> None:
        try:
            src  = ev.Info.MessageSource
            jid  = src.Sender
            chat = src.Chat

            # Skip echoes of messages neonize itself just sent.
            if src.IsFromMe and ev.Info.ID in _SENT_IDS:
                return

            # For self-messages use Chat JID; for DMs use Sender JID.
            effective_jid = jid if not src.IsFromMe else chat
            if not effective_jid or not _is_allowed(
                str(getattr(effective_jid, "User", "")),
                is_group=src.IsGroup,
                is_from_me=src.IsFromMe,
            ):
                return

            text = (
                ev.Message.conversation
                or getattr(ev.Message.extendedTextMessage, "text", "")
                or getattr(ev.Message.ephemeralMessage, "message", {})
                   and getattr(ev.Message.ephemeralMessage.message, "conversation", "")
            ).strip()

            if not text:
                return

            log.info("neonize_message_received", jid=str(getattr(effective_jid, "User", "")), preview=text[:60])
            asyncio.run_coroutine_threadsafe(_handle_message(effective_jid, text), loop)
        except Exception as exc:
            log.error("neonize_on_message_error", error=str(exc))

    return client


# ── Async retry loop (runs inside the dedicated event loop thread) ─────────────

async def _async_run_with_retry() -> None:
    """Connect neonize with exponential backoff on disconnect/error.

    Logic:
    - No session DB  → warn once and exit (user needs to run configure).
    - connect() returns without ConnectedEv firing → bail, session stale/invalid.
    - connect() returns after ConnectedEv fired → normal disconnect, reconnect.
    """
    global _client

    loop  = asyncio.get_running_loop()
    delay = _backoff_init()

    while not _stop_event.is_set():
        if not _SESSION_DB.exists():
            log.warning(
                "neonize_no_session",
                hint="Run 'sarthak configure' → Channels → WhatsApp to scan QR",
            )
            return

        connected_flag = threading.Event()
        try:
            client = _make_client(loop, connected_flag)
        except ImportError:
            log.error("neonize_not_installed", hint="pip install neonize")
            return

        _client = client
        log.info("neonize_connecting")
        t0 = time.monotonic()

        try:
            await asyncio.to_thread(client.connect)
        except Exception as exc:
            log.warning("neonize_connection_error", error=str(exc), retry_in=delay)
        else:
            log.info("neonize_connect_returned")

        uptime  = time.monotonic() - t0
        _client = None

        if _stop_event.is_set():
            break

        # connect() returned without authenticating → QR was shown or session
        # was rejected. Stop retrying; user must re-scan.
        if not connected_flag.is_set():
            log.warning(
                "neonize_session_invalid",
                uptime_secs=round(uptime, 1),
                hint="Session rejected or expired. Re-scan QR via 'sarthak configure'.",
            )
            return

        # Authenticated but disconnected — normal blip, reconnect with backoff.
        if uptime >= _MIN_HEALTHY_SECS:
            delay = _backoff_init()
            log.info("neonize_will_reconnect", uptime_secs=int(uptime), retry_in=delay)
        else:
            log.warning("neonize_fast_disconnect", uptime_secs=round(uptime, 1), retry_in=delay)

        try:
            await asyncio.wait_for(asyncio.sleep(delay), timeout=delay + 1)
        except (asyncio.TimeoutError, asyncio.CancelledError):
            pass
        delay = min(delay * 2, _backoff_max())

    log.info("neonize_retry_loop_exited")


def _run_bot_loop() -> None:
    """Entry point for the bot thread: create and run the event loop."""
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    global _async_loop
    _async_loop = loop
    try:
        loop.run_until_complete(_async_run_with_retry())
    finally:
        loop.close()
        _async_loop = None


# ── Public lifecycle API ──────────────────────────────────────────────────────

def _silence_neonize_stdout() -> None:
    """Redirect stdout to /dev/null to suppress neonize/whatsmeow Go-layer prints.

    neonize prints XML stanzas, 'Press Ctrl+C to exit', and websocket frames
    directly to fd 1. These bypass Python logging and cannot be filtered.
    """
    import os
    try:
        devnull_fd = os.open(os.devnull, os.O_WRONLY)
        os.dup2(devnull_fd, 1)
        os.close(devnull_fd)
    except Exception:
        pass


async def start_neonize_bot() -> None:
    """Start the neonize bot with reconnect loop. No-op if already running."""
    global _bot_thread

    if _bot_thread is not None and _bot_thread.is_alive():
        log.info("neonize_bot_already_running")
        return

    try:
        from neonize.client import NewClient  # type: ignore  # noqa: F401
    except ImportError:
        log.error("neonize_not_installed", hint="pip install neonize")
        return

    _silence_neonize_stdout()
    _stop_event.clear()
    _bot_thread = threading.Thread(
        target=_run_bot_loop, daemon=True, name="neonize-bot"
    )
    _bot_thread.start()
    log.info("neonize_bot_started")


async def stop_neonize_bot() -> None:
    """Signal the retry loop to stop and disconnect the active client."""
    global _client, _async_loop, _bot_thread

    _stop_event.set()

    if _client is not None:
        try:
            await asyncio.to_thread(_client.disconnect)
        except Exception as exc:
            log.warning("neonize_stop_error", error=str(exc))
        _client = None

    if _bot_thread is not None:
        _bot_thread.join(timeout=8)
        _bot_thread = None

    log.info("neonize_bot_stopped")


__all__ = [
    "start_neonize_bot",
    "stop_neonize_bot",
    "send_message_standalone",
    "is_connected",
]
