"""
Sarthak Spaces — Space persistence and registry.

Single source of truth for all space state.
Each space is a directory containing a `.spaces.json` config file.
A global registry at ~/.sarthak_ai/spaces.json tracks all known spaces.

Public API (space config I/O):
    load_space(path)            → dict | None
    save_space(config, dir)     → Path
    init_space(dir, ...)        → dict
    update_space(updates, dir)  → dict
    record_session(dir, ...)    → None

Registry:
    list_spaces()               → list[dict]
    set_active_space(dir)       → dict
    get_active_space()          → dict | None
    clear_active_space()        → None
    remove_space(dir)           → bool
    rename_space(dir, name)     → dict

Profile store (SpaceProfile inside .spaces.json):
    load_profile(dir)           → SpaceProfile | None
    save_profile(dir, profile)  → None
    init_space_profile(dir, ...) → SpaceProfile
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import threading

from sarthak.core.logging import get_logger

log = get_logger(__name__)

SPACE_FILE = ".spaces.json"
_SPACES_DIR = Path.home() / ".sarthak_ai"
_REGISTRY = _SPACES_DIR / "spaces.json"
_ACTIVE_FILE = _SPACES_DIR / "active_space.json"
_PROFILE_KEY = "__profile__"
_REGISTRY_LOCK = threading.Lock()

# ── Registry write-through cache ──────────────────────────────────────────────
# Populated on first read; invalidated on every write (_save_registry keeps it
# in sync so reads after writes in the same process are always consistent).
#
# ⚠ Multi-worker caveat: with `uvicorn --workers N` each worker has its own
# private _registry_cache.  A registry write in worker A invalidates that
# worker's cache, but workers B–N continue serving stale data until their
# next disk read.  For multi-worker deployments either disable this cache or
# use a file-watcher / shared-memory mechanism.
_registry_cache: list[dict[str, Any]] | None = None


# ── Timestamp ─────────────────────────────────────────────────────────────────

def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


# ── Discovery ─────────────────────────────────────────────────────────────────

def _find_space(start: Path | None = None) -> Path | None:
    """Walk up from start (default cwd) to find a .spaces.json."""
    p = (start or Path.cwd()).resolve()
    for parent in [p, *p.parents]:
        candidate = parent / SPACE_FILE
        if candidate.exists():
            return candidate
    return None


# ══════════════════════════════════════════════════════════════════════════════
# Space config I/O
# ══════════════════════════════════════════════════════════════════════════════

def load_space(path: Path | None = None) -> dict[str, Any] | None:
    """Load space config. path may be a directory or direct file path."""
    candidate = path
    if candidate and candidate.is_dir():
        candidate = candidate / SPACE_FILE
    if not candidate:
        candidate = _find_space()
    if not candidate or not candidate.exists():
        return None
    try:
        return json.loads(candidate.read_text(encoding="utf-8"))
    except Exception as exc:
        log.warning("space_load_failed", path=str(candidate), error=str(exc))
        return None


def save_space(config: dict[str, Any], directory: Path) -> Path:
    """Write space config to directory/.spaces.json."""
    path = directory / SPACE_FILE
    path.write_text(json.dumps(config, indent=2, ensure_ascii=False), encoding="utf-8")
    return path


def init_space(
    directory: Path,
    name: str,
    description: str = "",
    goal: str = "",
    tags: list[str] | None = None,
) -> dict[str, Any]:
    """Create a new space config. Returns the config dict."""
    directory = directory.resolve()
    config: dict[str, Any] = {
        "name": name,
        "description": description,
        "goal": goal,
        "tags": tags or [],
        "directory": str(directory),
        "created_at": _now(),
        "updated_at": _now(),
        "sessions": [],           # list of {start, end, summary}
        "skills": [],             # mastered concept tags (auto-updated)
        "preferred_tools": [],    # e.g. ["uv", "polars", "mlflow"]
        "ai_notes": "",           # human-readable notes (not profile blob)
    }
    save_space(config, directory)
    _register_space(config)
    log.info("space_created", name=name, dir=str(directory))
    return config


def update_space(updates: dict[str, Any], directory: Path | None = None) -> dict[str, Any]:
    """Merge updates into existing space config and save."""
    ws_file = _find_space(directory)
    if not ws_file:
        raise FileNotFoundError("No space found. Run: sarthak spaces init")
    config = json.loads(ws_file.read_text(encoding="utf-8"))
    config.update(updates)
    config["updated_at"] = _now()
    ws_file.write_text(json.dumps(config, indent=2, ensure_ascii=False), encoding="utf-8")
    _register_space(config)
    return config


def record_session(
    directory: Path | None,
    summary: str,
    start: datetime,
    end: datetime,
) -> None:
    """Append a completed session record to the space config."""
    try:
        update_space(
            {"sessions": _append_session(directory, {
                "start": start.isoformat(),
                "end": end.isoformat(),
                "summary": summary,
            })},
            directory,
        )
    except FileNotFoundError:
        pass


def _append_session(directory: Path | None, session: dict) -> list:
    ws_file = _find_space(directory)
    if not ws_file:
        return [session]
    config = json.loads(ws_file.read_text(encoding="utf-8"))
    sessions = config.get("sessions", [])
    sessions.append(session)
    return sessions[-50:]


def get_space_context(directory: Path | None = None) -> str:
    """Return a compact text summary of the space for injecting into agent prompts."""
    ws = load_space(directory)
    if not ws:
        active = get_active_space()
        if active:
            ws = load_space(Path(active["directory"]))
    if not ws:
        return ""
    lines = [
        f"## Active Space: {ws['name']}",
        f"**Goal**: {ws['goal']}",
        f"**Description**: {ws['description']}",
    ]
    if ws.get("tags"):
        lines.append(f"**Tags**: {', '.join(ws['tags'])}")
    if ws.get("preferred_tools"):
        lines.append(f"**Tools**: {', '.join(ws['preferred_tools'])}")
    if ws.get("ai_notes"):
        lines.append(f"\n**Notes**:\n{ws['ai_notes'][:600]}")
    recent = ws.get("sessions", [])[-3:]
    if recent:
        lines.append("\n**Recent sessions**:")
        for s in reversed(recent):
            lines.append(f"- {s['start'][:10]}: {s['summary'][:120]}")
    return "\n".join(lines)


# ══════════════════════════════════════════════════════════════════════════════
# Registry
# ══════════════════════════════════════════════════════════════════════════════

def list_spaces() -> list[dict[str, Any]]:
    return _load_registry()


def set_active_space(directory: Path) -> dict[str, Any]:
    """Set the active space by directory. Returns space config."""
    ws = load_space(directory)
    if not ws:
        raise FileNotFoundError(f"No space found in {directory}")
    _ensure_dir()
    payload = {
        "directory": ws.get("directory", str(directory)),
        "name": ws.get("name", ""),
        "activated_at": _now(),
    }
    _ACTIVE_FILE.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    return ws


def get_active_space() -> dict[str, Any] | None:
    if not _ACTIVE_FILE.exists():
        return None
    try:
        return json.loads(_ACTIVE_FILE.read_text(encoding="utf-8"))
    except Exception:
        return None


def clear_active_space() -> None:
    if _ACTIVE_FILE.exists():
        _ACTIVE_FILE.unlink()


def remove_space(directory: Path) -> bool:
    entries = _load_registry()
    target = str(directory.resolve())
    filtered = [e for e in entries if e.get("directory") != target]
    removed = len(filtered) != len(entries)
    if removed:
        _save_registry(filtered)
    active = get_active_space()
    if active and active.get("directory") == target:
        clear_active_space()
    return removed


def rename_space(directory: Path, name: str) -> dict[str, Any]:
    return update_space({"name": name}, directory)


def set_space_goal(directory: Path, goal: str) -> dict[str, Any]:
    return update_space({"goal": goal}, directory)


def set_space_tags(directory: Path, tags: list[str]) -> dict[str, Any]:
    return update_space({"tags": tags}, directory)


# ── Registry internals ─────────────────────────────────────────────────────────

def _ensure_dir() -> None:
    _SPACES_DIR.mkdir(parents=True, exist_ok=True)


def _load_registry() -> list[dict[str, Any]]:
    global _registry_cache
    with _REGISTRY_LOCK:
        if _registry_cache is not None:
            return _registry_cache
        if not _REGISTRY.exists():
            _registry_cache = []
            return _registry_cache
        data = json.loads(_REGISTRY.read_text(encoding="utf-8"))
        _registry_cache = data if isinstance(data, list) else []
        return _registry_cache


def _save_registry(entries: list[dict[str, Any]]) -> None:
    global _registry_cache
    _ensure_dir()
    with _REGISTRY_LOCK:
        _REGISTRY.write_text(json.dumps(entries, indent=2), encoding="utf-8")
        _registry_cache = entries  # keep cache in sync


def _register_space(config: dict[str, Any]) -> None:
    entries = _load_registry()
    directory = str(config.get("directory", ""))
    if not directory:
        return
    payload = {
        "name": config.get("name", ""),
        "directory": directory,
        "description": config.get("description", ""),
        "goal": config.get("goal", ""),
        "tags": config.get("tags", []),
        "updated_at": _now(),
    }
    for e in entries:
        if e.get("directory") == directory:
            e.update(payload)
            if not e.get("created_at"):
                e["created_at"] = config.get("created_at", _now())
            _save_registry(entries)
            return
    payload["created_at"] = config.get("created_at", _now())
    entries.append(payload)
    _save_registry(entries)


# ══════════════════════════════════════════════════════════════════════════════
# Profile store — SpaceProfile inside .spaces.json
# ══════════════════════════════════════════════════════════════════════════════

def load_profile(workspace_dir: Path):  # -> SpaceProfile | None
    """Load SpaceProfile from .spaces.json __profile__ key."""
    from sarthak.spaces.models import SpaceProfile
    ws = load_space(workspace_dir)
    if not ws:
        return None
    raw = ws.get(_PROFILE_KEY)
    if not raw:
        return None
    try:
        return SpaceProfile.model_validate(raw)
    except Exception:
        return None


def save_profile(workspace_dir: Path, profile) -> None:  # profile: SpaceProfile
    """Persist SpaceProfile inside .spaces.json and sync metadata fields."""
    ws = load_space(workspace_dir) or init_space(
        workspace_dir,
        name=profile.domain,
        description=f"Sarthak Space: {profile.domain}",
        goal=profile.learner.goal or "Mastery",
    )
    ws[_PROFILE_KEY] = profile.model_dump()
    ws["preferred_tools"] = profile.expert_tools_installed
    ws["skills"] = profile.learner.mastered_concepts[-10:]
    ws["tags"] = list(dict.fromkeys([profile.domain, profile.space_type.value]))
    ws["updated_at"] = _now()
    save_space(ws, workspace_dir)
    _register_space(ws)


def init_space_profile(
    workspace_dir: Path,
    space_type,  # SpaceType
    background: str = "",
    learner_name: str = "",
):  # -> SpaceProfile
    """Create a new SpaceProfile from domain defaults and persist it."""
    from sarthak.spaces.domains import get_domain
    from sarthak.spaces.models import LearnerProfile, SpaceProfile
    domain = get_domain(space_type)
    profile = SpaceProfile(
        space_type=space_type,
        domain=domain["domain_name"],
        learner=LearnerProfile(name=learner_name, background=background),
        recommended_tools=domain["tools"],
        workspace_dir=str(workspace_dir),
    )
    save_profile(workspace_dir, profile)
    return profile
