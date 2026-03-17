"""
Sarthak Agent Engine — persistence layer.

Storage layout:
  Global agents:  ~/.sarthak_ai/agents/<agent_id>/spec.json
  Space agents:   <space_dir>/.spaces/agents/<agent_id>/spec.json
  Run history:    <agent_dir>/runs/<run_id>.json  (max 50 per agent)
  Registry:       ~/.sarthak_ai/agents/registry.json
"""
from __future__ import annotations

import json
import threading
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import structlog

from sarthak.agents.models import AgentPatch, AgentRun, AgentScope, AgentSpec

log = structlog.get_logger(__name__)

_GLOBAL_DIR    = Path.home() / ".sarthak_ai" / "agents"
_REGISTRY      = _GLOBAL_DIR / "registry.json"
_MAX_RUNS      = 50
_LIST_CACHE_TTL = 10.0  # seconds

_registry_lock  = threading.Lock()
_list_cache_lock = threading.Lock()
_list_cache: list[AgentSpec] = []
_list_cache_at: float = 0.0
_list_cache_reg_mtime: float = 0.0


# ── Directories ───────────────────────────────────────────────────────────────

def _agent_dir(spec: AgentSpec) -> Path:
    if spec.scope == AgentScope.SPACE and spec.space_dir:
        return Path(spec.space_dir) / ".spaces" / "agents" / spec.agent_id
    return _GLOBAL_DIR / spec.agent_id


def _runs_dir(spec: AgentSpec) -> Path:
    return _agent_dir(spec) / "runs"


# ── CRUD ──────────────────────────────────────────────────────────────────────

def _validate_spec(spec: AgentSpec) -> None:
    if not spec.prompt.strip():
        raise ValueError(f"Agent '{spec.agent_id}' has an empty prompt.")
    if spec.scope == AgentScope.SPACE and not spec.space_dir:
        raise ValueError(f"Agent '{spec.agent_id}' has scope=SPACE but no space_dir.")
    try:
        from croniter import croniter
        if not croniter.is_valid(spec.schedule):
            raise ValueError(f"Agent '{spec.agent_id}' has invalid cron: '{spec.schedule}'.")
    except ImportError:
        pass


def save_agent(spec: AgentSpec) -> Path:
    _validate_spec(spec)
    d = _agent_dir(spec)
    d.mkdir(parents=True, exist_ok=True)
    path = d / "spec.json"
    from sarthak.core.utils import write_atomic
    write_atomic(path, spec.model_dump_json(indent=2))
    _register(spec)  # also invalidates list cache
    log.info("agent_saved", agent_id=spec.agent_id, scope=spec.scope)
    return path


def load_agent(agent_id: str) -> AgentSpec | None:
    entry = _registry_by_id().get(agent_id)
    if not entry:
        return None
    path = Path(entry["spec_path"])
    if not path.exists():
        return None
    try:
        return AgentSpec.model_validate_json(path.read_text(encoding="utf-8"))
    except Exception as exc:
        log.warning("agent_load_failed", agent_id=agent_id, error=str(exc))
        return None


def delete_agent(agent_id: str) -> bool:
    spec = load_agent(agent_id)
    if not spec:
        return False
    spec_path = _agent_dir(spec) / "spec.json"
    if spec_path.exists():
        spec_path.unlink()
    _deregister(agent_id)  # also invalidates list cache
    log.info("agent_deleted", agent_id=agent_id)
    return True


def list_agents(
    space_dir: Path | None = None,
    scope: "AgentScope | None" = None,
) -> list[AgentSpec]:
    """List agents with optional space_dir or scope filter.

    Only the unfiltered (space_dir=None, scope=None) result is cached —
    filtered queries always read fresh from the cached raw list.
    """
    global _list_cache, _list_cache_at, _list_cache_reg_mtime

    now = time.monotonic()
    reg_mtime = _REGISTRY.stat().st_mtime if _REGISTRY.exists() else 0.0

    # Refresh raw list if stale
    with _list_cache_lock:
        cache_fresh = (
            bool(_list_cache)
            and (now - _list_cache_at) < _LIST_CACHE_TTL
            and reg_mtime == _list_cache_reg_mtime
        )
        if not cache_fresh:
            _list_cache = _load_all_specs()
            _list_cache_at = now
            _list_cache_reg_mtime = reg_mtime
        raw = list(_list_cache)

    # Apply filters on the in-memory list (no extra I/O)
    if space_dir is not None:
        target = Path(space_dir).resolve()
        return [
            s for s in raw
            if s.scope == AgentScope.SPACE and _same_dir(s.space_dir, target)
        ]
    if scope is not None:
        return [s for s in raw if s.scope == scope]
    return raw


def _same_dir(path_str: str, target: Path) -> bool:
    try:
        return Path(path_str).resolve() == target
    except Exception:
        return False


def _load_all_specs() -> list[AgentSpec]:
    specs: list[AgentSpec] = []
    for entry in _load_registry():
        path = Path(entry.get("spec_path", ""))
        if not path.exists():
            continue
        try:
            specs.append(AgentSpec.model_validate_json(path.read_text(encoding="utf-8")))
        except Exception:
            pass
    return specs


def _invalidate_list_cache() -> None:
    global _list_cache, _list_cache_at, _list_cache_reg_mtime
    with _list_cache_lock:
        _list_cache = []
        _list_cache_at = 0.0
        _list_cache_reg_mtime = 0.0


def update_agent(agent_id: str, **updates: Any) -> AgentSpec | None:
    spec = load_agent(agent_id)
    if not spec:
        return None
    current = spec.model_dump()
    current.update({k: v for k, v in updates.items() if k in current})
    current["updated_at"] = datetime.now(timezone.utc).isoformat()
    validated = AgentSpec.model_validate(current)
    save_agent(validated)
    return validated


def patch_agent(agent_id: str, patch: AgentPatch) -> AgentSpec | None:
    updates = patch.model_dump(exclude_none=True)
    return update_agent(agent_id, **updates) if updates else load_agent(agent_id)


# ── Run history ───────────────────────────────────────────────────────────────

def save_run(spec: AgentSpec, run: AgentRun) -> Path:
    rd = _runs_dir(spec)
    rd.mkdir(parents=True, exist_ok=True)
    path = rd / f"{run.run_id}.json"
    from sarthak.core.utils import write_atomic
    write_atomic(path, run.model_dump_json(indent=2))
    _trim_runs(rd)
    return path


def load_runs(agent_id: str, limit: int = 10) -> list[AgentRun]:
    spec = load_agent(agent_id)
    if not spec:
        return []
    rd = _runs_dir(spec)
    if not rd.exists():
        return []
    files = sorted(rd.glob("*.json"), key=lambda p: p.stat().st_mtime, reverse=True)
    return [AgentRun.model_validate_json(f.read_text(encoding="utf-8")) for f in files[:limit]]


def _trim_runs(runs_dir: Path) -> None:
    for old in sorted(runs_dir.glob("*.json"), key=lambda p: p.stat().st_mtime, reverse=True)[_MAX_RUNS:]:
        old.unlink(missing_ok=True)


# ── Registry ──────────────────────────────────────────────────────────────────

def _load_registry_locked() -> list[dict]:
    _REGISTRY.parent.mkdir(parents=True, exist_ok=True)
    if not _REGISTRY.exists():
        return []
    return json.loads(_REGISTRY.read_text(encoding="utf-8"))


def _save_registry_locked(entries: list[dict]) -> None:
    _REGISTRY.parent.mkdir(parents=True, exist_ok=True)
    from sarthak.core.utils import write_atomic
    write_atomic(_REGISTRY, json.dumps(entries, indent=2))


def _load_registry() -> list[dict]:
    with _registry_lock:
        return _load_registry_locked()


def _registry_by_id() -> dict[str, dict]:
    return {e["agent_id"]: e for e in _load_registry() if "agent_id" in e}


def _register(spec: AgentSpec) -> None:
    spec_path = str(_agent_dir(spec) / "spec.json")
    with _registry_lock:
        entries = _load_registry_locked()
        for e in entries:
            if e.get("agent_id") == spec.agent_id:
                e.update({"spec_path": spec_path, "name": spec.name, "scope": spec.scope})
                _save_registry_locked(entries)
                _invalidate_list_cache()
                return
        entries.append({"agent_id": spec.agent_id, "name": spec.name,
                        "scope": spec.scope, "spec_path": spec_path})
        _save_registry_locked(entries)
        _invalidate_list_cache()


def _deregister(agent_id: str) -> None:
    with _registry_lock:
        entries = _load_registry_locked()
        _save_registry_locked([e for e in entries if e.get("agent_id") != agent_id])
        _invalidate_list_cache()


# ── Helpers ───────────────────────────────────────────────────────────────────

def new_run_id() -> str:
    return str(uuid.uuid4())[:8]


def compute_next_run(schedule: str) -> str:
    """Compute next cron fire time as ISO-8601. Returns '' on error."""
    try:
        from croniter import croniter
        return croniter(schedule, datetime.now(timezone.utc)).get_next(datetime).isoformat()
    except Exception:
        return ""
