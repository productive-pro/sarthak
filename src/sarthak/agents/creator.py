"""
Sarthak Agent Engine — AI-powered agent creator.

Two agent types:
  - SYSTEM agents (AgentScope.GLOBAL): run globally, no space context.
    Live at ~/.sarthak_ai/agents/<id>/spec.json
    Used for: cross-space digests, system monitoring, global automation.

  - SPACE agents (AgentScope.SPACE): scoped to one space directory.
    Live at <space_dir>/.spaces/agents/<id>/spec.json
    Used for: space-specific tasks, file analysis, concept tracking.

Public API:
  create_agent_from_description(description, scope, space_dir?, dry_run?) -> AgentSpec
"""
from __future__ import annotations

import re
import uuid
from pathlib import Path

import structlog

from sarthak.agents.models import AgentScope, AgentSpec, AgentTool, SandboxPolicy
from sarthak.agents.store import compute_next_run, save_agent
from sarthak.features.ai.agents._base import parse_json_response, run_llm

log = structlog.get_logger(__name__)

# Schedules that suggest high-frequency patterns → lower wall_timeout
_LONG_RUNNING_PATTERNS = ("*/5", "*/10", "*/15", "0 * *", "* * *")

# ── Scope-specific system prompts loaded from .md files ──────────────────────
# data/agents/roadmap/agent-creator-system.md  (GLOBAL scope)
# data/agents/roadmap/agent-creator-space.md   (SPACE scope)

def _creator_prompt(scope: AgentScope) -> str:
    """Load the creator system prompt for the given scope from its .md file."""
    from sarthak.data.loader import load_agent
    agent_id = "agent-creator-space" if scope == AgentScope.SPACE else "agent-creator-system"
    return load_agent(agent_id).system_prompt


async def create_agent_from_description(
    description: str,
    scope: AgentScope = AgentScope.GLOBAL,
    space_dir: Path | None = None,
    notify_telegram: bool | None = None,
    dry_run: bool = False,
) -> AgentSpec:
    """
    Parse a natural-language description and return an AgentSpec.

    Parameters
    ----------
    description:      Natural-language task description.
    scope:            AgentScope.GLOBAL (system) or AgentScope.SPACE.
                      When AgentScope.SPACE, space_dir must be provided.
    space_dir:        Required when scope == SPACE. Agent is stored in
                      <space_dir>/.spaces/agents/.
    notify_telegram:  Override LLM's telegram decision (None = let LLM decide).
    dry_run:          Return spec without saving to disk.
    """
    if scope == AgentScope.SPACE and not space_dir:
        raise ValueError("space_dir is required when scope is AgentScope.SPACE")

    # Load scope-appropriate system prompt from .md file
    system_prompt = _creator_prompt(scope)

    # Build user message — inject space context for space agents
    user_msg = f"User request: {description}"
    if scope == AgentScope.SPACE and space_dir:
        from sarthak.spaces.store import get_space_context
        space_context = get_space_context(space_dir) or ""
        if space_context:
            user_msg += f"\n\nSpace context:\n{space_context}"

    raw  = await run_llm(system_prompt, user_msg)
    data = parse_json_response(raw)

    # Parse tools
    tools: list[AgentTool] = []
    for t in data.get("tools", []):
        try:
            tools.append(AgentTool(t))
        except ValueError:
            pass

    notify  = data.get("notify_telegram", False) if notify_telegram is None else notify_telegram
    name    = data.get("name", "Custom Agent")
    schedule = data.get("schedule", "0 8 * * *")

    # Raise wall_timeout for high-frequency schedules
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
        space_dir=str(space_dir) if space_dir else "",
        notify_telegram=notify,
        next_run_at=compute_next_run(schedule),
        extra=data.get("extra", {}),
        sandbox=sandbox_policy,
    )

    if not dry_run:
        save_agent(spec)
        log.info(
            "agent_created",
            agent_id=spec.agent_id,
            scope=scope.value,
            schedule=schedule,
            space=str(space_dir) if space_dir else "global",
        )

    return spec


def _slugify(name: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")
    return slug or f"agent-{uuid.uuid4().hex[:6]}"
