"""
Sarthak AI — WhatsApp Bot (Meta Cloud API webhook).

Two routes mounted on the FastAPI app:
  GET  /webhook/whatsapp  — Meta verification handshake
  POST /webhook/whatsapp  — Incoming messages

Auth: only messages from cfg[whatsapp][allowed_phone] are processed.

Message flow (mirrors Telegram):
  incoming text → stream_dispatch() → buffer full reply → send_message()

Commands (text-based, no inline keyboards):
  /start /today /learn /digest /srs /roadmap /notes /status /spaces /help
  Everything else → free-text → orchestrator
"""
from __future__ import annotations

import uuid
from typing import Any

import structlog
from fastapi import APIRouter, Query, Request, Response

from sarthak.core.config import load_config
from sarthak.features.channels import load_history_messages, save_chat_turn, stream_dispatch
from sarthak.features.channels.whatsapp.client import send_message

log = structlog.get_logger(__name__)
router = APIRouter(prefix="/webhook/whatsapp", tags=["whatsapp"])

# ── Command dispatch table (mirrors Telegram _RUN_LABELS) ─────────────────────
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


# ── Helpers ───────────────────────────────────────────────────────────────────

def _load_wa_cfg() -> dict:
    return load_config().get("whatsapp", {})


def _is_allowed(phone: str, wa_cfg: dict) -> bool:
    allowed = wa_cfg.get("allowed_phone", "")
    return bool(allowed) and phone == allowed


def _extract_message(body: dict) -> tuple[str, str] | None:
    """Extract (from_phone, text) from a Meta webhook payload. Returns None if not a text message."""
    try:
        entry = body["entry"][0]
        change = entry["changes"][0]["value"]
        msg = change["messages"][0]
        if msg.get("type") != "text":
            return None
        return msg["from"], msg["text"]["body"].strip()
    except (KeyError, IndexError):
        return None


# ── Route: GET — Meta verification ───────────────────────────────────────────

@router.get("")
async def verify(
    hub_mode: str = Query(default="", alias="hub.mode"),
    hub_challenge: str = Query(default="", alias="hub.challenge"),
    hub_verify_token: str = Query(default="", alias="hub.verify_token"),
) -> Response:
    wa_cfg = _load_wa_cfg()
    expected = wa_cfg.get("verify_token", "")
    if hub_mode == "subscribe" and hub_verify_token == expected:
        log.info("whatsapp_webhook_verified")
        return Response(content=hub_challenge, media_type="text/plain")
    log.warning("whatsapp_webhook_verify_failed")
    return Response(status_code=403)


# ── Route: POST — Incoming messages ──────────────────────────────────────────

@router.post("")
async def receive(request: Request) -> dict[str, Any]:
    cfg = load_config()
    wa_cfg = cfg.get("whatsapp", {})

    if not wa_cfg.get("enabled"):
        return {"status": "disabled"}

    try:
        body = await request.json()
    except Exception:
        return {"status": "invalid_json"}

    extracted = _extract_message(body)
    if extracted is None:
        return {"status": "ignored"}

    from_phone, text = extracted

    if not _is_allowed(from_phone, wa_cfg):
        log.warning("whatsapp_unauthorized", phone=from_phone)
        return {"status": "unauthorized"}

    log.info("whatsapp_message_received", from_phone=from_phone, preview=text[:60])

    # Fire-and-forget so Meta gets a 200 quickly
    import asyncio
    asyncio.create_task(_handle(cfg, from_phone, text))
    return {"status": "ok"}


async def _handle(cfg: dict, from_phone: str, text: str) -> None:
    """Route the message — command or free text — and send the reply."""
    # Stable session_id per phone number (cross-session history)
    session_id = f"wa:{from_phone}"

    # Command dispatch
    cmd = text.split()[0].lower() if text.startswith("/") else ""

    if cmd == "/help":
        await send_message(cfg, to=from_phone, text=_HELP_TEXT)
        return

    if cmd == "/spaces":
        from sarthak.features.ai.tools.spaces import tool_spaces_list
        await send_message(cfg, to=from_phone, text=tool_spaces_list())
        return

    if cmd in _COMMANDS:
        run_key = _COMMANDS[cmd]
        reply = await _run_handler(run_key)
        await send_message(cfg, to=from_phone, text=reply)
        await save_chat_turn(session_id, text, reply)
        return

    # Free text → orchestrator (streaming, buffered)
    reply = await _stream_and_buffer(text, session_id)
    await send_message(cfg, to=from_phone, text=reply)
    await save_chat_turn(session_id, text, reply)


async def _stream_and_buffer(question: str, session_id: str) -> str:
    """Collect the full streaming reply into a single string."""
    history = await load_history_messages(session_id)
    final = ""
    try:
        async for partial in stream_dispatch(
            question, session_id=session_id, message_history=history
        ):
            final = partial
    except Exception as exc:
        log.error("whatsapp_stream_failed", error=str(exc))
        final = f"Error: {exc}"
    return final or "(no response)"


async def _run_handler(run_key: str) -> str:
    """Call the matching _CTX_HANDLERS / _RUN_HANDLERS from the Telegram module (reused)."""
    # Import lazily to avoid circular imports; these are pure functions with no Telegram deps.
    from sarthak.features.channels.telegram.bot import _RUN_HANDLERS, _CTX_HANDLERS
    try:
        if run_key in _CTX_HANDLERS:
            return await _CTX_HANDLERS[run_key](None, None)  # pool=None, ctx=None
        if run_key in _RUN_HANDLERS:
            return await _RUN_HANDLERS[run_key](None)
    except Exception as exc:
        log.error("whatsapp_run_handler_failed", run_key=run_key, error=str(exc))
        return f"Error running {run_key}: {exc}"
    return f"Unknown command: {run_key}"
