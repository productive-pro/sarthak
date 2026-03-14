"""
WhatsApp QR-code login — web routes for initial pairing.

Routes:
  GET  /api/channels/whatsapp/qr      — SSE stream of QR code frames
                                          events: {"type":"qr","data":"<png data-url>"}
                                                  {"type":"connected","jid":"..."}
                                                  {"type":"error","msg":"..."}
  GET  /api/channels/whatsapp/status  — {"connected": bool, "jid": str|null}
  POST /api/channels/whatsapp/logout  — stop bot, delete session DB

Design notes
------------
QR login is done through a *separate* temporary neonize client so the
running neonize_bot is never interrupted mid-session. Once pairing
completes both share the same SESSION_DB file, so the bot thread picks up
the new credentials on its next connect (or restart).

Only one QR stream can be active at a time (_qr_lock). A second request
waits rather than spawning a conflicting client.
"""
from __future__ import annotations

import asyncio
import base64
import io
import json
from typing import AsyncGenerator

import structlog
from fastapi import APIRouter
from fastapi.responses import StreamingResponse

from sarthak.features.channels.whatsapp import SESSION_DB as _SESSION_DB, SESSION_NAME as _SESSION_NAME

log = structlog.get_logger(__name__)
router = APIRouter(prefix="/api/channels/whatsapp", tags=["whatsapp-qr"])

# Serialise QR requests — only one pairing attempt at a time.
_qr_lock = asyncio.Lock()


def _png_data_url(qr_text: str) -> str:
    """Render QR text to a PNG data-URL using the qrcode library."""
    import qrcode  # type: ignore
    img = qrcode.make(qr_text)
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return "data:image/png;base64," + base64.b64encode(buf.getvalue()).decode()


def _sse(data: dict) -> str:
    """Format one SSE data frame."""
    return f"data: {json.dumps(data)}\n\n"


async def _qr_stream() -> AsyncGenerator[str, None]:
    """Yield SSE events until connected, error, or 120 s timeout."""
    if _qr_lock.locked():
        yield _sse({"type": "error", "msg": "QR scan already in progress in another tab."})
        return

    try:
        from neonize.client import NewClient  # type: ignore
        from neonize.events import ConnectedEv, DisconnectedEv  # type: ignore
    except ImportError:
        yield _sse({"type": "error", "msg": "neonize not installed — run: pip install neonize"})
        return

    async with _qr_lock:
        queue: asyncio.Queue[dict] = asyncio.Queue()
        loop = asyncio.get_event_loop()

        # Temporary client solely for pairing — shares SESSION_NAME so credentials
        # are written to the same DB the bot thread reads.
        client = NewClient(_SESSION_NAME)

        def on_qr(_, data: bytes) -> None:
            try:
                data_url = _png_data_url(data.decode("utf-8", errors="replace"))
                loop.call_soon_threadsafe(queue.put_nowait, {"type": "qr", "data": data_url})
            except Exception as exc:
                loop.call_soon_threadsafe(queue.put_nowait, {"type": "error", "msg": str(exc)})

        client.event.qr(on_qr)

        @client.event(ConnectedEv)
        def on_connected(cl, _ev) -> None:
            try:
                jid = cl.me.User if getattr(cl, "me", None) else ""
            except Exception:
                jid = ""
            loop.call_soon_threadsafe(queue.put_nowait, {"type": "connected", "jid": jid})

        @client.event(DisconnectedEv)
        def on_disconnect(_cl, _ev) -> None:
            loop.call_soon_threadsafe(queue.put_nowait, {"type": "disconnected"})

        # client.connect() blocks — run in thread pool.
        connect_task = asyncio.create_task(asyncio.to_thread(client.connect))
        try:
            while True:
                try:
                    event = await asyncio.wait_for(queue.get(), timeout=120.0)
                except asyncio.TimeoutError:
                    yield _sse({"type": "error", "msg": "QR scan timed out (120 s). Try again."})
                    break

                yield _sse(event)

                if event["type"] == "connected":
                    log.info("whatsapp_qr_connected", jid=event.get("jid"))
                    # Update config.toml jid so the bot knows who to accept messages from.
                    _persist_jid(str(event.get("jid", "")))
                    break
                if event["type"] in ("error", "disconnected"):
                    break
        finally:
            connect_task.cancel()
            try:
                await asyncio.to_thread(client.disconnect)
            except Exception:
                pass


def _persist_jid(jid: str) -> None:
    """Write whatsapp.jid to config.toml after a successful QR login."""
    if not jid:
        return
    try:
        import tomlkit
        from sarthak.core.config import get_config_path
        path = get_config_path()
        data = tomlkit.parse(path.read_text())
        wa = data.setdefault("whatsapp", tomlkit.table())
        wa["jid"] = jid
        wa["enabled"] = True
        wa["mode"] = "qr"
        path.write_text(tomlkit.dumps(data))
        log.info("whatsapp_jid_persisted", jid=jid)
    except Exception as exc:
        log.warning("whatsapp_jid_persist_failed", error=str(exc))


# ── Routes ──────────────────────────────────────────────────────────────────────

@router.get("/qr")
async def get_qr():
    """SSE stream of QR code frames until connected, error, or timeout."""
    return StreamingResponse(
        _qr_stream(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@router.get("/status")
async def get_status():
    """Live connection status from the neonize bot thread."""
    from sarthak.features.channels.whatsapp import is_connected
    from sarthak.core.config import load_config
    cfg = load_config()
    jid = str(cfg.get("whatsapp", {}).get("jid", "")) or None
    return {"connected": is_connected(), "jid": jid if is_connected() else None}


@router.post("/logout")
async def logout():
    """Stop the bot, delete the session DB, clear config jid."""
    from sarthak.features.channels.whatsapp.neonize_bot import stop_neonize_bot
    await stop_neonize_bot()

    if _SESSION_DB.exists():
        _SESSION_DB.unlink()
        log.info("whatsapp_session_deleted")

    # Clear jid from config so the bot doesn't auto-restart with stale creds.
    try:
        import tomlkit
        from sarthak.core.config import get_config_path
        path = get_config_path()
        data = tomlkit.parse(path.read_text())
        wa = data.get("whatsapp", {})
        if isinstance(wa, dict):
            wa["jid"] = ""
            wa["enabled"] = False
        path.write_text(tomlkit.dumps(data))
    except Exception as exc:
        log.warning("whatsapp_logout_config_clear_failed", error=str(exc))

    return {"ok": True}
