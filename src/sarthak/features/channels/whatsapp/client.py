"""
WhatsApp Meta Cloud API — thin sender client.

Usage:
    # In-context (when you have cfg):
    await send_message(cfg, to="+91...", text="Hello")

    # Standalone (reads config itself, used by scheduler/runner):
    await send_message_standalone("Agent output here")
"""
from __future__ import annotations

import structlog
import httpx

from sarthak.core.constants import WHATSAPP_MESSAGE_LIMIT

log = structlog.get_logger(__name__)

_API_BASE = "https://graph.facebook.com/v19.0"


def _get_whatsapp_cfg(cfg: dict) -> dict:
    return cfg.get("whatsapp", {})


async def send_message(cfg: dict, to: str, text: str) -> None:
    """Send a plain-text WhatsApp message, chunked to WHATSAPP_MESSAGE_LIMIT."""
    wa = _get_whatsapp_cfg(cfg)
    if not wa.get("enabled"):
        return

    phone_number_id = wa.get("phone_number_id", "")
    access_token = wa.get("access_token", "")
    if not phone_number_id or not access_token:
        log.warning("whatsapp_send_skipped", reason="missing phone_number_id or access_token")
        return

    url = f"{_API_BASE}/{phone_number_id}/messages"
    headers = {
        "Authorization": f"Bearer {access_token}",
        "Content-Type": "application/json",
    }

    chunks = [text[i: i + WHATSAPP_MESSAGE_LIMIT] for i in range(0, len(text), WHATSAPP_MESSAGE_LIMIT)]
    timeout = int(wa.get("timeout_seconds", 30))

    async with httpx.AsyncClient(timeout=timeout) as client:
        for chunk in chunks:
            payload = {
                "messaging_product": "whatsapp",
                "to": to,
                "type": "text",
                "text": {"body": chunk},
            }
            try:
                resp = await client.post(url, headers=headers, json=payload)
                resp.raise_for_status()
            except Exception as exc:
                log.warning("whatsapp_send_failed", to=to, error=str(exc))


async def send_message_standalone(text: str) -> None:
    """Send to the configured allowed_phone without needing an active request context.
    Used by agent scheduler and runner for push notifications."""
    from sarthak.core.config import load_config
    cfg = load_config()
    wa = _get_whatsapp_cfg(cfg)
    if not wa.get("enabled"):
        return
    to = wa.get("allowed_phone", "")
    if not to:
        log.warning("whatsapp_standalone_skipped", reason="allowed_phone not set")
        return
    await send_message(cfg, to=to, text=text)
