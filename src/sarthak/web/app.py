"""
Sarthak Web — FastAPI backend.

Route ordering is critical:
  Fixed-path routes (/api/spaces/init, /api/spaces/rag/*, etc.) MUST be
  registered BEFORE the roadmap router whose wildcard /{space}/... would
  otherwise swallow them as space names.

Middleware stack (outermost first):
  SlowAPI rate limiting → request → handler
"""
from __future__ import annotations

import os
from contextlib import asynccontextmanager
from pathlib import Path

import httpx
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from slowapi import Limiter, _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded
from slowapi.util import get_remote_address

from sarthak.core.logging import get_logger
from sarthak.web.routers import (
    REACT_DIST,
    activity_router,
    agents_router,
    chat_router,
    config_router,
    dashboard_router,
    spaces_router,
    spaces_rag_router,
    spaces_practice_router,
    spaces_settings_router,
    spa_router,
)
from sarthak.features.channels.whatsapp.qr import router as whatsapp_qr_router

log = get_logger(__name__)

# ── Rate limiter (SlowAPI — same syntax as Flask-Limiter) ─────────────────────
limiter = Limiter(key_func=get_remote_address, default_limits=["200/minute"])

# ── Shared httpx client (reused across requests, avoids per-request TCP teardown)
_http_client: httpx.AsyncClient | None = None


def get_http_client() -> httpx.AsyncClient:
    """Return the process-level shared httpx client."""
    assert _http_client is not None, "http client not initialised"
    return _http_client


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Start-up: register built-in agents, open shared HTTP client.
    Shut-down: close HTTP client gracefully.
    """
    global _http_client
    _http_client = httpx.AsyncClient(timeout=5.0, headers={"Connection": "keep-alive"})

    try:
        from sarthak.agents.scheduler import ensure_builtin_agents
        ensure_builtin_agents()
    except Exception as e:
        log.warning("startup_agents_failed", error=str(e))

    yield

    await _http_client.aclose()
    _http_client = None


app = FastAPI(title="Sarthak", docs_url=None, redoc_url=None, lifespan=lifespan)

# ── Middleware ────────────────────────────────────────────────────────────────
app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)


# ── API Routers (order matters for /api/spaces/* vs roadmap router) ───────────
# RAG, practice, and settings routers must be registered BEFORE roadmap router
# which uses a wildcard /{space}/... that would capture those paths.

app.include_router(dashboard_router)
app.include_router(chat_router)
app.include_router(config_router)
app.include_router(spaces_router)
app.include_router(spaces_rag_router)
app.include_router(spaces_practice_router)
app.include_router(spaces_settings_router)
app.include_router(agents_router)
app.include_router(activity_router)
app.include_router(whatsapp_qr_router)  # /api/channels/whatsapp/qr|status|logout


# ── Per-space roadmap router — MUST come after all fixed /api/spaces/... paths ─

from sarthak.spaces.roadmap.router import _set_base as _set_roadmap_base  # noqa: E402
from sarthak.spaces.roadmap.router import roadmap_router                    # noqa: E402

app.include_router(roadmap_router, prefix="/api/spaces")

_spaces_root_env = os.environ.get("SARTHAK_SPACES_DIR", "").strip()
if _spaces_root_env:
    _set_roadmap_base(Path(_spaces_root_env))


# ── Static assets ─────────────────────────────────────────────────────────────

_STATIC = Path(__file__).parent / "static"
_STATIC.mkdir(exist_ok=True)
app.mount("/static", StaticFiles(directory=str(_STATIC)), name="static")

if REACT_DIST.exists():
    _REACT_ASSETS = REACT_DIST / "assets"
    if _REACT_ASSETS.exists():
        app.mount("/assets", StaticFiles(directory=str(_REACT_ASSETS)), name="react_assets")
    app.mount("/ui", StaticFiles(directory=str(REACT_DIST)), name="react_root")


# ── SPA (must be last — catches everything not matched above) ─────────────────

app.include_router(spa_router)


# ── Launch ────────────────────────────────────────────────────────────────────

def launch_web(host: str = "127.0.0.1", port: int = 4848) -> None:
    import uvicorn
    uvicorn.run("sarthak.web.app:app", host=host, port=port, reload=False)
