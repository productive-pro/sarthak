from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse, HTMLResponse

router = APIRouter()


def _resolve_react_dist() -> Path:
    """
    Locate the bundled React dist directory.

    Works in three environments:
      1. Installed wheel  — importlib.resources (Python 3.11+ Traversable)
      2. Source checkout  — __file__-relative path
      3. PyInstaller binary — sys._MEIPASS-relative path
    """
    import importlib.resources
    import sys

    # PyInstaller one-file binary
    base = getattr(sys, "_MEIPASS", None)
    if base:
        p = Path(base) / "sarthak" / "web" / "react_dist"
        if p.is_dir():
            return p

    # Installed wheel or editable install — use importlib.resources
    try:
        ref = importlib.resources.files("sarthak.web") / "react_dist"
        # Materialise to a real filesystem path (works for zip-safe wheels too)
        with importlib.resources.as_file(ref) as p:
            if Path(p).is_dir():
                return Path(p)
    except Exception:
        pass

    # Source-tree fallback
    return Path(__file__).resolve().parent.parent / "react_dist"


_REACT_DIST = _resolve_react_dist()
_REACT_HTML = _REACT_DIST / "index.html"
REACT_DIST = _REACT_DIST

_MISSING_FRONTEND_HTML = """
<!DOCTYPE html><html><head><title>Sarthak — Frontend Not Found</title>
<style>body{font-family:sans-serif;max-width:640px;margin:60px auto;padding:0 20px;}
pre{background:#f4f4f4;padding:12px;border-radius:4px;overflow-x:auto;}</style>
</head><body>
<h2>Frontend assets not found</h2>
<p>The React frontend was not bundled with this installation.<br>
Run the following to build it, then restart the server:</p>
<pre>cd /path/to/sarthak-repo\nbash rebuild_frontend.sh\nuv pip install -e .</pre>
<p>If you installed from PyPI and see this message, please
<a href="https://github.com/productive-pro/sarthak/issues">open an issue</a>.</p>
</body></html>
"""


def _read_spa_html() -> str:
    if _REACT_HTML.exists():
        return _REACT_HTML.read_text(encoding="utf-8")
    return _MISSING_FRONTEND_HTML


@router.get("/", response_class=HTMLResponse)
async def spa() -> str:
    return _read_spa_html()


@router.get("/roadmap", response_class=HTMLResponse)
async def roadmap_ui() -> str:
    # Roadmap is served by the React SPA — same index.html with hash routing
    return _read_spa_html()


@router.get("/{full_path:path}", response_class=HTMLResponse, include_in_schema=False)
async def spa_fallback(full_path: str):
    if full_path.startswith("api/"):
        raise HTTPException(404)
    if _REACT_DIST.exists():
        candidate = (_REACT_DIST / full_path).resolve()
        if candidate.is_file() and _REACT_DIST in candidate.parents:
            return FileResponse(candidate)
    return _read_spa_html()
