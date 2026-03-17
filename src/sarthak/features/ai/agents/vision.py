"""
Vision agent — snapshot analysis with optional web search and shell context.

Specialist sub-agent called via delegation from the orchestrator.
Uses duckduckgo_search_tool() as a built-in rather than manual httpx.

AGENT DATA RULE:
  - Only receives statistical activity digest (stats + head/tail).
  - Screenshot bytes via BinaryContent (vision).
  - No raw table rows ever enter the prompt.
"""
from __future__ import annotations

from pydantic_ai import Agent, BinaryContent, RunContext
from pydantic_ai.common_tools.duckduckgo import duckduckgo_search_tool

from sarthak.features.ai.deps import AgentDeps, SarthakResult
from sarthak.features.ai.agents._base import build_pydantic_model, shared_run_shell
from sarthak.core.ai_utils.prompts import get_prompt


def build(provider: str, model_name: str) -> Agent[AgentDeps, SarthakResult]:
    agent: Agent[AgentDeps, SarthakResult] = Agent(
        build_pydantic_model(provider, model_name),
        output_type=SarthakResult,
        deps_type=AgentDeps,
        system_prompt=get_prompt("sarthak_agent"),
        tools=[duckduckgo_search_tool()],  # built-in web search
    )

    @agent.tool
    async def run_shell(ctx: RunContext[AgentDeps], command: str) -> str:
        """Run a safe read-only shell command."""
        if not ctx.deps.allow_shell:
            return "Shell access disabled by policy."
        return await shared_run_shell(command, ctx.deps.cwd, "vision")

    @agent.tool
    async def query_recent_events(ctx: RunContext[AgentDeps], days: int = 1) -> str:
        """Query recent activity digest (stats + head/tail only — no raw rows)."""
        from sarthak.features.ai.tools.activity import tool_query_activity
        return await tool_query_activity(ctx.deps.pool, days=days)

    return agent
