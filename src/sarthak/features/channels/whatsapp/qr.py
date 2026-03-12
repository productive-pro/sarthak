"""
WhatsApp QR-code login via neonize (wraps whatsmeow / Go).

Routes:
  GET /api/channels/whatsapp/qr        — SSE stream: {"type":"qr","data":"<data-url>"}
                                                      {"type":"connected","jid":"..."}
                                                      {"type":"error","msg":"..."}
  GET /api/channels/whatsapp/status    — JSON: {"connected": bool, "jid": str | null}
  POST /api/channels/whatsapp/logout   — disconnect and delete session
"""
from __future__ import annotations

import asyncio
import io
import json
import structlog
from typing import AsyncGenerator

from fastapi import APIRouter
from fastapi.responses import StreamingResponse

from sarthak.features.channels.whatsapp import SESSION_DB as _SESSION_DB, SESSION_NAME as _SESSION_NAME

log = structlog.get_logger(__name__)
router = APIRouter(prefix="/api/channels/whatsapp", tags=["whatsapp-qr"])

# Shared state (process-wide singleton)
_client = None
_connected_jid: str | None = None


def _make_qr_data_url(qr_text: str) -> str:
    """Render QR text to a PNG data URL using the qrcode library."""
    import qrcode  # type: ignore
    img = qrcode.make(qr_text)
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    import base64
    return "data:image/png;base64," + base64.b64encode(buf.getvalue()).decode()


async def _sse_event(data: dict) -> str:
    return f"data: {json.dumps(data)}\n\n"


async def _qr_stream() -> AsyncGenerator[str, None]:
    """Yield SSE events: qr code frames → connected or error."""
    global _client, _connected_jid

    try:
        from neonize.client import NewClient  # type: ignore
        from neonize.events import ConnectedEv, DisconnectedEv  # type: ignore
    except ImportError:
        yield await _sse_event({"type": "error", "msg": "neonize not installed. Run: pip install neonize"})
        return

    queue: asyncio.Queue[dict] = asyncio.Queue()
    loop = asyncio.get_event_loop()

    # Session name must match neonize_bot so both share the same session store
    from sarthak.features.channels.whatsapp.neonize_bot import _SESSION_NAME
    client = NewClient(_SESSION_NAME)

    def on_qr(_, data: bytes):
        try:
            data_url = _make_qr_data_url(data.decode("utf-8", errors="replace"))
            loop.call_soon_threadsafe(queue.put_nowait, {"type": "qr", "data": data_url})
        except Exception as exc:
            loop.call_soon_threadsafe(queue.put_nowait, {"type": "error", "msg": str(exc)})

    client.event.qr(on_qr)

    @client.event(ConnectedEv)
    def on_connected(cl, ev):
        try:
            jid = cl.me.User if getattr(cl, "me", None) else ""
        except Exception:
            jid = ""
        loop.call_soon_threadsafe(queue.put_nowait, {"type": "connected", "jid": jid})

    @client.event(DisconnectedEv)
    def on_disconnect(_, ev):
        loop.call_soon_threadsafe(queue.put_nowait, {"type": "disconnected"})

    _client = client

    # Run neonize client in a thread (it blocks)
    connect_task = asyncio.create_task(asyncio.to_thread(client.connect))

    try:
        while True:
            try:
                event = await asyncio.wait_for(queue.get(), timeout=60.0)
            except asyncio.TimeoutError:
                yield await _sse_event({"type": "error", "msg": "QR scan timed out"})
                break

            yield await _sse_event(event)

            if event["type"] == "connected":
                _connected_jid = event.get("jid")
                log.info("whatsapp_qr_connected", jid=_connected_jid)
                break
            if event["type"] in ("error", "disconnected"):
                break
    finally:
        connect_task.cancel()


@router.get("/qr")
async def get_qr():
    """SSE stream of QR code frames until connected or error."""
    return StreamingResponse(
        _qr_stream(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@router.get("/status")
async def get_status():
    """Current connection status."""
    return {"connected": _connected_jid is not None, "jid": _connected_jid}


@router.post("/logout")
async def logout():
    """Disconnect and remove session."""
    global _client, _connected_jid
    if _client:
        try:
            await asyncio.to_thread(_client.disconnect)
        except Exception:
            pass
        _client = None
    _connected_jid = None
    if _SESSION_DB.exists():
        _SESSION_DB.unlink()
        log.info("whatsapp_session_deleted")
    return {"ok": True}
