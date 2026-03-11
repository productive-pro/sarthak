from __future__ import annotations

import time
import urllib.parse
from pathlib import Path

from fastapi import HTTPException

# Very short-lived in-process cache for the spaces list — avoids re-reading the
# registry JSON on every single API call within the same request burst.
_spaces_list_cache: list[dict] = []
_spaces_list_cache_at: float = 0.0
_SPACES_LIST_TTL = 2.0  # seconds — short enough to pick up changes quickly


def _get_spaces_list() -> list[dict]:
    global _spaces_list_cache, _spaces_list_cache_at
    now = time.monotonic()
    if _spaces_list_cache and (now - _spaces_list_cache_at) < _SPACES_LIST_TTL:
        return _spaces_list_cache
    from sarthak.spaces.store import list_spaces
    _spaces_list_cache = list_spaces()
    _spaces_list_cache_at = now
    return _spaces_list_cache


def invalidate_spaces_list_cache() -> None:
    """Call after any mutation (create/delete/activate space) to force a fresh read."""
    global _spaces_list_cache_at
    _spaces_list_cache_at = 0.0


def get_space_or_404(space_id: str) -> dict:
    decoded = urllib.parse.unquote(space_id)
    spaces = _get_spaces_list()

    def _matches(s: dict) -> bool:
        name = s.get("name", "")
        d    = s.get("directory", "")
        # exact name match
        if name in (space_id, decoded):
            return True
        # exact directory match (decoded absolute path)
        if d == decoded or d == space_id:
            return True
        # last path component match (e.g. "myapp" matches "/home/user/myapp")
        d_path = Path(d)
        return d_path.name in (space_id, decoded)

    match = next((s for s in spaces if _matches(s)), None)
    if not match:
        raise HTTPException(404, "Space not found")
    return match


def resolve_space_dir(space_id: str, body_directory: str = "") -> Path:
    """Resolve the workspace directory from body or space_id URL param.

    body_directory takes precedence (backward-compat). When omitted,
    the space_id is matched against the registry by name or directory suffix.
    """
    if body_directory.strip():
        return Path(body_directory).expanduser().resolve()
    match = get_space_or_404(space_id)
    return Path(match["directory"]).expanduser().resolve()
