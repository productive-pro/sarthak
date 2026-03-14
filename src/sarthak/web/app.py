"""
Sarthak Web — FastAPI backend.

Route ordering is critical:
  Fixed-path routes (/api/spaces/init, /api/spaces/rag/*, etc.) MUST be
  registered BEFORE the roadmap router whose wildcard /{space}/... would
  otherwise swallow them as space names.
"""

from __future__ import annotations

import os
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

from sarthak.core.logging import get_logger
from sarthak.web.routers import (
    REACT_DIST,
    activity_router,
    agents_router,
    chat_router,
    config_router,
    dashboard_router,
    spaces_router,
    spa_router,
)
from sarthak.features.channels.whatsapp.qr import router as whatsapp_qr_router

log = get_logger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Ensure built-in system agents are registered on startup."""
    try:
        from sarthak.agents.scheduler import ensure_builtin_agents

        ensure_builtin_agents()
    except Exception as e:
        log.warning("startup_agents_failed", error=str(e))
    yield


app = FastAPI(title="Sarthak", docs_url=None, redoc_url=None, lifespan=lifespan)


# ── API Routers (order matters for /api/spaces/* vs roadmap router) ───────────

app.include_router(dashboard_router)
app.include_router(chat_router)
app.include_router(config_router)
app.include_router(spaces_router)
app.include_router(agents_router)
app.include_router(activity_router)
app.include_router(whatsapp_qr_router)  # /api/channels/whatsapp/qr|status|logout


# ── Per-space roadmap router — MUST come after all fixed /api/spaces/... paths ─

from sarthak.spaces.roadmap.router import _set_base as _set_roadmap_base
from sarthak.spaces.roadmap.router import roadmap_router  # noqa: E402

app.include_router(roadmap_router, prefix="/api/spaces")

_spaces_root_env = os.environ.get("SARTHAK_SPACES_DIR", "").strip()
if _spaces_root_env:
    _set_roadmap_base(Path(_spaces_root_env))


# ── Static assets ─────────────────────────────────────────────────────────────

_STATIC = Path(__file__).parent / "static"
_STATIC.mkdir(exist_ok=True)
app.mount("/static", StaticFiles(directory=str(_STATIC)), name="static")

# React build assets (hashed filenames like /assets/index-abc123.js)
if REACT_DIST.exists():
    _REACT_ASSETS = REACT_DIST / "assets"
    if _REACT_ASSETS.exists():
        app.mount(
            "/assets", StaticFiles(directory=str(_REACT_ASSETS)), name="react_assets"
        )
    # Serve other root-level static files from react_dist (favicon, svg, etc.)
    app.mount(
        "/ui", StaticFiles(directory=str(REACT_DIST)), name="react_root"
    )


# ── SPA (last) ───────────────────────────────────────────────────────────────

app.include_router(spa_router)


# ── Launch ───────────────────────────────────────────────────────────────────


def launch_web(host: str = "127.0.0.1", port: int = 4848) -> None:
    import uvicorn
    uvicorn.run("sarthak.web.app:app", host=host, port=port, reload=False)
