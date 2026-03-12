"""
Sarthak AI — WhatsApp bot via neonize (QR-login, personal account).

Lifecycle
---------
  start_neonize_bot()   — called by orchestrator/service on startup when
                          config[whatsapp][mode] == "qr"
  stop_neonize_bot()    — graceful shutdown

Message flow (mirrors Telegram bot):
  incoming text → _handle_message() → command dispatch / orchestrator
                → reply sent back via client.send_message()

Reconnect logic
---------------
  _run_with_retry() runs in a daemon thread. On disconnect or error it
  waits with exponential backoff (5 s → 10 s → … → 300 s cap) then
  rebuilds the client and reconnects. Stops cleanly when _stop_event is set.

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

log = structlog.get_logger(__name__)


# Process-wide singletons
_client: Any = None
_async_loop: asyncio.AbstractEventLoop | None = None
_bot_thread: threading.Thread | None = None
_stop_event = threading.Event()

_MAX_BACKOFF = 300
_INIT_BACKOFF = 5
_MIN_HEALTHY_SECS = 30  # reset backoff only after a stable connection

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
}

_HELP_TEXT = (
    "*Sarthak AI — WhatsApp*\n\n"
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


# ── Send helper ───────────────────────────────────────────────────────────────

def _send(jid: Any, text: str) -> None:
    """Send a plain-text reply. jid is a neonize JID object."""
    if _client is None:
        return
    try:
        resp = _client.send_message(jid, text)
        # Record the sent message ID so on_message can skip the echo WhatsApp
        # delivers back to all linked devices (IsFromMe=True).
        try:
            _SENT_IDS.append(resp.ID)
        except Exception:
            pass
    except Exception as exc:
        log.warning("neonize_send_failed", error=str(exc))


# ── Auth guard ────────────────────────────────────────────────────────────────

def _is_allowed(jid_user: str) -> bool:
    """Restrict to the configured JID (whatsapp.jid in config.toml)."""
    allowed = str(load_config().get("whatsapp", {}).get("jid", "")).strip()
    return not allowed or jid_user == allowed


# ── Message handlers ──────────────────────────────────────────────────────────

async def _handle_message(jid: Any, text: str) -> None:
    """Route one incoming message: command or free text → reply → send."""
    session_id = f"wa-qr:{jid.User}"
    cmd = text.split()[0].lower() if text.startswith("/") else ""

    if cmd == "/help":
        _send(jid, _HELP_TEXT)
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
    """Reuse the Telegram command handlers (no Telegram-specific deps)."""
    from sarthak.features.channels.telegram.bot import _RUN_HANDLERS, _CTX_HANDLERS
    try:
        if run_key in _CTX_HANDLERS:
            return await _CTX_HANDLERS[run_key](None, None)
        if run_key in _RUN_HANDLERS:
            return await _RUN_HANDLERS[run_key](None)
    except Exception as exc:
        log.error("neonize_run_handler_failed", run_key=run_key, error=str(exc))
        return f"Error running {run_key}: {exc}"
    return f"Unknown command: {run_key}"


# ── neonize client factory + event wiring ────────────────────────────────────

def _make_client(loop: asyncio.AbstractEventLoop) -> Any:
    """Build a fresh NewClient with all event handlers wired."""
    from neonize.client import NewClient  # type: ignore
    from neonize.events import MessageEv, DisconnectedEv, LoggedOutEv  # type: ignore

    client = NewClient(_SESSION_NAME)

    @client.event(DisconnectedEv)
    def on_disconnect(_, ev):
        log.info("neonize_disconnected")

    @client.event(LoggedOutEv)
    def on_logout(_, ev):
        log.warning("neonize_logged_out", hint="Re-scan QR via 'sarthak configure'")

    @client.event(MessageEv)
    def on_message(_, ev):
        try:
            src = ev.Info.MessageSource
            # Groups are never processed.
            if src.IsGroup:
                return
            jid = src.Sender
            if not jid or not _is_allowed(jid.User):
                return
            # Allow IsFromMe messages (owner messaging themselves in Saved Messages
            # from their phone) but skip echoes of messages that neonize just sent.
            if src.IsFromMe and ev.Info.ID in _SENT_IDS:
                return
            text = (
                ev.Message.conversation
                or (ev.Message.extendedTextMessage.text if ev.Message.HasField("extendedTextMessage") else "")
            ).strip()
            if not text:
                return
            log.info("neonize_message_received", jid=jid.User, preview=text[:60])
            # loop is the running asyncio event loop — schedule the coroutine on it
            asyncio.run_coroutine_threadsafe(_handle_message(jid, text), loop)
        except Exception as exc:
            log.error("neonize_on_message_error", error=str(exc))

    return client


# ── Async retry loop (runs inside the dedicated event loop thread) ─────────────

async def _async_run_with_retry() -> None:
    """Connect neonize with exponential backoff on disconnect/error.

    client.connect() blocks — it runs in the thread pool via asyncio.to_thread()
    so the event loop stays alive to process _handle_message coroutines.
    """
    global _client

    loop = asyncio.get_running_loop()
    delay = _INIT_BACKOFF

    while not _stop_event.is_set():
        try:
            client = _make_client(loop)
        except ImportError:
            log.error("neonize_not_installed", hint="pip install neonize")
            return

        _client = client
        log.info("neonize_connecting")
        t0 = time.monotonic()

        try:
            # client.connect() blocks — run in thread pool so the event loop
            # stays live for incoming _handle_message coroutines.
            await asyncio.to_thread(client.connect)
        except Exception as exc:
            log.warning("neonize_connection_error", error=str(exc), retry_in=delay)
        else:
            log.info("neonize_connect_returned")

        uptime = time.monotonic() - t0
        _client = None

        if _stop_event.is_set():
            break

        if uptime >= _MIN_HEALTHY_SECS:
            delay = _INIT_BACKOFF
            log.info("neonize_will_reconnect", uptime_secs=int(uptime), retry_in=delay)
        else:
            log.warning("neonize_fast_disconnect", uptime_secs=round(uptime, 1), retry_in=delay)

        try:
            await asyncio.wait_for(asyncio.sleep(delay), timeout=delay + 1)
        except (asyncio.TimeoutError, asyncio.CancelledError):
            pass
        delay = min(delay * 2, _MAX_BACKOFF)

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

    _stop_event.clear()
    _bot_thread = threading.Thread(
        target=_run_bot_loop, daemon=True, name="neonize-bot"
    )
    _bot_thread.start()
    log.info("neonize_bot_started", session=_SESSION_NAME)


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
