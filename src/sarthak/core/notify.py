"""Sarthak AI — Notification helpers for external channels (Telegram/WhatsApp)."""
from __future__ import annotations

import structlog

log = structlog.get_logger(__name__)


async def send_telegram_message(cfg: dict, text: str) -> None:
    """Send a plain message to the configured Telegram user. Fire-and-forget."""
    tg = cfg.get("telegram", {})
    raw_token = tg.get("bot_token", "")
    raw_id    = tg.get("allowed_user_id")
    if not raw_token or not raw_id:
        return
    try:
        from sarthak.storage.encrypt import decrypt_string
        import httpx
        token   = decrypt_string(raw_token) if raw_token.startswith("ENC:") else raw_token
        chat_id = int(raw_id)
        timeout = int(tg.get("timeout_seconds", 30))
        async with httpx.AsyncClient(timeout=timeout) as client:
            await client.post(
                f"https://api.telegram.org/bot{token}/sendMessage",
                json={"chat_id": chat_id, "text": text[:4096], "parse_mode": "Markdown"},
            )
        log.info("telegram_message_sent", preview=text[:60])
    except Exception as exc:
        log.warning("telegram_send_failed", error=str(exc))


async def send_telegram(cfg: dict, message: str, agent_id: str = "") -> None:
    """Send telegram message tagged with agent_id in logs."""
    try:
        tg = cfg.get("telegram", {})
        if tg.get("enabled") is False:
            return
        await send_telegram_message(cfg, message)
        if agent_id:
            log.info("telegram_sent", agent_id=agent_id)
    except Exception as exc:
        log.warning("telegram_send_failed", agent_id=agent_id, error=str(exc))


async def send_whatsapp(cfg: dict, message: str, agent_id: str = "") -> None:
    """Send a WhatsApp message to allowed_phone. Fire-and-forget."""
    try:
        wa = cfg.get("whatsapp", {})
        if not wa.get("enabled"):
            return
        from sarthak.features.channels.whatsapp.client import send_message_standalone
        await send_message_standalone(message)
        if agent_id:
            log.info("whatsapp_sent", agent_id=agent_id)
    except Exception as exc:
        log.warning("whatsapp_send_failed", agent_id=agent_id, error=str(exc))
