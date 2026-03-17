"""
Sarthak AI — Agents API router.

Two agent types exposed cleanly:

  System agents  (AgentScope.GLOBAL):
    GET  /api/agents                  — list all system agents
    POST /api/agents/system           — create a system agent
    GET  /api/agents/space            — list all space agents (across all spaces)

  Space agents  (AgentScope.SPACE):
    GET  /api/spaces/{space_id}/agents        — list agents for one space
    POST /api/spaces/{space_id}/agents        — create a space agent

  Shared operations (work on any agent by ID):
    POST   /api/agents/{agent_id}/run
    GET    /api/agents/{agent_id}/logs
    PATCH  /api/agents/{agent_id}
    DELETE /api/agents/{agent_id}
"""
from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from sarthak.agents.models import AgentPatch, AgentScope
from sarthak.web.routers.helpers import get_space_or_404

router = APIRouter()


# ── System agents ─────────────────────────────────────────────────────────────

@router.get("/api/agents")
async def list_system_agents_api() -> list[dict]:
    """List all system (global) agents."""
    from sarthak.agents.store import list_agents
    return [s.model_dump() for s in list_agents(scope=AgentScope.GLOBAL)]


@router.get("/api/agents/space")
async def list_all_space_agents_api() -> list[dict]:
    """List all space agents across every registered space."""
    from sarthak.agents.store import list_agents
    return [s.model_dump() for s in list_agents(scope=AgentScope.SPACE)]


class SystemAgentCreate(BaseModel):
    description: str = Field(min_length=1, max_length=8000)
    notify_telegram: bool = False


@router.post("/api/agents/system")
async def create_system_agent_api(body: SystemAgentCreate) -> dict:
    """Create a system-level (global) agent from a natural-language description."""
    from sarthak.agents.creator import create_agent_from_description
    spec = await create_agent_from_description(
        body.description,
        scope=AgentScope.GLOBAL,
        notify_telegram=body.notify_telegram or None,
    )
    return spec.model_dump()


# ── Space agents ──────────────────────────────────────────────────────────────

@router.get("/api/spaces/{space_id}/agents")
async def list_space_agents_api(space_id: str) -> list[dict]:
    """List all agents scoped to a specific space."""
    from sarthak.agents.store import list_agents
    match = get_space_or_404(space_id)
    return [s.model_dump() for s in list_agents(space_dir=Path(match["directory"]))]


class SpaceAgentCreate(BaseModel):
    description: str = Field(min_length=1, max_length=8000)
    notify_telegram: bool = False


@router.post("/api/spaces/{space_id}/agents")
async def create_space_agent_api(space_id: str, body: SpaceAgentCreate) -> dict:
    """Create a space-scoped agent from a natural-language description."""
    from sarthak.agents.creator import create_agent_from_description
    match = get_space_or_404(space_id)
    spec = await create_agent_from_description(
        body.description,
        scope=AgentScope.SPACE,
        space_dir=Path(match["directory"]),
        notify_telegram=body.notify_telegram or None,
    )
    return spec.model_dump()


# ── Shared operations (any agent by ID) ───────────────────────────────────────

@router.post("/api/agents/{agent_id}/run")
async def run_agent_api(agent_id: str) -> dict:
    """Run an agent immediately, ignoring its schedule."""
    from sarthak.agents.runner import run_agent
    from sarthak.agents.store import load_agent
    spec = load_agent(agent_id)
    if not spec:
        raise HTTPException(404, "Agent not found")
    run = await run_agent(spec)
    return {
        "success": run.success,
        "output":  run.output,
        "error":   run.error,
        "run_id":  run.run_id,
    }


@router.get("/api/agents/{agent_id}/logs")
async def agent_logs_api(agent_id: str, limit: int = 5) -> list[dict]:
    """Return recent run history for any agent."""
    from sarthak.agents.store import load_runs
    return [r.model_dump() for r in load_runs(agent_id, limit=limit)]


@router.patch("/api/agents/{agent_id}")
async def patch_agent_api(agent_id: str, body: AgentPatch) -> dict:
    """Patch mutable fields on any agent (name, schedule, enabled, etc.)."""
    from sarthak.agents.store import patch_agent
    spec = patch_agent(agent_id, body)
    if not spec:
        raise HTTPException(404, "Agent not found")
    return spec.model_dump()


@router.delete("/api/agents/{agent_id}")
async def delete_agent_api(agent_id: str) -> dict:
    """Delete any agent by ID."""
    from sarthak.agents.store import delete_agent
    if not delete_agent(agent_id):
        raise HTTPException(404, "Agent not found")
    return {"ok": True}
