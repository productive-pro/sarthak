"""
Orchestrator agent — primary user-facing agent for all channels (TUI, Telegram, web).

Uses pydantic-ai Agent Delegation pattern:
  - Delegates to specialist sub-agents (vision, summary) via tool calls
  - Passes ctx.usage to sub-agent runs so total usage is tracked correctly
  - duckduckgo_search_tool() registered as a built-in tool (no manual web tool needed)

AGENT DATA RULE:
  - Activity queries: stats only (no raw rows).
"""
from __future__ import annotations

from pydantic_ai import Agent, RunContext
from pydantic_ai.common_tools.duckduckgo import duckduckgo_search_tool

from sarthak.core.constants import AGENT_RETRIES, AGENT_OUTPUT_RETRIES
from sarthak.features.ai.deps import OrchestratorDeps, OrchestratorResult
from sarthak.features.ai.agents._base import build_pydantic_model
from sarthak.core.ai_utils.prompts import get_prompt
from sarthak.features.ai.skills import list_skills, build_context_block
from sarthak.features.ai.tools import (
    tool_query_activity, tool_get_summary, tool_get_tips, tool_save_tip,
    tool_run_shell,
    tool_service_status, tool_restart_service, tool_send_notification,
    tool_list_skills, tool_read_skill, tool_save_skill, tool_delete_skill,
    tool_spaces_session, tool_spaces_status, tool_spaces_setup,
    tool_spaces_evaluate, tool_spaces_init, tool_spaces_context,
    tool_spaces_quick, tool_spaces_list,
    tool_spaces_rag_index, tool_spaces_rag_search,
)


def build(provider: str, model_name: str) -> Agent[OrchestratorDeps, OrchestratorResult]:
    skills = list_skills()
    base_prompt = get_prompt("orchestrator_agent").format(
        skills_context=build_context_block(skills) if skills else ""
    )
    system = base_prompt

    agent: Agent[OrchestratorDeps, OrchestratorResult] = Agent(
        build_pydantic_model(provider, model_name),
        output_type=OrchestratorResult,
        deps_type=OrchestratorDeps,
        system_prompt=system,
        retries=AGENT_RETRIES,
        output_retries=AGENT_OUTPUT_RETRIES,
        tools=[duckduckgo_search_tool()],
    )

    # ── Agent Delegation ──────────────────────────────────────────────────────

    @agent.tool
    async def run_snapshot_analysis(ctx: RunContext[OrchestratorDeps], user_request: str) -> str:
        """Delegate a vision/snapshot analysis task to the specialist vision agent."""
        from sarthak.features.ai.agents import get_agent
        from sarthak.features.ai.deps import AgentDeps
        sub  = get_agent("vision")
        deps = AgentDeps(
            pool=ctx.deps.pool, cwd=ctx.deps.cwd,
            allow_web=ctx.deps.allow_web, allow_shell=ctx.deps.allow_shell,
        )
        result = await sub.run(user_request, deps=deps, usage=ctx.usage)
        return result.output.summary

    @agent.tool
    async def run_daily_summary(ctx: RunContext[OrchestratorDeps], date_str: str = "") -> str:
        """Delegate daily digest generation to the summary specialist agent."""
        from sarthak.features.ai.agents import get_agent
        from sarthak.features.ai.deps import AgentDeps
        sub    = get_agent("summary")
        deps   = AgentDeps(pool=ctx.deps.pool, cwd=ctx.deps.cwd)
        prompt = f"Generate the daily summary for {date_str or 'today'}."
        result = await sub.run(prompt, deps=deps, usage=ctx.usage)
        return result.output.summary

    # ── Activity ──────────────────────────────────────────────────────────────

    @agent.tool
    async def query_activity(ctx: RunContext[OrchestratorDeps], days: int = 1, limit: int = 30) -> str:
        """Fetch activity digest: stats + head/tail only (no raw rows)."""
        return await tool_query_activity(ctx.deps.pool, days=days, limit=limit)

    @agent.tool
    async def get_summary(ctx: RunContext[OrchestratorDeps], date_str: str = "") -> str:
        """Get the AI-generated daily summary. date_str = 'YYYY-MM-DD' or empty for today."""
        return await tool_get_summary(ctx.deps.pool, date_str or None)

    @agent.tool
    async def get_tips(ctx: RunContext[OrchestratorDeps], limit: int = 3) -> str:
        """Fetch the latest saved tips."""
        return await tool_get_tips(ctx.deps.pool, limit=limit)

    @agent.tool
    async def save_tip(ctx: RunContext[OrchestratorDeps], tip: str) -> str:
        """Persist a new tip to the database."""
        return await tool_save_tip(ctx.deps.pool, tip)

    # ── Shell ─────────────────────────────────────────────────────────────────

    @agent.tool
    async def run_shell(ctx: RunContext[OrchestratorDeps], command: str) -> str:
        """Run a safe read-only shell command."""
        if not ctx.deps.allow_shell:
            return "Shell access disabled."
        return await tool_run_shell(command, cwd=ctx.deps.cwd)

    # ── Skills ────────────────────────────────────────────────────────────────

    @agent.tool_plain
    def list_skills_tool() -> str:
        return tool_list_skills()

    @agent.tool_plain
    def read_skill_tool(name: str) -> str:
        return tool_read_skill(name)

    @agent.tool_plain
    def save_skill_tool(name: str, description: str, content: str, tags: str = "") -> str:
        return tool_save_skill(name, description, content, tags)

    @agent.tool_plain
    def delete_skill_tool(name: str) -> str:
        return tool_delete_skill(name)

    # ── System ────────────────────────────────────────────────────────────────

    @agent.tool_plain
    async def service_status() -> str:
        return await tool_service_status()

    @agent.tool_plain
    async def restart_service(service: str) -> str:
        return await tool_restart_service(service)

    @agent.tool_plain
    async def send_notification(title: str, body: str) -> str:
        return await tool_send_notification(title, body)

    # ── Spaces ────────────────────────────────────────────────────────────────

    @agent.tool_plain
    def spaces_context(space_dir: str = "") -> str:
        """Get active space context (goal, tools, recent sessions). Call first for any learning request."""
        return tool_spaces_context(space_dir)

    @agent.tool_plain
    def spaces_init(space_dir: str, space_type: str = "data_science",
                    background: str = "", learner_name: str = "") -> str:
        """Initialize a new Sarthak Space in a directory."""
        return tool_spaces_init(space_dir, space_type, background, learner_name)

    @agent.tool_plain
    def spaces_session(space_dir: str = "", space_type: str = "data_science") -> str:
        """Run a learning session. Use when user says 'teach me', 'next lesson', 'what should I learn'."""
        return tool_spaces_session(space_dir, space_type)

    @agent.tool_plain
    def spaces_status(space_dir: str = "") -> str:
        """Show learner's mastery progress for a Sarthak Space."""
        return tool_spaces_status(space_dir)

    @agent.tool_plain
    def spaces_setup(space_dir: str = "") -> str:
        """Set up expert environment for a space (scan tools, reshape workspace)."""
        return tool_spaces_setup(space_dir)

    @agent.tool_plain
    def spaces_evaluate(concept: str, submission: str, space_dir: str = "") -> str:
        """Evaluate learner's code/answer and update their mastery level."""
        return tool_spaces_evaluate(concept, submission, space_dir)

    @agent.tool_plain
    def spaces_quick(space_dir: str = "") -> str:
        """Run a 5-minute micro-learning task. Good for busy days."""
        return tool_spaces_quick(space_dir)

    @agent.tool_plain
    def spaces_list() -> str:
        """List all known Sarthak spaces in the registry."""
        return tool_spaces_list()

    # ── RAG ───────────────────────────────────────────────────────────────────

    @agent.tool_plain
    def spaces_rag_index(space_dir: str = "", full: bool = False) -> str:
        """Index or re-index workspace files for RAG semantic search. full=True forces full re-embed."""
        return tool_spaces_rag_index(space_dir, full)

    @agent.tool_plain
    def spaces_rag_search(query: str, space_dir: str = "", top_k: int = 5) -> str:
        """Search indexed workspace files for content relevant to query. Returns file:line references."""
        return tool_spaces_rag_search(query, space_dir, top_k)

    return agent
