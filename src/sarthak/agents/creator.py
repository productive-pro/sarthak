"""
Sarthak Agent Engine — AI-powered agent creator.

create_agent_from_description(description, space_dir?, dry_run?) -> AgentSpec

The LLM picks name, schedule, tools, and prompt from natural language.
dry_run=True returns the spec without saving to disk.
"""
from __future__ import annotations

import re
import uuid
from pathlib import Path

import structlog

from sarthak.agents.models import AgentScope, AgentSpec, AgentTool, SandboxPolicy
from sarthak.agents.prompts.roadmap import CREATOR as _SYSTEM_PROMPT
from sarthak.agents.store import compute_next_run
from sarthak.features.ai.agents._base import run_llm, parse_json_response

log = structlog.get_logger(__name__)

# Schedules that suggest long-running patterns → raise wall_timeout
_LONG_RUNNING_PATTERNS = ("*/5", "*/10", "*/15", "0 * *", "* * *")


async def create_agent_from_description(
    description: str,
    space_dir: Path | None = None,
    notify_telegram: bool | None = None,
    dry_run: bool = False,
) -> AgentSpec:
    """
    Parse a natural-language description and return an AgentSpec.
    Saves to disk unless dry_run=True.
    """
    space_context = ""
    if space_dir:
        from sarthak.spaces.store import get_space_context
        space_context = get_space_context(space_dir) or ""

    user_msg = f"User request: {description}"
    if space_context:
        user_msg += f"\n\nSpace context:\n{space_context}"

    raw  = await run_llm(_SYSTEM_PROMPT, user_msg)
    data = parse_json_response(raw)

    tools: list[AgentTool] = []
    for t in data.get("tools", []):
        try:
            tools.append(AgentTool(t))
        except ValueError:
            pass

    scope     = AgentScope.SPACE if space_dir else AgentScope.GLOBAL
    space_str = str(space_dir) if space_dir else ""
    notify    = data.get("notify_telegram", False) if notify_telegram is None else notify_telegram
    name      = data.get("name", "Custom Agent")
    schedule  = data.get("schedule", "0 8 * * *")

    # Set wall_timeout hint for high-frequency / monitoring schedules
    sandbox_policy = SandboxPolicy()
    if any(schedule.startswith(p) for p in _LONG_RUNNING_PATTERNS):
        sandbox_policy = SandboxPolicy(wall_timeout=60)

    spec = AgentSpec(
        agent_id=_slugify(name),
        name=name,
        description=data.get("description", description[:120]),
        prompt=data.get("prompt", description),
        schedule=schedule,
        tools=tools,
        scope=scope,
        space_dir=space_str,
        notify_telegram=notify,
        next_run_at=_next_run(schedule),
        extra=data.get("extra", {}),
        sandbox=sandbox_policy,
    )

    if not dry_run:
        from sarthak.agents.store import save_agent
        save_agent(spec)
        log.info("agent_created", agent_id=spec.agent_id, schedule=schedule)

    return spec


def _slugify(name: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")
    return slug or f"agent-{uuid.uuid4().hex[:6]}"


# compute_next_run imported from sarthak.agents.store — single canonical implementation
_next_run = compute_next_run
