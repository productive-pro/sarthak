"""
Sarthak AI — WhatsApp bot via neonize (QR-login, personal account).

Streaming strategy for WhatsApp:
  WhatsApp doesn't support Telegram-style inline message editing via standard
  client APIs. Best-effort streaming UX:

  1. Send "⏳ Thinking..." immediately + typing indicator loop.
  2. Stream reply into local buffer.
  3. Every _STREAM_UPDATE_INTERVAL seconds during streaming:
       Try _client.edit_message(jid, msg_id, partial) — neonize ≥0.3.14
       If edit fails (older neonize): no mid-stream update, just final send.
  4. Send the complete final reply (replaces placeholder on success, new msg on fail).
  5. Revoke the placeholder if edit was used.

  This gives live partial replies on newer neonize and clean final replies on older.

Lifecycle:
  start_neonize_bot() / stop_neonize_bot() — called by orchestrator/service.py

Commands: /today /digest /srs /roadmap /notes /status /spaces /help
Numbers 1-7 → same quick actions.
Free text → streaming orchestrator response.

Events: ConnectedEv, DisconnectedEv, LoggedOutEv, MessageEv, ReceiptEv,
        PresenceEv, ChatPresenceEv, CallOfferEv, CallTerminateEv,
        GroupInfoEv, PairStatusEv, HistorySyncEv, BlocklistEv,
        StreamErrorEv, KeepAliveTimeoutEv, KeepAliveRestoredEv,
        ClientOutdatedEv, TemporaryBanEv, UndecryptableMessageEv
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

_WA_MESSAGE_LIMIT   = 3800
_STREAM_UPDATE_INTERVAL = 4.0  # seconds between partial WhatsApp message edits

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

# Track sent message IDs to avoid echo-response to our own messages.
_SENT_IDS: collections.deque[str] = collections.deque(maxlen=200)


# ── Suppress whatsmeow EOF noise ──────────────────────────────────────────────
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
    "1": "today", "2": "digest", "3": "srs_due",
    "4": "roadmap", "5": "my_notes", "6": "status", "7": "spaces",
}

_HELP_TEXT = (
    "*Sarthak AI — WhatsApp*\n\n"
    "*Quick Menu*\n"
    "1) Today\n2) Digest\n3) SRS\n4) Roadmap\n5) Notes\n6) Status\n7) Spaces\n\n"
    "/today /digest /srs /roadmap /notes /status /spaces /help\n\n"
    "Or send any question for a streamed AI response."
)

# ── Connection status ─────────────────────────────────────────────────────────

def is_connected() -> bool:
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
    if is_from_me:
        return True
    if is_group:
        allowed_groups: list = wa.get("allowed_group_jids", [])
        if allowed_groups:
            return _normalise_jid(jid_user) in {_normalise_jid(str(g)) for g in allowed_groups}
        return str(wa.get("allow_groups", "false")).lower() not in ("false", "0", "")
    allowed_numbers: list = wa.get("allowed_numbers", [])
    if allowed_numbers:
        return _normalise_jid(jid_user) in {_normalise_jid(str(n)) for n in allowed_numbers}
    raw = wa.get("jid", "")
    allowed = _normalise_jid(str(raw).strip() if raw else "")
    return not allowed or _normalise_jid(jid_user) == allowed


# ── Send helpers ──────────────────────────────────────────────────────────────

def _send(jid: Any, text: str) -> str | None:
    """Send plain-text reply chunked to _WA_MESSAGE_LIMIT. Returns first message ID."""
    if _client is None:
        return None
    first_id: str | None = None
    chunks = [text[i: i + _WA_MESSAGE_LIMIT] for i in range(0, len(text), _WA_MESSAGE_LIMIT)]
    for chunk in chunks:
        try:
            resp = _client.send_message(jid, chunk)
            msg_id = getattr(resp, "ID", None) or getattr(resp, "id", None)
            if msg_id:
                _SENT_IDS.append(str(msg_id))
                if first_id is None:
                    first_id = str(msg_id)
        except Exception as exc:
            log.warning("neonize_send_failed", error=str(exc))
            break
    return first_id


def _edit_message(jid: Any, msg_id: str, new_text: str) -> bool:
    """
    Try to edit a previously sent message (neonize ≥0.3).
    Returns True on success, False if not supported or failed.
    """
    if _client is None or not msg_id:
        return False
    try:
        # neonize wraps whatsmeow's SendMessage with EditAttributeSenderRevoke
        # Available as client.edit_message(jid, msg_id, new_text) in ≥0.3.14
        _client.edit_message(jid, msg_id, new_text[:_WA_MESSAGE_LIMIT])
        return True
    except (AttributeError, Exception):
        return False


def _revoke_message(jid: Any, msg_id: str) -> None:
    """Try to revoke (delete for everyone) a previously sent message."""
    if _client is None or not msg_id:
        return
    try:
        _client.revoke_message(jid, msg_id)
    except (AttributeError, Exception):
        pass


def _send_typing(jid: Any, typing: bool = True) -> None:
    """Send chat presence (typing indicator)."""
    if _client is None:
        return
    try:
        from neonize.utils.enum import ChatPresence, ChatPresenceMedia  # type: ignore
        state = ChatPresence.CHAT_PRESENCE_COMPOSING if typing else ChatPresence.CHAT_PRESENCE_PAUSED
        _client.send_chat_presence(jid, state, ChatPresenceMedia.CHAT_PRESENCE_MEDIA_TEXT)
    except Exception:
        pass


# ── Streaming with best-effort editing ────────────────────────────────────────

async def _stream_with_editing(jid: Any, question: str, session_id: str) -> str:
    """
    Stream the LLM reply with live WhatsApp message updates.

    Strategy:
      1. Send "⏳ Thinking..." placeholder immediately.
      2. Stream reply; every _STREAM_UPDATE_INTERVAL seconds try edit_message.
         If edit succeeds: placeholder shows growing reply (Telegram-like).
         If edit fails (older neonize): just collect full reply, send at end.
      3. Send the complete final reply:
         - If edits worked: one final edit to show the full reply.
         - If edits never worked: send as new message (revoke placeholder).

    Returns the final reply string.
    """
    history = await load_history_messages(session_id)

    # 1. Send placeholder + start typing loop
    _send_typing(jid, True)
    placeholder_id = _send(jid, "⏳ Thinking…")

    final_reply = ""
    last_edit_at = time.monotonic()
    edit_supported: bool | None = None  # None = unknown, True/False once tested

    try:
        async for partial in stream_dispatch(
            question, session_id=session_id, message_history=history
        ):
            final_reply = partial
            now = time.monotonic()
            if now - last_edit_at >= _STREAM_UPDATE_INTERVAL and placeholder_id:
                if edit_supported is not False:
                    # Try editing the placeholder
                    ok = _edit_message(jid, placeholder_id, partial[:_WA_MESSAGE_LIMIT] + " ✍️")
                    if ok:
                        edit_supported = True
                    elif edit_supported is None:
                        edit_supported = False  # first attempt failed — don't try again
                last_edit_at = now
    except Exception as exc:
        log.error("neonize_stream_failed", error=str(exc))
        final_reply = f"Error: {exc}"
    finally:
        _send_typing(jid, False)

    # 2. Send the complete final reply
    if not final_reply:
        final_reply = "(no response)"

    if edit_supported and placeholder_id:
        # Finish with final edit (clean, no extra message)
        if not _edit_message(jid, placeholder_id, final_reply):
            # Edit failed for final (e.g. timeout) — send as new message
            _revoke_message(jid, placeholder_id)
            _send(jid, final_reply)
    else:
        # Edits not supported — revoke placeholder, send complete reply
        if placeholder_id:
            _revoke_message(jid, placeholder_id)
        _send(jid, final_reply)

    return final_reply


# ── Message handler ────────────────────────────────────────────────────────────

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

    # Free text → streaming orchestrator with live message editing
    reply = await _stream_with_editing(jid, clean_text, session_id)
    await save_chat_turn(session_id, clean_text, reply)


async def _run_handler(run_key: str) -> str:
    """Call a handler from the Telegram bot's _RUN_HANDLERS / _CTX_HANDLERS (reused)."""
    from sarthak.features.channels.telegram.bot import _RUN_HANDLERS, _CTX_HANDLERS
    try:
        if run_key in _CTX_HANDLERS:
            return await _CTX_HANDLERS[run_key](None, None)
        if run_key in _RUN_HANDLERS:
            return await _RUN_HANDLERS[run_key](None)
    except AttributeError as exc:
        log.warning("neonize_handler_needs_ctx", run_key=run_key, error=str(exc))
        return "No active space. Set one via the web UI or /spaces."
    except Exception as exc:
        log.error("neonize_run_handler_failed", run_key=run_key, error=str(exc))
        return f"Error: {exc}"
    return f"Unknown command: {run_key}"


# ── Standalone push API ────────────────────────────────────────────────────────

async def send_message_standalone(text: str) -> None:
    """Push text to the configured JID. No-op if not connected."""
    cfg = load_config()
    if not cfg.get("whatsapp", {}).get("enabled"):
        return
    raw_jid = cfg.get("whatsapp", {}).get("jid", "")
    jid_user = str(raw_jid).strip() if raw_jid else ""
    if not jid_user or _client is None:
        log.warning("whatsapp_standalone_skipped", reason="not connected or jid not set")
        return
    try:
        from neonize.utils.jid import build_jid  # type: ignore
        _send(build_jid(jid_user), text)
    except Exception as exc:
        log.warning("whatsapp_standalone_failed", error=str(exc))


async def send_image_standalone(image_bytes: bytes, caption: str = "") -> None:
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
        mid = getattr(resp, "ID", None) or getattr(resp, "id", None)
        if mid:
            _SENT_IDS.append(str(mid))
    except Exception as exc:
        log.warning("whatsapp_send_image_failed", error=str(exc))


async def send_document_standalone(
    data: bytes, filename: str, caption: str = "", mime_type: str = "application/octet-stream"
) -> None:
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
        mid = getattr(resp, "ID", None) or getattr(resp, "id", None)
        if mid:
            _SENT_IDS.append(str(mid))
    except Exception as exc:
        log.warning("whatsapp_send_document_failed", error=str(exc))


# ── neonize client factory + event wiring ─────────────────────────────────────

def _make_client_and_factory(
    loop: asyncio.AbstractEventLoop,
    connected_flag: threading.Event,
) -> tuple[Any, Any]:
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
    try:
        devices = factory.get_all_devices()
        if devices:
            log.info("neonize_resuming_session", jid=str(devices[0].JID.User))
        else:
            log.info("neonize_no_stored_session", hint="QR scan needed via 'sarthak configure'")
    except Exception as exc:
        log.warning("neonize_get_devices_failed", error=str(exc))

    client = factory.new_client(uuid="sarthak-bot")

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
        log.warning("neonize_logged_out", reason=str(getattr(ev, "Reason", "")),
                    hint="Re-scan QR via 'sarthak configure' or web UI")

    @client.event(PairStatusEv)
    def on_pair_status(_, ev) -> None:
        log.info("neonize_pair_status", id=str(getattr(ev, "ID", "")))

    @client.event(ClientOutdatedEv)
    def on_outdated(_, ev) -> None:
        log.warning("neonize_client_outdated", hint="Upgrade neonize: pip install -U neonize")

    @client.event(TemporaryBanEv)
    def on_temp_ban(_, ev) -> None:
        log.error("neonize_temporary_ban", code=str(getattr(ev, "Code", "")))

    @client.event(KeepAliveTimeoutEv)
    def on_keepalive_timeout(_, ev) -> None:
        log.warning("neonize_keepalive_timeout")

    @client.event(KeepAliveRestoredEv)
    def on_keepalive_restored(_, ev) -> None:
        log.info("neonize_keepalive_restored")

    @client.event(StreamErrorEv)
    def on_stream_error(_, ev) -> None:
        log.warning("neonize_stream_error",
                    code=str(getattr(ev, "Code", "")), raw=str(getattr(ev, "Raw", ""))[:200])

    @client.event(HistorySyncEv)
    def on_history_sync(_, ev) -> None:
        log.info("neonize_history_sync_received")

    @client.event(BlocklistEv)
    def on_blocklist(_, ev) -> None:
        log.info("neonize_blocklist_received")

    @client.event(PresenceEv)
    def on_presence(_, ev) -> None:
        pass

    @client.event(ChatPresenceEv)
    def on_chat_presence(_, ev) -> None:
        pass

    @client.event(ReceiptEv)
    def on_receipt(_, ev) -> None:
        pass

    @client.event(CallOfferEv)
    def on_call_offer(cl, ev) -> None:
        caller = str(getattr(getattr(ev, "CallCreator", None), "User", ""))
        if str(_wa_cfg().get("auto_reject_calls", "true")).lower() not in ("false", "0", ""):
            log.info("neonize_incoming_call_rejected", caller=caller)
            try:
                cl.reject_call(ev.CallID, ev.CallCreator)
            except Exception:
                pass

    @client.event(CallTerminateEv)
    def on_call_terminate(_, ev) -> None:
        log.info("neonize_call_terminated")

    @client.event(GroupInfoEv)
    def on_group_info(_, ev) -> None:
        pass

    @client.event(UndecryptableMessageEv)
    def on_undecryptable(_, ev) -> None:
        log.warning("neonize_undecryptable_message")

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
                     jid=str(getattr(effective_jid, "User", "")), preview=text[:60])
            asyncio.run_coroutine_threadsafe(
                _handle_message(effective_jid, text), loop
            )
            if str(_wa_cfg().get("send_read_receipt", "true")).lower() not in ("false", "0", ""):
                try:
                    from neonize.utils.enum import ReceiptType  # type: ignore
                    _.mark_read(ev.Info.ID, chat=chat, sender=jid, receipt=ReceiptType.READ)
                except Exception:
                    pass
        except Exception as exc:
            log.error("neonize_on_message_error", error=str(exc))

    return client, factory


# ── Async retry loop ──────────────────────────────────────────────────────────

async def _async_run_with_retry() -> None:
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
                "neonize_session_invalid", uptime_secs=round(uptime, 1),
                session_db=SESSION_DB,
                hint="ConnectedEv never fired. Delete DB and re-scan QR: sarthak configure",
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


# ── Public lifecycle API ──────────────────────────────────────────────────────

async def start_neonize_bot() -> None:
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
    _bot_thread = threading.Thread(target=_run_bot_loop, daemon=True, name="neonize-bot")
    _bot_thread.start()
    log.info("neonize_bot_started", session_db=SESSION_DB)


async def stop_neonize_bot() -> None:
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
    if _client is None:
        return None
    try:
        me = _client.get_me()
        return str(me.User) if me else None
    except Exception:
        return None


__all__ = [
    "start_neonize_bot", "stop_neonize_bot",
    "send_message_standalone", "send_image_standalone", "send_document_standalone",
    "is_connected", "get_connected_jid",
]
