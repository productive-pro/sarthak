"""
Orchestrator agent — primary user-facing agent for all channels (TUI, Telegram, web).

Strategy 1 — Lazy Tool Loading:
  build() accepts tool_groups. Only the requested groups are registered, so the
  LLM only sees tool schemas it actually needs. Cuts system-prompt tokens 30-50%
  on focused queries. The intent pre-classifier in agent.py picks groups before
  build() is called.

  Groups:
    "activity"   → query_activity, get_summary, get_tips, save_tip
    "shell"      → run_shell
    "skills"     → list/read/save/delete skill tools
    "system"     → service_status, restart_service
    "spaces"     → spaces_context/init/session/status/setup/evaluate/quick/list
    "rag"        → spaces_rag_index, spaces_rag_search
    "workspace"  → workspace_qa, workspace_analyse
    "delegation" → run_snapshot_analysis, run_daily_summary (sub-agent calls)
    "web"        → duckduckgo_search_tool
  ALL_GROUPS = all groups (default)

Strategy 3 — Subagent Context Isolation:
  spaces_session runs the full learning session in an isolated sub-agent context
  and returns only a compact summary string — the session transcript never
  pollutes the orchestrator's context window.

Hierarchical Context (your design):
  tool_spaces_context defaults to SOUL+MEMORY only (fast, low-token).
  It only loads HEARTBEAT when the user's question is about SRS/streak/cards.
  This is the "read main first, dig into branches only if needed" pattern.
"""
from __future__ import annotations

from pydantic_ai import Agent, RunContext
from pydantic_ai.common_tools.duckduckgo import duckduckgo_search_tool

from sarthak.core.constants import AGENT_RETRIES, AGENT_OUTPUT_RETRIES
from sarthak.features.ai.deps import OrchestratorDeps, OrchestratorResult
from sarthak.features.ai.agents._base import build_pydantic_model
from sarthak.features.ai.skills import list_skills, build_context_block
from sarthak.data.loader import load_agent, build_prompt

ALL_GROUPS: frozenset[str] = frozenset({
    "activity", "shell", "skills", "system",
    "spaces", "rag", "workspace", "delegation", "web",
})


def build(
    provider: str,
    model_name: str,
    tool_groups: frozenset[str] | set[str] | None = None,
) -> "Agent[OrchestratorDeps, OrchestratorResult]":
    """
    Build the orchestrator, registering only the tool groups requested.
    tool_groups=None → ALL_GROUPS (full capability, backward-compatible).
    """
    groups = ALL_GROUPS if tool_groups is None else frozenset(tool_groups)

    meta   = load_agent("orchestrator")
    skills = list_skills()
    prompt = build_prompt(meta, build_context_block(skills) if skills else "").format(
        skills_context=build_context_block(skills) if skills else ""
    )
    base_tools = [duckduckgo_search_tool()] if "web" in groups else []

    agent: Agent[OrchestratorDeps, OrchestratorResult] = Agent(
        build_pydantic_model(provider, model_name),
        output_type=OrchestratorResult,
        deps_type=OrchestratorDeps,
        system_prompt=prompt,
        retries=AGENT_RETRIES,
        output_retries=AGENT_OUTPUT_RETRIES,
        tools=base_tools,
    )
    _register_tools(agent, groups)
    return agent


# ── Tool registration by group ────────────────────────────────────────────────

def _register_tools(
    agent: "Agent[OrchestratorDeps, OrchestratorResult]",
    groups: frozenset[str],
) -> None:
    """Register tool handlers onto agent based on active groups."""

    # ── Delegation ────────────────────────────────────────────────────────────
    if "delegation" in groups:

        @agent.tool
        async def run_snapshot_analysis(ctx: RunContext[OrchestratorDeps], user_request: str) -> str:
            """Delegate a vision/snapshot analysis task to the specialist vision agent.
            Token usage flows back to the parent run via ctx.usage (shared budget)."""
            from sarthak.features.ai.agents import get_agent
            from sarthak.features.ai.deps import AgentDeps
            sub  = get_agent("vision")
            deps = AgentDeps(pool=ctx.deps.pool, cwd=ctx.deps.cwd,
                             allow_web=ctx.deps.allow_web, allow_shell=ctx.deps.allow_shell)
            result = await sub.run(user_request, deps=deps, usage=ctx.usage)
            return result.output.summary

        @agent.tool
        async def run_daily_summary(ctx: RunContext[OrchestratorDeps], date_str: str = "") -> str:
            """Delegate daily digest to the summary sub-agent. Returns summary only.
            Token usage flows back to the parent run via ctx.usage (shared budget)."""
            from sarthak.features.ai.agents import get_agent
            from sarthak.features.ai.deps import AgentDeps
            sub  = get_agent("summary")
            deps = AgentDeps(pool=ctx.deps.pool, cwd=ctx.deps.cwd)
            result = await sub.run(
                f"Generate the daily summary for {date_str or 'today'}.",
                deps=deps, usage=ctx.usage,
            )
            return result.output.summary

    # ── Activity ──────────────────────────────────────────────────────────────
    if "activity" in groups:

        @agent.tool
        async def query_activity(ctx: RunContext[OrchestratorDeps], days: int = 1, limit: int = 30) -> str:
            """Fetch activity digest: stats + head/tail only (no raw rows)."""
            from sarthak.features.ai.tools import tool_query_activity
            return await tool_query_activity(ctx.deps.pool, days=days, limit=limit)

        @agent.tool
        async def get_summary(ctx: RunContext[OrchestratorDeps], date_str: str = "") -> str:
            """Get the AI-generated daily summary. date_str = 'YYYY-MM-DD' or empty for today."""
            from sarthak.features.ai.tools import tool_get_summary
            return await tool_get_summary(ctx.deps.pool, date_str or None)

        @agent.tool
        async def get_tips(ctx: RunContext[OrchestratorDeps], limit: int = 3) -> str:
            """Fetch the latest saved tips."""
            from sarthak.features.ai.tools import tool_get_tips
            return await tool_get_tips(ctx.deps.pool, limit=limit)

        @agent.tool
        async def save_tip(ctx: RunContext[OrchestratorDeps], tip: str) -> str:
            """Persist a new tip to the database."""
            from sarthak.features.ai.tools import tool_save_tip
            return await tool_save_tip(ctx.deps.pool, tip)


    # ── Shell ─────────────────────────────────────────────────────────────────
    if "shell" in groups:

        @agent.tool
        async def run_shell(ctx: RunContext[OrchestratorDeps], command: str) -> str:
            """Run a safe read-only shell command."""
            if not ctx.deps.allow_shell:
                return "Shell access disabled."
            from sarthak.features.ai.tools import tool_run_shell
            return await tool_run_shell(command, cwd=ctx.deps.cwd)

    # ── Skills ────────────────────────────────────────────────────────────────
    if "skills" in groups:

        @agent.tool_plain
        def list_skills_tool() -> str:
            from sarthak.features.ai.skills import tool_list_skills
            return tool_list_skills()

        @agent.tool_plain
        def read_skill_tool(name: str) -> str:
            from sarthak.features.ai.skills import tool_read_skill
            return tool_read_skill(name)

        @agent.tool_plain
        def save_skill_tool(name: str, description: str, content: str, tags: str = "") -> str:
            from sarthak.features.ai.skills import tool_save_skill
            return tool_save_skill(name, description, content, tags)

        @agent.tool_plain
        def delete_skill_tool(name: str) -> str:
            from sarthak.features.ai.skills import tool_delete_skill
            return tool_delete_skill(name)

    # ── System ────────────────────────────────────────────────────────────────
    if "system" in groups:

        @agent.tool_plain
        async def service_status() -> str:
            from sarthak.features.ai.tools import tool_service_status
            return await tool_service_status()

        @agent.tool_plain
        async def restart_service(service: str) -> str:
            from sarthak.features.ai.tools import tool_restart_service
            return await tool_restart_service(service)


    # ── Spaces ────────────────────────────────────────────────────────────────
    if "spaces" in groups:

        @agent.tool
        async def spaces_context(ctx: RunContext[OrchestratorDeps], space_dir: str = "") -> str:
            """
            Get active space context (SOUL + MEMORY).
            Call first for any learning request.
            Hierarchical: loads HEARTBEAT only if question contains srs/streak/cards keywords.
            """
            from sarthak.features.ai.tools import tool_spaces_context_hierarchical
            return await tool_spaces_context_hierarchical(
                space_dir=space_dir, question_hint=ctx.deps.question_hint
            )

        @agent.tool_plain
        def spaces_init(space_dir: str, space_type: str = "data_science",
                        background: str = "", learner_name: str = "") -> str:
            """Initialize a new Sarthak Space in a directory."""
            from sarthak.features.ai.tools import tool_spaces_init
            return tool_spaces_init(space_dir, space_type, background, learner_name)

        @agent.tool
        async def spaces_session(ctx: RunContext[OrchestratorDeps], space_dir: str = "",
                                  space_type: str = "data_science") -> str:
            """
            Run a learning session in an isolated sub-context.
            Strategy 3: returns only a compact summary — full session transcript
            never enters the orchestrator context window.
            """
            from sarthak.features.ai.tools import tool_spaces_session_isolated
            return await tool_spaces_session_isolated(space_dir=space_dir, space_type=space_type)

        @agent.tool_plain
        def spaces_status(space_dir: str = "") -> str:
            """Show learner mastery progress."""
            from sarthak.features.ai.tools import tool_spaces_status
            return tool_spaces_status(space_dir)

        @agent.tool_plain
        def spaces_setup(space_dir: str = "") -> str:
            """Set up expert environment for a space."""
            from sarthak.features.ai.tools import tool_spaces_setup
            return tool_spaces_setup(space_dir)

        @agent.tool_plain
        def spaces_evaluate(concept: str, submission: str, space_dir: str = "") -> str:
            """Evaluate learner submission and update mastery."""
            from sarthak.features.ai.tools import tool_spaces_evaluate
            return tool_spaces_evaluate(concept, submission, space_dir)

        @agent.tool_plain
        def spaces_quick(space_dir: str = "") -> str:
            """Run a 5-minute micro-learning task."""
            from sarthak.features.ai.tools import tool_spaces_quick
            return tool_spaces_quick(space_dir)

        @agent.tool_plain
        def spaces_list() -> str:
            """List all known Sarthak spaces."""
            from sarthak.features.ai.tools import tool_spaces_list
            return tool_spaces_list()


    # ── RAG ───────────────────────────────────────────────────────────────────
    if "rag" in groups:

        @agent.tool_plain
        def spaces_rag_index(space_dir: str = "", full: bool = False) -> str:
            """Index or re-index workspace files for RAG search."""
            from sarthak.features.ai.tools import tool_spaces_rag_index
            return tool_spaces_rag_index(space_dir, full)

        @agent.tool_plain
        def spaces_rag_search(query: str, space_dir: str = "", top_k: int = 5) -> str:
            """Search indexed workspace files for content relevant to query."""
            from sarthak.features.ai.tools import tool_spaces_rag_search
            return tool_spaces_rag_search(query, space_dir, top_k)

    # ── Workspace ─────────────────────────────────────────────────────────────
    if "workspace" in groups:

        @agent.tool_plain
        def workspace_qa(question: str, space_dir: str = "") -> str:
            """Answer questions about workspace data: sessions, notes, SRS cards, etc."""
            from sarthak.features.ai.tools import tool_workspace_qa
            return tool_workspace_qa(question, space_dir)

        @agent.tool_plain
        def workspace_analyse(space_dir: str = "") -> str:
            """Force-refresh workspace analysis (Optimal_Learn.md)."""
            from sarthak.features.ai.tools import tool_workspace_analyse
            return tool_workspace_analyse(space_dir)

