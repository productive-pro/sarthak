from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from sarthak.web.routers.helpers import get_space_or_404

router = APIRouter()


@router.get("/api/agents")
async def list_agents_api() -> list[dict]:
    from sarthak.agents.store import list_agents

    return [s.model_dump() for s in list_agents()]


class AgentCreate(BaseModel):
    description: str
    directory: str = ""
    notify_telegram: bool = False


@router.post("/api/agents")
async def create_agent_api(body: AgentCreate) -> dict:
    from sarthak.agents.creator import create_agent_from_description

    space_dir = Path(body.directory).resolve() if body.directory else None
    spec = await create_agent_from_description(
        body.description,
        space_dir=space_dir,
        notify_telegram=body.notify_telegram or None,
    )
    return spec.model_dump()


@router.post("/api/agents/{agent_id}/run")
async def run_agent_api(agent_id: str) -> dict:
    from sarthak.agents.runner import run_agent
    from sarthak.agents.store import load_agent

    spec = load_agent(agent_id)
    if not spec:
        raise HTTPException(404, "Agent not found")
    run = await run_agent(spec)
    return {
        "success": run.success,
        "output": run.output,
        "error": run.error,
        "run_id": run.run_id,
    }


@router.get("/api/agents/{agent_id}/logs")
async def agent_logs_api(agent_id: str, limit: int = 5) -> list[dict]:
    from sarthak.agents.store import load_runs

    return [r.model_dump() for r in load_runs(agent_id, limit=limit)]


@router.delete("/api/agents/{agent_id}")
async def delete_agent_api(agent_id: str) -> dict:
    from sarthak.agents.store import delete_agent

    if not delete_agent(agent_id):
        raise HTTPException(404, "Agent not found")
    return {"ok": True}


@router.patch("/api/agents/{agent_id}")
async def patch_agent_api(agent_id: str, body: dict) -> dict:
    from sarthak.agents.store import update_agent

    spec = update_agent(agent_id, **body)
    if not spec:
        raise HTTPException(404, "Agent not found")
    return spec.model_dump()


# ── Space agents ─────────────────────────────────────────────────────────────


@router.get("/api/spaces/{space_id}/agents")
async def list_space_agents_api(space_id: str) -> list[dict]:
    from sarthak.agents.store import list_agents

    match = get_space_or_404(space_id)
    agents = list_agents(space_dir=Path(match["directory"]))
    return [s.model_dump() for s in agents]


class SpaceAgentCreate(BaseModel):
    description: str
    notify_telegram: bool = False


@router.post("/api/spaces/{space_id}/agents")
async def create_space_agent_api(space_id: str, body: SpaceAgentCreate) -> dict:
    from sarthak.agents.creator import create_agent_from_description

    match = get_space_or_404(space_id)
    space_dir = Path(match["directory"])
    spec = await create_agent_from_description(
        body.description,
        space_dir=space_dir,
        notify_telegram=body.notify_telegram or None,
    )
    return spec.model_dump()
