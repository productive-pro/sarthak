"""
Sarthak — AG-UI endpoint (CopilotKit shared-state strategy).

How CopilotKit uses AG-UI shared state
---------------------------------------
CopilotKit fronts the agent with a "shared state" model:

  1. Frontend keeps live state (XP, streak, concept, space_dir) via useCoAgent.
  2. On each POST the frontend serialises that state into RunAgentInput.state.
  3. Backend validates it into SarthakUIState, injects via StateDeps.
  4. Tools read ctx.deps.state to know which space is active (no extra round-trip).
  5. After a spaces_session call the tool MUTATES ctx.deps.state (xp, streak, …).
  6. pydantic-ai detects the mutation and emits a STATE_DELTA event — CopilotKit
     picks it up and re-renders XP bar, streak chip, active concept panel.

Endpoint:  POST /api/ag-ui
Body:      AG-UI RunAgentInput (JSON, from CopilotKit useCoAgent hook)
Response:  text/event-stream — RUN_STARTED … TEXT_MESSAGE_CONTENT …
           STATE_DELTA … RUN_FINISHED

Frontend (React + CopilotKit)
------------------------------
  import { useCoAgent, CopilotKit } from "@copilotkit/react-core";

  const { state } = useCoAgent({
    name: "sarthak",
    initialState: { xp: 0, streak: 0, level: "", concept: "", space_dir: "" },
  });
  // state updates automatically when the agent emits STATE_DELTA

  <CopilotKit runtimeUrl="/api/ag-ui">…</CopilotKit>
"""
from __future__ import annotations

from fastapi import APIRouter, Request
from fastapi.responses import Response
from pydantic import BaseModel, Field

from pydantic_ai import Agent, RunContext
from pydantic_ai.ui import StateDeps
from pydantic_ai.ui.ag_ui import AGUIAdapter

from sarthak.core.logging import get_logger
from sarthak.features.ai.agents._base import resolve_provider_model, build_pydantic_model
from sarthak.data.loader import load_agent, build_prompt
from sarthak.features.ai.skills import list_skills, build_context_block

log = get_logger(__name__)
router = APIRouter()


# ── Shared state contract (frontend ↔ backend) ────────────────────────────────

class SarthakUIState(BaseModel):
    """
    Live learner state kept in sync between CopilotKit frontend and backend.
    The frontend initialises with zeros; tools update it so STATE_DELTA events
    re-render XP bar, streak, active concept without a page reload.
    """
    xp: int = 0
    streak: int = 0
    level: str = ""
    concept: str = ""        # currently active concept
    space_dir: str = ""      # which workspace is active (passed in by frontend)
    session_count: int = 0
    badges: list[str] = Field(default_factory=list)


# deps type for this agent: StateDeps carries .state: SarthakUIState
AGUIDeps = StateDeps[SarthakUIState]


# ── AG-UI specific agent (separate from the main orchestrator) ────────────────
# This agent has deps_type=StateDeps[SarthakUIState] so pydantic-ai can detect
# .state mutations and emit STATE_DELTA events automatically.
# Tools here read ctx.deps.state.space_dir instead of needing a passed arg.

def _build_ag_ui_agent(provider: str, model_name: str) -> Agent[AGUIDeps, str]:
    """Build the AG-UI agent. Cached by caller via _get_ag_ui_agent()."""
    from pydantic_ai.common_tools.duckduckgo import duckduckgo_search_tool
    meta   = load_agent("orchestrator")
    skills = list_skills()
    prompt = build_prompt(meta, build_context_block(skills) if skills else "").format(
        skills_context=build_context_block(skills) if skills else ""
    )
    agent: Agent[AGUIDeps, str] = Agent(
        build_pydantic_model(provider, model_name),
        output_type=str,
        deps_type=AGUIDeps,
        system_prompt=prompt,
        retries=2,
        tools=[duckduckgo_search_tool()],
    )
    _register_ag_ui_tools(agent)
    return agent


# simple 2-key cache so we don't rebuild on every request
_AGENT_CACHE: dict[tuple[str, str], Agent] = {}


def _get_ag_ui_agent(provider: str, model_name: str) -> Agent[AGUIDeps, str]:
    """Return a cached AG-UI agent for the given provider/model pair."""
    key = (provider, model_name)
    if key not in _AGENT_CACHE:
        _AGENT_CACHE[key] = _build_ag_ui_agent(provider, model_name)
    return _AGENT_CACHE[key]


# ── Tool registration ─────────────────────────────────────────────────────────

def _register_ag_ui_tools(agent: Agent[AGUIDeps, str]) -> None:
    """Register tools that read/write SarthakUIState for STATE_DELTA emission."""

    @agent.tool
    async def spaces_session(ctx: RunContext[AGUIDeps], space_type: str = "data_science") -> str:
        """
        Run a Sarthak Spaces learning session.

        Reads space_dir from shared state (no need to pass it explicitly from
        the frontend — CopilotKit already synced it via RunAgentInput.state).
        After the session, mutates ctx.deps.state so pydantic-ai emits a
        STATE_DELTA event that updates the XP bar and streak chip in real time.
        """
        import asyncio, concurrent.futures
        from pathlib import Path
        from sarthak.spaces.orchestrator import SpacesOrchestrator
        from sarthak.spaces.models import SpaceType

        space_dir = ctx.deps.state.space_dir
        ws_dir = Path(space_dir).resolve() if space_dir else Path.cwd()

        executor = concurrent.futures.ThreadPoolExecutor(max_workers=1)
        loop = asyncio.get_running_loop()
        try:
            st = SpaceType(space_type)
        except ValueError:
            st = SpaceType.DATA_SCIENCE

        orch = SpacesOrchestrator(ws_dir)
        result = await loop.run_in_executor(
            executor, lambda: asyncio.run(orch.next_session(space_type=st))
        )

        # ── CopilotKit strategy: mutate state → triggers STATE_DELTA ──────────
        s = ctx.deps.state
        s.xp            += result.xp_earned
        s.streak         = _read_streak(ws_dir) or s.streak
        s.concept        = result.action_taken.removeprefix("Taught: ")
        s.session_count += 1
        if result.badges_earned:
            s.badges = list(dict.fromkeys(s.badges + result.badges_earned))

        # Compact reply only — keeps orchestrator context tight
        reply = result.reply or ""
        return reply[:400] + "…" if len(reply) > 400 else reply

    @agent.tool
    async def spaces_status(ctx: RunContext[AGUIDeps]) -> str:
        """Show learner mastery progress. Syncs current XP/streak into state."""
        from pathlib import Path
        from sarthak.spaces.orchestrator import SpacesOrchestrator
        from sarthak.spaces.store import load_profile

        ws_dir = Path(ctx.deps.state.space_dir).resolve() if ctx.deps.state.space_dir else Path.cwd()
        orch   = SpacesOrchestrator(ws_dir)
        status = orch.get_status()

        # Sync state from disk profile so frontend panels stay accurate
        profile = load_profile(ws_dir)
        if profile:
            s = ctx.deps.state
            s.xp            = profile.learner.xp
            s.streak        = profile.learner.streak_days
            s.session_count = profile.learner.total_sessions
            s.badges        = list(profile.learner.badges)

        return status

    @agent.tool
    async def spaces_context(ctx: RunContext[AGUIDeps]) -> str:
        """Get active space context (SOUL + MEMORY). Use before any learning request."""
        from sarthak.features.ai.tools.spaces import tool_spaces_context_hierarchical
        return await tool_spaces_context_hierarchical(space_dir=ctx.deps.state.space_dir)

    @agent.tool_plain
    def spaces_init(space_dir: str, space_type: str = "data_science",
                    background: str = "", learner_name: str = "") -> str:
        """Initialize a new Sarthak Space in a directory."""
        from sarthak.features.ai.tools.spaces import tool_spaces_init
        return tool_spaces_init(space_dir, space_type, background, learner_name)

    @agent.tool_plain
    def spaces_evaluate(concept: str, submission: str) -> str:
        """Evaluate learner submission and update mastery."""
        from sarthak.features.ai.tools.spaces import tool_spaces_evaluate
        return tool_spaces_evaluate(concept, submission)

    @agent.tool_plain
    def spaces_list() -> str:
        """List all known Sarthak spaces."""
        from sarthak.features.ai.tools.spaces import tool_spaces_list
        return tool_spaces_list()


def _read_streak(ws_dir) -> int:
    """Read current streak from disk profile without throwing."""
    try:
        from sarthak.spaces.store import load_profile
        p = load_profile(ws_dir)
        return p.learner.streak_days if p else 0
    except Exception:
        return 0


# ── Endpoint ──────────────────────────────────────────────────────────────────

@router.post("/api/ag-ui")
async def ag_ui_endpoint(request: Request) -> Response:
    """
    AG-UI streaming endpoint — CopilotKit shared-state strategy.

    Flow per request:
      1. Parse RunAgentInput from body.
      2. Validate RunAgentInput.state → SarthakUIState (contains space_dir).
      3. Build StateDeps(state=...) — implements StateHandler protocol.
      4. Run AG-UI agent with those deps.
      5. When a tool mutates ctx.deps.state, pydantic-ai emits STATE_DELTA.
      6. CopilotKit frontend receives STATE_DELTA → re-renders XP, streak, concept.
    """
    body      = await request.body()
    run_input = AGUIAdapter.build_run_input(body)

    raw_state = run_input.state or {}
    state     = SarthakUIState.model_validate(raw_state)
    deps      = StateDeps(state=state)

    p, m  = resolve_provider_model()
    agent = _get_ag_ui_agent(p, m)

    log.info("ag_ui_request", provider=p, model=m,
             space_dir=state.space_dir, xp=state.xp, streak=state.streak)

    return await AGUIAdapter.dispatch_request(
        agent=agent,
        request=request,
        deps=deps,
    )
