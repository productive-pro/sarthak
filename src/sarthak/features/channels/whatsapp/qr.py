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
QR login uses a *temporary* ClientFactory with the same SESSION_DB path so
credentials are written to the right file and the bot thread picks them up
on its next connect (or restart).

Only one QR stream can be active at a time (_qr_lock).
"""
from __future__ import annotations

import asyncio
import base64
import io
import json
import threading
from typing import AsyncGenerator

import structlog
from fastapi import APIRouter
from fastapi.responses import StreamingResponse

from sarthak.features.channels.whatsapp import SESSION_DB

log = structlog.get_logger(__name__)
router = APIRouter(prefix="/api/channels/whatsapp", tags=["whatsapp-qr"])

_qr_lock = asyncio.Lock()


def _png_data_url(qr_text: str) -> str:
    import qrcode  # type: ignore
    img = qrcode.make(qr_text)
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return "data:image/png;base64," + base64.b64encode(buf.getvalue()).decode()


def _sse(data: dict) -> str:
    return f"data: {json.dumps(data)}\n\n"


async def _qr_stream() -> AsyncGenerator[str, None]:
    """Yield SSE events until connected, error, or 120 s timeout."""
    if _qr_lock.locked():
        yield _sse({"type": "error", "msg": "QR scan already in progress in another tab."})
        return

    try:
        from neonize.client import ClientFactory  # type: ignore
        from neonize.events import ConnectedEv, DisconnectedEv, OfflineSyncCompletedEv  # type: ignore
    except ImportError:
        yield _sse({"type": "error", "msg": "neonize not installed — run: pip install neonize"})
        return

    async with _qr_lock:
        queue: asyncio.Queue[dict] = asyncio.Queue()
        loop = asyncio.get_event_loop()

        factory = ClientFactory(database_name=SESSION_DB)
        client = factory.new_client(uuid="sarthak-bot")

        # Fired when WhatsApp completes app-state sync after pairing.
        # We MUST wait for this before disconnecting — tearing down earlier
        # leaves 0 signal sessions in the DB and WhatsApp removes the device
        # on the next connect with stream error / EOF.
        _sync_done = threading.Event()

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

        @client.event(OfflineSyncCompletedEv)
        def on_sync_done(_cl, _ev) -> None:
            _sync_done.set()
            loop.call_soon_threadsafe(queue.put_nowait, {"type": "synced"})

        @client.event(DisconnectedEv)
        def on_disconnect(_cl, _ev) -> None:
            loop.call_soon_threadsafe(queue.put_nowait, {"type": "disconnected"})

        connect_task = asyncio.create_task(asyncio.to_thread(client.connect))
        try:
            jid_val = ""
            while True:
                try:
                    event = await asyncio.wait_for(queue.get(), timeout=120.0)
                except asyncio.TimeoutError:
                    yield _sse({"type": "error", "msg": "QR scan timed out (120 s). Try again."})
                    break

                if event["type"] == "synced":
                    # Sync complete — safe to disconnect now
                    log.info("whatsapp_qr_sync_complete", jid=jid_val)
                    break

                yield _sse(event)

                if event["type"] == "connected":
                    jid_val = str(event.get("jid", ""))
                    log.info("whatsapp_qr_connected", jid=jid_val)
                    _persist_jid(jid_val)
                    # Stay connected and wait for OfflineSyncCompletedEv (up to 45 s)
                    # before tearing down — do NOT break here.
                    try:
                        await asyncio.wait_for(
                            asyncio.get_event_loop().run_in_executor(None, lambda: _sync_done.wait(45)),
                            timeout=46,
                        )
                    except Exception:
                        pass
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


# ── Routes ────────────────────────────────────────────────────────────────────

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
    from sarthak.features.channels.whatsapp.neonize_bot import get_connected_jid
    from sarthak.core.config import load_config
    cfg = load_config()
    cfg_jid = str(cfg.get("whatsapp", {}).get("jid", "")) or None
    connected = is_connected()
    live_jid = get_connected_jid() if connected else None
    return {
        "connected": connected,
        "jid": live_jid or (cfg_jid if connected else None),
        "session_db": SESSION_DB,
    }


@router.post("/logout")
async def logout():
    """Stop the bot, delete the session DB, clear config jid."""
    from sarthak.features.channels.whatsapp.neonize_bot import stop_neonize_bot
    from pathlib import Path
    await stop_neonize_bot()

    db_path = Path(SESSION_DB)
    if db_path.exists():
        db_path.unlink()
        log.info("whatsapp_session_deleted", path=SESSION_DB)

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
