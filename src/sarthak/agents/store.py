"""
Sarthak Agent Engine — persistence layer.

Storage layout:
  Global agents:  ~/.sarthak_ai/agents/<agent_id>/spec.json
  Space agents:   <space_dir>/.spaces/agents/<agent_id>/spec.json
  Run history:    <agent_dir>/runs/<run_id>.json   (max 50 per agent)
  Registry:       ~/.sarthak_ai/agents/registry.json  (all known agent IDs + paths)
"""
from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import structlog

from sarthak.agents.models import AgentRun, AgentScope, AgentSpec

log = structlog.get_logger(__name__)

_GLOBAL_DIR = Path.home() / ".sarthak_ai" / "agents"
_REGISTRY   = _GLOBAL_DIR / "registry.json"
_MAX_RUNS   = 50


# ── Directories ───────────────────────────────────────────────────────────────

def _agent_dir(spec: AgentSpec) -> Path:
    """Return the directory that holds spec.json for an agent."""
    if spec.scope == AgentScope.SPACE and spec.space_dir:
        base = Path(spec.space_dir) / ".spaces" / "agents"
    else:
        base = _GLOBAL_DIR
    return base / spec.agent_id


def _runs_dir(spec: AgentSpec) -> Path:
    return _agent_dir(spec) / "runs"


# ── CRUD ──────────────────────────────────────────────────────────────────────

def _validate_spec(spec: AgentSpec) -> None:
    """Raise ValueError for invalid specs before persisting."""
    if not spec.prompt.strip():
        raise ValueError(f"Agent '{spec.agent_id}' has an empty prompt.")
    if spec.scope.value == "space" and not spec.space_dir:
        raise ValueError(f"Agent '{spec.agent_id}' has scope=SPACE but no space_dir.")
    try:
        from croniter import croniter
        if not croniter.is_valid(spec.schedule):
            raise ValueError(f"Agent '{spec.agent_id}' has invalid cron schedule: '{spec.schedule}'.")
    except ImportError:
        pass


def save_agent(spec: AgentSpec) -> Path:
    """Validate and persist agent spec. Creates directories as needed."""
    _validate_spec(spec)
    d = _agent_dir(spec)
    d.mkdir(parents=True, exist_ok=True)
    path = d / "spec.json"
    path.write_text(spec.model_dump_json(indent=2), encoding="utf-8")
    _register(spec)
    log.info("agent_saved", agent_id=spec.agent_id, scope=spec.scope)
    return path


def load_agent(agent_id: str) -> AgentSpec | None:
    """Load agent by ID using the registry index."""
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
    """Remove agent spec and deregister. Keeps run history."""
    spec = load_agent(agent_id)
    if not spec:
        return False
    spec_path = _agent_dir(spec) / "spec.json"
    if spec_path.exists():
        spec_path.unlink()
    _deregister(agent_id)
    log.info("agent_deleted", agent_id=agent_id)
    return True


def list_agents(space_dir: Path | None = None) -> list[AgentSpec]:
    """List all agents. Filter by space_dir if given."""
    agents: list[AgentSpec] = []
    for entry in _load_registry():
        path = Path(entry.get("spec_path", ""))
        if not path.exists():
            continue
        spec = AgentSpec.model_validate_json(path.read_text(encoding="utf-8"))
        if space_dir is not None:
            # Show ONLY agents belonging to this space
            if spec.scope != AgentScope.SPACE:
                continue
            try:
                if Path(spec.space_dir).resolve() != Path(space_dir).resolve():
                    continue
            except Exception:
                continue
        agents.append(spec)
    return agents


def update_agent(agent_id: str, **updates: Any) -> AgentSpec | None:
    """Patch fields on an agent and save."""
    spec = load_agent(agent_id)
    if not spec:
        return None
    for key, val in updates.items():
        setattr(spec, key, val)
    spec.updated_at = datetime.now(timezone.utc).isoformat()
    save_agent(spec)
    return spec


# ── Run history ───────────────────────────────────────────────────────────────

def save_run(spec: AgentSpec, run: AgentRun) -> Path:
    """Persist a run record. Trims to MAX_RUNS."""
    rd = _runs_dir(spec)
    rd.mkdir(parents=True, exist_ok=True)
    path = rd / f"{run.run_id}.json"
    path.write_text(run.model_dump_json(indent=2), encoding="utf-8")
    _trim_runs(rd)
    return path


def load_runs(agent_id: str, limit: int = 10) -> list[AgentRun]:
    """Return most recent runs for an agent."""
    spec = load_agent(agent_id)
    if not spec:
        return []
    rd = _runs_dir(spec)
    if not rd.exists():
        return []
    run_files = sorted(rd.glob("*.json"), key=lambda p: p.stat().st_mtime, reverse=True)
    runs: list[AgentRun] = []
    for f in run_files[:limit]:
        runs.append(AgentRun.model_validate_json(f.read_text(encoding="utf-8")))
    return runs


def _trim_runs(runs_dir: Path) -> None:
    """Keep only the _MAX_RUNS most recent run files."""
    files = sorted(runs_dir.glob("*.json"), key=lambda p: p.stat().st_mtime, reverse=True)
    for old in files[_MAX_RUNS:]:
        old.unlink(missing_ok=True)


# ── Registry ──────────────────────────────────────────────────────────────────

def _load_registry() -> list[dict]:
    _REGISTRY.parent.mkdir(parents=True, exist_ok=True)
    if not _REGISTRY.exists():
        return []
    return json.loads(_REGISTRY.read_text(encoding="utf-8"))


def _save_registry(entries: list[dict]) -> None:
    _REGISTRY.parent.mkdir(parents=True, exist_ok=True)
    _REGISTRY.write_text(json.dumps(entries, indent=2), encoding="utf-8")


def _registry_by_id() -> dict[str, dict]:
    """Return registry keyed by agent_id for O(1) lookup."""
    return {e["agent_id"]: e for e in _load_registry() if "agent_id" in e}


def _register(spec: AgentSpec) -> None:
    entries = _load_registry()
    spec_path = str(_agent_dir(spec) / "spec.json")
    for e in entries:
        if e.get("agent_id") == spec.agent_id:
            e.update({"spec_path": spec_path, "name": spec.name, "scope": spec.scope})
            _save_registry(entries)
            return
    entries.append({"agent_id": spec.agent_id, "name": spec.name,
                    "scope": spec.scope, "spec_path": spec_path})
    _save_registry(entries)


def _deregister(agent_id: str) -> None:
    _save_registry([e for e in _load_registry() if e.get("agent_id") != agent_id])


def new_run_id() -> str:
    """Generate a unique run ID."""
    return str(uuid.uuid4())[:8]
