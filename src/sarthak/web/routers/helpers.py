"""
Web router helpers — space resolution and lightweight list caching.

get_space_or_404(space_id)         — raise 404 or return registry entry
resolve_space_dir(space_id, dir)   — return Path for a space
invalidate_spaces_list_cache()     — call after any create/delete/activate
SpaceOrDep                         — FastAPI Depends() typed dependency
"""
from __future__ import annotations

import time
import urllib.parse
from pathlib import Path
from typing import Annotated

from fastapi import Depends, HTTPException

# ── In-process short-lived list cache ────────────────────────────────────────
# Avoids re-reading the registry JSON on every API call within a request burst.
# NOT the factory cache — kept sync so it works from sync helper code.

_spaces_cache: list[dict] = []
_spaces_cache_at: float = 0.0
_SPACES_TTL = 2.0  # seconds


def _get_spaces_list() -> list[dict]:
    global _spaces_cache, _spaces_cache_at
    now = time.monotonic()
    if _spaces_cache and (now - _spaces_cache_at) < _SPACES_TTL:
        return _spaces_cache
    from sarthak.spaces.store import list_spaces
    _spaces_cache = list_spaces()
    _spaces_cache_at = now
    return _spaces_cache


def invalidate_spaces_list_cache() -> None:
    """Call after any mutation (create/delete/activate) to force a fresh read."""
    global _spaces_cache_at
    _spaces_cache_at = 0.0


# ── Space resolution ──────────────────────────────────────────────────────────

def get_space_or_404(space_id: str) -> dict:
    """Resolve space_id (name, directory, or last path component) → registry entry."""
    decoded = urllib.parse.unquote(space_id)
    spaces = _get_spaces_list()

    def _matches(s: dict) -> bool:
        name = s.get("name", "")
        d = s.get("directory", "")
        if name in (space_id, decoded):
            return True
        if d in (space_id, decoded):
            return True
        # last path component: "myapp" matches "/home/user/myapp"
        return Path(d).name in (space_id, decoded)

    match = next((s for s in spaces if _matches(s)), None)
    if not match:
        raise HTTPException(404, f"Space {space_id!r} not found")
    return match


def resolve_space_dir(space_id: str, body_directory: str = "") -> Path:
    """Return workspace Path from body_directory (preferred) or space_id lookup."""
    if body_directory.strip():
        return Path(body_directory).expanduser().resolve()
    match = get_space_or_404(space_id)
    return Path(match["directory"]).expanduser().resolve()


# ── FastAPI dependency ────────────────────────────────────────────────────────

def _space_dep(space_id: str) -> dict:
    """FastAPI Depends()-compatible wrapper for get_space_or_404."""
    return get_space_or_404(space_id)


# Annotated type alias — use as: `space: SpaceEntry` in route signatures
SpaceEntry = Annotated[dict, Depends(_space_dep)]
