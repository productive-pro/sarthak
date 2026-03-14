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

Media flow:
  send_image_standalone / send_document_standalone / send_audio_standalone
  → build message object → _send_media()

Reconnect: exponential backoff 5 s → 10 s → … → 300 s cap.
Stops cleanly when _stop_event is set.

Session: uses ClientFactory(database_name=SESSION_DB) so credentials
are stored in the configured path, not the process CWD.

Commands: /today /digest /srs /roadmap /notes /status /spaces /help
Everything else → free text → orchestrator (buffered stream reply)

Events handled:
  ConnectedEv, DisconnectedEv, LoggedOutEv, MessageEv, ReceiptEv,
  PresenceEv, ChatPresenceEv, CallOfferEv, CallTerminateEv,
  GroupInfoEv, PairStatusEv, HistorySyncEv, BlocklistEv,
  StreamErrorEv, KeepAliveTimeoutEv, KeepAliveRestoredEv
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
from sarthak.features.channels.whatsapp import SESSION_DB

_WA_MESSAGE_LIMIT = 3800

log = structlog.get_logger(__name__)

# ── Process-wide singletons ───────────────────────────────────────────────────
_client: Any = None
_factory: Any = None
_async_loop: asyncio.AbstractEventLoop | None = None
_bot_thread: threading.Thread | None = None
_stop_event = threading.Event()

_MIN_HEALTHY_SECS = 30


def _wa_cfg() -> dict:
    return load_config().get("whatsapp", {})


def _backoff_max() -> int:
    return int(_wa_cfg().get("reconnect_backoff_max", 300))


def _backoff_init() -> int:
    return int(_wa_cfg().get("reconnect_backoff_init", 5))


# Track IDs of messages we sent so we don't echo-respond to them.
_SENT_IDS: collections.deque[str] = collections.deque(maxlen=200)


# ── Suppress noisy whatsmeow EOF log ─────────────────────────────────────────
class _WhatsmeowEOFFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        msg = record.getMessage()
        return "failed to close WebSocket" not in msg and "failed to read frame header" not in msg


logging.getLogger("neonize").addFilter(_WhatsmeowEOFFilter())

# ── Command table ─────────────────────────────────────────────────────────────
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
    "1) Today\n2) Digest\n3) SRS\n4) Roadmap\n5) Notes\n6) Status\n7) Spaces\n\n"
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


# ── Connection status ─────────────────────────────────────────────────────────

def is_connected() -> bool:
    """True when a live neonize client is active."""
    return _client is not None and getattr(_client, "connected", False)


# ── Auth guard ────────────────────────────────────────────────────────────────

def _normalise_jid(user: str) -> str:
    v = str(user or "").strip().lower()
    if "@" in v:
        v = v.split("@", 1)[0]
    if ":" in v:
        v = v.split(":", 1)[0]
    return v


def _is_allowed(jid_user: str, is_group: bool = False, is_from_me: bool = False) -> bool:
    wa = _wa_cfg()
    if is_group and str(wa.get("allow_groups", "false")).lower() in ("false", "0", ""):
        return False
    if is_from_me:
        return True
    raw = wa.get("jid", "")
    allowed = _normalise_jid(str(raw).strip() if raw else "")
    return not allowed or _normalise_jid(jid_user) == allowed


# ── Send helpers ──────────────────────────────────────────────────────────────

def _send(jid: Any, text: str) -> None:
    """Send plain-text reply chunked to _WA_MESSAGE_LIMIT."""
    if _client is None:
        return
    chunks = [text[i: i + _WA_MESSAGE_LIMIT] for i in range(0, len(text), _WA_MESSAGE_LIMIT)]
    for chunk in chunks:
        try:
            resp = _client.send_message(jid, chunk)
            try:
                _SENT_IDS.append(resp.ID)
            except Exception:
                pass
        except Exception as exc:
            log.warning("neonize_send_failed", error=str(exc))
            break


def _send_typing(jid: Any, typing: bool = True) -> None:
    """Send chat presence (typing indicator)."""
    if _client is None:
        return
    try:
        state = "composing" if typing else "paused"
        _client.send_chat_presence(jid, state, "")
    except Exception:
        pass


async def send_message_standalone(text: str) -> None:
    """Send to the configured JID without an active request context.
    Used by agent scheduler/runner for push notifications. No-op if not connected."""
    cfg = load_config()
    if not cfg.get("whatsapp", {}).get("enabled"):
        return
    raw_jid = cfg.get("whatsapp", {}).get("jid", "")
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


async def send_image_standalone(image_bytes: bytes, caption: str = "") -> None:
    """Send an image to the configured JID. No-op if not connected."""
    cfg = load_config()
    if not cfg.get("whatsapp", {}).get("enabled") or _client is None:
        return
    raw_jid = cfg.get("whatsapp", {}).get("jid", "")
    if not raw_jid:
        return
    try:
        from neonize.utils.jid import build_jid  # type: ignore
        jid = build_jid(str(raw_jid).strip())
        msg = _client.build_image_message(image_bytes, caption=caption, mime_type="image/jpeg")
        resp = _client.send_message(jid, message=msg)
        try:
            _SENT_IDS.append(resp.ID)
        except Exception:
            pass
    except Exception as exc:
        log.warning("whatsapp_send_image_failed", error=str(exc))


async def send_document_standalone(data: bytes, filename: str, caption: str = "", mime_type: str = "application/octet-stream") -> None:
    """Send a document/file to the configured JID. No-op if not connected."""
    cfg = load_config()
    if not cfg.get("whatsapp", {}).get("enabled") or _client is None:
        return
    raw_jid = cfg.get("whatsapp", {}).get("jid", "")
    if not raw_jid:
        return
    try:
        from neonize.utils.jid import build_jid  # type: ignore
        jid = build_jid(str(raw_jid).strip())
        msg = _client.build_document_message(data, filename=filename, caption=caption, mime_type=mime_type)
        resp = _client.send_message(jid, message=msg)
        try:
            _SENT_IDS.append(resp.ID)
        except Exception:
            pass
    except Exception as exc:
        log.warning("whatsapp_send_document_failed", error=str(exc))


# ── Message handlers ──────────────────────────────────────────────────────────

async def _handle_message(jid: Any, text: str) -> None:
    """Route one incoming message: command or free text → reply → send."""
    session_id = f"wa-qr:{getattr(jid, 'User', str(jid))}"
    wa = _wa_cfg()
    clean_text = text.strip()
    cmd = clean_text.split()[0].lower() if clean_text.startswith("/") else ""
    menu_key = clean_text.lower()

    if str(wa.get("send_presence", "false")).lower() not in ("false", "0", ""):
        try:
            if _client:
                await asyncio.to_thread(_client.send_presence, "available")
        except Exception:
            pass

    if cmd in ("/help", "/menu") or menu_key in ("menu", "help"):
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

    # Free text → stream orchestrator response with typing indicator
    _send_typing(jid, True)
    try:
        reply = await _stream_and_buffer(text, session_id)
    finally:
        _send_typing(jid, False)
    _send(jid, reply)
    await save_chat_turn(session_id, text, reply)


async def _stream_and_buffer(question: str, session_id: str) -> str:
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
    from sarthak.features.channels.telegram.bot import _RUN_HANDLERS, _CTX_HANDLERS
    try:
        if run_key in _CTX_HANDLERS:
            return await _CTX_HANDLERS[run_key](None, None)
        if run_key in _RUN_HANDLERS:
            return await _RUN_HANDLERS[run_key](None)
    except AttributeError as exc:
        log.warning("neonize_handler_needs_ctx", run_key=run_key, error=str(exc))
        return "No active space. Set one via the web UI or send /spaces."
    except Exception as exc:
        log.error("neonize_run_handler_failed", run_key=run_key, error=str(exc))
        return f"Error: {exc}"
    return f"Unknown command: {run_key}"


# ── neonize client factory + event wiring ────────────────────────────────────

def _make_client_and_factory(
    loop: asyncio.AbstractEventLoop,
    connected_flag: threading.Event,
) -> tuple[Any, Any]:
    """Build ClientFactory + NewClient with all event handlers wired.

    Uses ClientFactory(database_name=SESSION_DB) so credentials are always
    stored in the configured path regardless of CWD.
    If a paired device already exists in the DB, reuse its JID.
    Otherwise create a fresh client with a stable uuid.
    """
    from neonize.client import ClientFactory  # type: ignore
    from neonize.events import (  # type: ignore
        ConnectedEv, DisconnectedEv, LoggedOutEv, MessageEv,
        ReceiptEv, PresenceEv, ChatPresenceEv,
        CallOfferEv, CallTerminateEv, GroupInfoEv,
        PairStatusEv, HistorySyncEv, BlocklistEv,
        StreamErrorEv, KeepAliveTimeoutEv, KeepAliveRestoredEv,
        ClientOutdatedEv, TemporaryBanEv, UndecryptableMessageEv,
    )

    factory = ClientFactory(database_name=SESSION_DB)

    # Always use the stable uuid "sarthak-bot" — this MUST match the uuid used
    # during QR pairing in qr.py / configure.py so the Go layer finds the stored
    # session in the DB. Passing jid= from get_all_devices() would set uuid to
    # jid.User (e.g. "919014633844:60") which mismatches the scan-time uuid and
    # causes the Go layer to treat this as a fresh login → QR shown → server EOF.
    try:
        devices = factory.get_all_devices()
        if devices:
            log.info("neonize_resuming_session", jid=str(devices[0].JID.User))
        else:
            log.info("neonize_no_stored_session", hint="QR scan needed via 'sarthak configure'")
    except Exception as exc:
        log.warning("neonize_get_devices_failed", error=str(exc))

    client = factory.new_client(uuid="sarthak-bot")

    # ── Connection events ─────────────────────────────────────────────────────

    @client.event(ConnectedEv)
    def on_connected(cl, ev) -> None:
        connected_flag.set()
        log.info("neonize_authenticated")
        push_name = str(_wa_cfg().get("push_name", "")).strip()
        if push_name:
            try:
                cl.set_profile_name(push_name)
            except Exception:
                pass

    @client.event(DisconnectedEv)
    def on_disconnect(_, ev) -> None:
        log.info("neonize_disconnected")

    @client.event(LoggedOutEv)
    def on_logout(_, ev) -> None:
        reason = str(getattr(ev, "Reason", ""))
        log.warning("neonize_logged_out", reason=reason,
                    hint="Re-scan QR via 'sarthak configure' or web UI")

    @client.event(PairStatusEv)
    def on_pair_status(_, ev) -> None:
        log.info("neonize_pair_status", id=str(getattr(ev, "ID", "")))

    @client.event(ClientOutdatedEv)
    def on_outdated(_, ev) -> None:
        log.warning("neonize_client_outdated", hint="Upgrade neonize: pip install -U neonize")

    @client.event(TemporaryBanEv)
    def on_temp_ban(_, ev) -> None:
        log.error("neonize_temporary_ban", code=str(getattr(ev, "Code", "")),
                  expire=str(getattr(ev, "Expire", "")))

    # ── Keep-alive ────────────────────────────────────────────────────────────

    @client.event(KeepAliveTimeoutEv)
    def on_keepalive_timeout(_, ev) -> None:
        log.warning("neonize_keepalive_timeout")

    @client.event(KeepAliveRestoredEv)
    def on_keepalive_restored(_, ev) -> None:
        log.info("neonize_keepalive_restored")

    # ── Stream errors ─────────────────────────────────────────────────────────

    @client.event(StreamErrorEv)
    def on_stream_error(_, ev) -> None:
        code = str(getattr(ev, "Code", ""))
        raw = str(getattr(ev, "Raw", ""))
        log.warning("neonize_stream_error", code=code, raw=raw[:200])

    # ── Sync events ───────────────────────────────────────────────────────────

    @client.event(HistorySyncEv)
    def on_history_sync(_, ev) -> None:
        log.info("neonize_history_sync_received")

    @client.event(BlocklistEv)
    def on_blocklist(_, ev) -> None:
        log.info("neonize_blocklist_received")

    # ── Presence ──────────────────────────────────────────────────────────────

    @client.event(PresenceEv)
    def on_presence(_, ev) -> None:
        pass  # available for future use

    @client.event(ChatPresenceEv)
    def on_chat_presence(_, ev) -> None:
        pass  # typing indicators from contacts

    # ── Receipts ──────────────────────────────────────────────────────────────

    @client.event(ReceiptEv)
    def on_receipt(_, ev) -> None:
        pass  # delivery/read receipts — available for future tracking

    # ── Calls ─────────────────────────────────────────────────────────────────

    @client.event(CallOfferEv)
    def on_call_offer(cl, ev) -> None:
        caller = str(getattr(getattr(ev, "CallCreator", None), "User", ""))
        if str(_wa_cfg().get("auto_reject_calls", "true")).lower() not in ("false", "0", ""):
            log.info("neonize_incoming_call_rejected", caller=caller)
            try:
                cl.reject_call(ev.CallID, ev.CallCreator)
            except Exception:
                pass
        else:
            log.info("neonize_incoming_call_received", caller=caller)

    @client.event(CallTerminateEv)
    def on_call_terminate(_, ev) -> None:
        log.info("neonize_call_terminated")

    # ── Groups ────────────────────────────────────────────────────────────────

    @client.event(GroupInfoEv)
    def on_group_info(_, ev) -> None:
        pass  # group metadata changes — available for future use

    # ── Undecryptable ─────────────────────────────────────────────────────────

    @client.event(UndecryptableMessageEv)
    def on_undecryptable(_, ev) -> None:
        log.warning("neonize_undecryptable_message")

    # ── Incoming messages ─────────────────────────────────────────────────────

    @client.event(MessageEv)
    def on_message(_, ev) -> None:
        try:
            src = ev.Info.MessageSource
            jid = src.Sender
            chat = src.Chat

            if src.IsFromMe and ev.Info.ID in _SENT_IDS:
                return

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
                or (
                    getattr(ev.Message.ephemeralMessage, "message", None)
                    and getattr(ev.Message.ephemeralMessage.message, "conversation", "")
                )
                or ""
            ).strip()

            if not text:
                return

            log.info("neonize_message_received",
                     jid=str(getattr(effective_jid, "User", "")),
                     preview=text[:60])
            asyncio.run_coroutine_threadsafe(
                _handle_message(effective_jid, text), loop
            )
            if str(_wa_cfg().get("send_read_receipt", "true")).lower() not in ("false", "0", ""):
                try:
                    from neonize.utils.enum import ReceiptType  # type: ignore
                    _.mark_read(
                        ev.Info.ID,
                        chat=chat,
                        sender=jid,
                        receipt=ReceiptType.Read,
                    )
                except Exception:
                    pass
        except Exception as exc:
            log.error("neonize_on_message_error", error=str(exc))

    return client, factory


# ── Async retry loop ──────────────────────────────────────────────────────────

async def _async_run_with_retry() -> None:
    """Connect neonize with exponential backoff on disconnect/error.

    Uses ClientFactory so the session DB path is always correct.
    - No devices in DB and no QR callback → warn once and exit.
    - connect() returns without ConnectedEv → session invalid, stop.
    - connect() returns after ConnectedEv → normal disconnect, reconnect.
    """
    global _client, _factory

    loop = asyncio.get_running_loop()
    delay = _backoff_init()

    while not _stop_event.is_set():
        try:
            from neonize.client import ClientFactory  # type: ignore  # noqa: F401
        except ImportError:
            log.error("neonize_not_installed", hint="pip install neonize")
            return

        connected_flag = threading.Event()
        try:
            client, factory = _make_client_and_factory(loop, connected_flag)
        except Exception as exc:
            log.error("neonize_client_build_failed", error=str(exc))
            return

        _client = client
        _factory = factory
        log.info("neonize_connecting", session_db=SESSION_DB, uuid="sarthak-bot")
        t0 = time.monotonic()

        try:
            await asyncio.to_thread(client.connect)
        except Exception as exc:
            log.warning("neonize_connection_error", error=str(exc), retry_in=delay)

        uptime = time.monotonic() - t0
        _client = None
        _factory = None

        if _stop_event.is_set():
            break

        if not connected_flag.is_set():
            log.warning(
                "neonize_session_invalid",
                uptime_secs=round(uptime, 1),
                session_db=SESSION_DB,
                hint=(
                    "ConnectedEv never fired — session rejected or no stored session. "
                    "Delete the DB and re-scan QR: rm {db} && sarthak configure".format(db=SESSION_DB)
                ),
            )
            return

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
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    global _async_loop
    _async_loop = loop
    try:
        loop.run_until_complete(_async_run_with_retry())
    finally:
        loop.close()
        _async_loop = None


# ── Stdout suppression ────────────────────────────────────────────────────────

def _silence_neonize_stdout() -> None:
    # Previously redirected fd 1 to /dev/null, but that swallows ALL stdout
    # including structlog JSON output, making the orchestrator log silent.
    # Go-layer noise ("Press Ctrl+C to exit") is cosmetic — leave it.
    pass


# ── Public lifecycle API ──────────────────────────────────────────────────────

async def start_neonize_bot() -> None:
    """Start the neonize bot with reconnect loop. No-op if already running."""
    global _bot_thread

    if _bot_thread is not None and _bot_thread.is_alive():
        log.info("neonize_bot_already_running")
        return

    try:
        from neonize.client import ClientFactory  # type: ignore  # noqa: F401
    except ImportError:
        log.error("neonize_not_installed", hint="pip install neonize")
        return

    _stop_event.clear()
    _bot_thread = threading.Thread(
        target=_run_bot_loop, daemon=True, name="neonize-bot"
    )
    _bot_thread.start()
    log.info("neonize_bot_started", session_db=SESSION_DB)


async def stop_neonize_bot() -> None:
    """Signal the retry loop to stop and disconnect the active client."""
    global _client, _factory, _async_loop, _bot_thread

    _stop_event.set()

    if _client is not None:
        try:
            await asyncio.to_thread(_client.disconnect)
        except Exception as exc:
            log.warning("neonize_stop_error", error=str(exc))
        _client = None
    _factory = None

    if _bot_thread is not None:
        _bot_thread.join(timeout=8)
        _bot_thread = None

    log.info("neonize_bot_stopped")


def get_connected_jid() -> str | None:
    """Return the JID string of the connected device, or None."""
    if _client is None:
        return None
    try:
        me = _client.get_me()
        return str(me.User) if me else None
    except Exception:
        return None


__all__ = [
    "start_neonize_bot",
    "stop_neonize_bot",
    "send_message_standalone",
    "send_image_standalone",
    "send_document_standalone",
    "is_connected",
    "get_connected_jid",
]
