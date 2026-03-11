"""
Sarthak AI — Desktop notification helper.

Cross-platform:
  Linux   : dunstify (dunst) → notify-send fallback
  macOS   : osascript (built-in)
  Windows : win10toast or plyer fallback

Saves user-approved tips to local SQLite.
"""
from __future__ import annotations

import asyncio
import sys
import structlog

log = structlog.get_logger(__name__)

# Keep old name as alias so existing callers don't break
async def notify_recommendation(recommendation: str, pool=None) -> None:
    await notify_desktop(recommendation, pool=pool)


async def notify_desktop(text: str, pool=None) -> None:
    """
    Surface a notification with an optional 'Save tip' action.
    Falls back gracefully if no notification backend is available.
    """
    text = text.strip()
    if not text:
        return

    display = text[:500]
    log.info("notification_sending", preview=display[:80])

    try:
        from sarthak.storage.helpers import write_alert
        await write_alert(level="info", source="notification",
                          message=display, details={"type": "recommendation"})
    except Exception:
        pass

    saved = False
    if sys.platform.startswith("linux"):
        saved = await _notify_linux(display)
    elif sys.platform == "darwin":
        await _notify_macos(display)
    elif sys.platform == "win32":
        await _notify_windows(display)

    if saved:
        await _save_tip(text)


async def _notify_linux(text: str) -> bool:
    """Try dunstify (interactive), fall back to notify-send (fire-and-forget)."""
    import shlex, os
    extra = shlex.split(os.environ.get("SARTHAK_NOTIFY_ARGS", ""))

    # Try dunstify with an action button
    try:
        proc = await asyncio.create_subprocess_exec(
            "dunstify",
            "--action=worth,Worth it!",
            "--timeout=30000",
            "--urgency=normal",
            "Sarthak", text,
            *extra,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.DEVNULL,
        )
        stdout, _ = await asyncio.wait_for(proc.communicate(), timeout=35)
        action = stdout.decode().strip()
        if action == "worth":
            log.info("tip_saved_by_user", tip=text[:80])
            return True
        return False
    except asyncio.TimeoutError:
        return False
    except FileNotFoundError:
        pass  # dunstify not installed

    # Fall back to notify-send (no action button)
    try:
        proc = await asyncio.create_subprocess_exec(
            "notify-send", "Sarthak", text,
            stderr=asyncio.subprocess.DEVNULL,
        )
        await asyncio.wait_for(proc.communicate(), timeout=5)
    except (FileNotFoundError, asyncio.TimeoutError):
        log.debug("no_linux_notification_tool_found")
    return False


async def _notify_macos(text: str) -> None:
    script = (
        f'display notification "{text[:200]}" with title "Sarthak"'
    )
    try:
        proc = await asyncio.create_subprocess_exec(
            "osascript", "-e", script,
            stderr=asyncio.subprocess.DEVNULL,
        )
        await asyncio.wait_for(proc.communicate(), timeout=10)
    except Exception as exc:
        log.debug("macos_notification_failed", error=str(exc))


async def _notify_windows(text: str) -> None:
    # Try win10toast (pip install win10toast)
    try:
        from win10toast import ToastNotifier  # type: ignore[import]
        toaster = ToastNotifier()
        toaster.show_toast("Sarthak", text[:200], duration=10, threaded=True)
        return
    except ImportError:
        pass
    # Fall back to plyer
    try:
        from plyer import notification  # type: ignore[import]
        notification.notify(title="Sarthak", message=text[:200], timeout=10)
    except Exception as exc:
        log.debug("windows_notification_failed", error=str(exc))


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


async def _save_tip(tip: str) -> None:
    try:
        from sarthak.storage.helpers import save_tip
        await save_tip(tip)
        log.info("tip_saved")
    except Exception as exc:
        log.error("tip_save_failed", error=str(exc))
