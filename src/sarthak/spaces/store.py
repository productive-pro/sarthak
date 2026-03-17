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
import shutil
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import threading

from sarthak.core.logging import get_logger

log = get_logger(__name__)

SPACE_FILE = ".spaces.json"
_SPACES_DIR = Path.home() / ".sarthak_ai"
_REGISTRY = _SPACES_DIR / "spaces.json"
_ACTIVE_FILE = _SPACES_DIR / "active_space.json"
_TRASH_RETENTION_DAYS = 30
_PROFILE_KEY = "__profile__"
_REGISTRY_LOCK = threading.Lock()

# ── Registry write-through cache ──────────────────────────────────────────────
# Invalidated on write (same process) and detected stale via file mtime check.
# Mtime check is O(1) (single stat syscall) so it's safe to do on every read.
_registry_cache: list[dict[str, Any]] | None = None
_registry_mtime: float = 0.0   # last known mtime of registry file


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
    from sarthak.core.utils import write_atomic
    write_atomic(path, json.dumps(config, indent=2, ensure_ascii=False))
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
    from sarthak.core.utils import write_atomic
    write_atomic(ws_file, json.dumps(config, indent=2, ensure_ascii=False))
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
    return _load_registry_filtered(include_trashed=False)


def list_trashed_spaces() -> list[dict[str, Any]]:
    return _load_registry_filtered(include_trashed=True)


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
    from sarthak.core.utils import write_atomic
    write_atomic(_ACTIVE_FILE, json.dumps(payload, indent=2))
    # Invalidate scheduler's active-space cache so next tick sees the new space immediately
    try:
        from sarthak.agents.scheduler import invalidate_active_space_cache
        invalidate_active_space_cache()
    except Exception:
        pass
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
    # Invalidate scheduler's active-space cache
    try:
        from sarthak.agents.scheduler import invalidate_active_space_cache
        invalidate_active_space_cache()
    except Exception:
        pass


def remove_space(directory: Path) -> bool:
    target = str(directory.resolve())
    with _REGISTRY_LOCK:
        entries = _load_registry_locked()
        filtered = [e for e in entries if e.get("directory") != target]
        removed = len(filtered) != len(entries)
        if removed:
            _save_registry_locked(filtered)
    active = get_active_space()
    if active and active.get("directory") == target:
        clear_active_space()
    return removed


def trash_space(directory: Path, name: str) -> dict[str, Any]:
    """Move a space to trash and keep it in registry for retention window."""
    target = str(directory.resolve())
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    trash_root = Path.home() / ".sarthak_ai" / "trash" / "spaces"
    trash_root.mkdir(parents=True, exist_ok=True)
    trash_path = trash_root / f"{Path(target).name}_{stamp}"

    if Path(target).exists():
        shutil.move(target, str(trash_path))

    with _REGISTRY_LOCK:
        entries = _load_registry_locked()
        for e in entries:
            if e.get("directory") == target:
                e["name"] = name or e.get("name", "")
                e["trashed_at"] = _now()
                e["trashed_path"] = str(trash_path)
                _save_registry_locked(entries)
                break
        else:
            entries.append({
                "name": name,
                "directory": target,
                "created_at": _now(),
                "updated_at": _now(),
                "trashed_at": _now(),
                "trashed_path": str(trash_path),
            })
            _save_registry_locked(entries)

    active = get_active_space()
    if active and active.get("directory") == target:
        clear_active_space()  # this also invalidates the agent cache
    return {"directory": target, "trashed_path": str(trash_path)}


def recover_space(directory: Path) -> dict[str, Any]:
    """Restore a trashed space back to its original directory."""
    target = str(directory.resolve())
    with _REGISTRY_LOCK:
        entries = _load_registry_locked()
        for e in entries:
            if e.get("directory") == target and e.get("trashed_at"):
                trash_path = e.get("trashed_path") or ""
                if not trash_path:
                    raise FileNotFoundError("No trash path recorded.")
                if Path(target).exists():
                    # Graceful handling: do not overwrite existing data.
                    # Mark as recovered, keep a pointer to the trashed copy.
                    e.pop("trashed_at", None)
                    e.pop("trashed_path", None)
                    e["updated_at"] = _now()
                    e["recovery_status"] = "already_exists"
                    e["conflict_trash_path"] = trash_path
                    _save_registry_locked(entries)
                    return e
                shutil.move(trash_path, target)
                e.pop("trashed_at", None)
                e.pop("trashed_path", None)
                e["updated_at"] = _now()
                _save_registry_locked(entries)
                return e
    raise FileNotFoundError("Trashed space not found.")


def delete_space_permanently(directory: Path) -> bool:
    """Permanently delete a trashed space (registry + trash folder)."""
    target = str(directory.resolve())
    removed = False
    with _REGISTRY_LOCK:
        entries = _load_registry_locked()
        filtered: list[dict[str, Any]] = []
        for e in entries:
            if e.get("directory") == target and e.get("trashed_at"):
                removed = True
                trash_path = e.get("trashed_path") or ""
                if trash_path and Path(trash_path).exists():
                    shutil.rmtree(trash_path, ignore_errors=True)
                continue
            filtered.append(e)
        if removed:
            _save_registry_locked(filtered)
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


def _load_registry_locked() -> list[dict[str, Any]]:
    """Load registry while holding _REGISTRY_LOCK (no lock inside)."""
    global _registry_cache, _registry_mtime
    if not _REGISTRY.exists():
        _registry_cache = []
        return _registry_cache
    # Invalidate cache if file was modified by another process
    try:
        mtime = _REGISTRY.stat().st_mtime
    except OSError:
        mtime = 0.0
    if _registry_cache is not None and mtime == _registry_mtime:
        return _registry_cache
    try:
        data = json.loads(_REGISTRY.read_text(encoding="utf-8"))
    except Exception:
        data = []
    _registry_cache = data if isinstance(data, list) else []
    _registry_mtime = mtime
    return _registry_cache


def _load_registry_filtered(include_trashed: bool) -> list[dict[str, Any]]:
    with _REGISTRY_LOCK:
        entries = _load_registry_locked()
        entries, changed = _purge_expired_locked(entries)
        if changed:
            _save_registry_locked(entries)
        if include_trashed:
            return [e for e in entries if e.get("trashed_at")]
        return [e for e in entries if not e.get("trashed_at")]


def _save_registry(entries: list[dict[str, Any]]) -> None:
    global _registry_cache, _registry_mtime
    _ensure_dir()
    with _REGISTRY_LOCK:
        _save_registry_locked(entries)


def _save_registry_locked(entries: list[dict[str, Any]]) -> None:
    """Save registry while holding _REGISTRY_LOCK (no lock inside)."""
    global _registry_cache, _registry_mtime
    from sarthak.core.utils import write_atomic
    write_atomic(_REGISTRY, json.dumps(entries, indent=2))
    _registry_cache = entries  # keep in-process cache in sync
    try:
        _registry_mtime = _REGISTRY.stat().st_mtime
    except OSError:
        _registry_mtime = 0.0


def _register_space(config: dict[str, Any]) -> None:
    with _REGISTRY_LOCK:
        entries = _load_registry_locked()
        directory = str(config.get("directory", ""))
        if not directory:
            return
        # Extract space_type and domain from the profile blob if present
        _profile_blob = config.get("__profile__") or {}
        _space_type = (
            _profile_blob.get("space_type") or config.get("space_type", "")
        )
        _domain = (
            _profile_blob.get("domain") or config.get("domain", "")
        )
        payload = {
            "name": config.get("name", ""),
            "directory": directory,
            "description": config.get("description", ""),
            "goal": config.get("goal", ""),
            "tags": config.get("tags", []),
            "space_type": _space_type,
            "domain": _domain,
            "updated_at": _now(),
        }
        for e in entries:
            if e.get("directory") == directory:
                e.update(payload)
                if not e.get("created_at"):
                    e["created_at"] = config.get("created_at", _now())
                # Preserve trash metadata if present
                if e.get("trashed_at"):
                    e["trashed_at"] = e.get("trashed_at")
                    e["trashed_path"] = e.get("trashed_path")
                _save_registry_locked(entries)
                return
        payload["created_at"] = config.get("created_at", _now())
        entries.append(payload)
        _save_registry_locked(entries)


def _parse_iso(ts: str) -> datetime | None:
    try:
        return datetime.fromisoformat(ts.replace("Z", "+00:00")).astimezone(timezone.utc)
    except Exception:
        return None


def _purge_expired_locked(entries: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], bool]:
    """Remove trashed entries older than retention window."""
    now = datetime.now(timezone.utc)
    keep: list[dict[str, Any]] = []
    changed = False
    for e in entries:
        trashed_at = e.get("trashed_at")
        if not trashed_at:
            keep.append(e)
            continue
        dt = _parse_iso(trashed_at)
        if dt and now - dt > timedelta(days=_TRASH_RETENTION_DAYS):
            trash_path = e.get("trashed_path") or ""
            if trash_path:
                shutil.rmtree(trash_path, ignore_errors=True)
            changed = True
            continue
        keep.append(e)
    return keep, changed


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
    """Persist SpaceProfile inside .spaces.json, sync metadata, and update Space Memory files."""
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


def save_clarification_answers(workspace_dir: Path, answers: str) -> None:
    """Persist clarification answers in .spaces.json so future roadmap regenerations use them."""
    ws = load_space(workspace_dir)
    if ws is None:
        return
    ws["clarification_answers"] = answers
    ws["updated_at"] = _now()
    save_space(ws, workspace_dir)


def load_clarification_answers(workspace_dir: Path) -> str:
    """Load persisted clarification answers, or empty string if none."""
    ws = load_space(workspace_dir)
    if ws is None:
        return ""
    return ws.get("clarification_answers", "")


def init_space_profile(
    workspace_dir: Path,
    space_type,  # SpaceType
    background: str = "",
    learner_name: str = "",
    goal: str = "",
    domain_name: str = "",
    recommended_tools: list | None = None,
):  # -> SpaceProfile
    """Create a new SpaceProfile from domain defaults, persist it, and init Space Memory files."""
    from sarthak.spaces.domain_loader import get_domain
    from sarthak.spaces.models import LearnerProfile, SpaceProfile
    domain = get_domain(space_type)
    profile = SpaceProfile(
        space_type=space_type,
        domain=domain_name or domain["domain_name"],
        learner=LearnerProfile(name=learner_name, background=background, goal=goal),
        recommended_tools=recommended_tools if recommended_tools is not None else domain["tools"],
        workspace_dir=str(workspace_dir),
    )
    save_profile(workspace_dir, profile)
    # Init SOUL.md + scaffold MEMORY.md (idempotent — skips if already present)
    try:
        import asyncio
        from sarthak.spaces.memory import init_space_memory
        try:
            loop = asyncio.get_running_loop()
            task = loop.create_task(init_space_memory(workspace_dir, profile))
            task.add_done_callback(
                lambda t: log.warning("space_memory_init_failed", error=str(t.exception()))
                if not t.cancelled() and t.exception() else None
            )
        except RuntimeError:
            asyncio.run(init_space_memory(workspace_dir, profile))
    except Exception as _e:
        log.warning("space_memory_init_failed", error=str(_e))
    return profile
