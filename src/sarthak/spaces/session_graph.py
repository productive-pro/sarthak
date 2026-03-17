"""
Sarthak Spaces — Graph-based session flow (pydantic-graph).

Replaces the linear await-chain in SpacesOrchestrator.next_session() with
a typed, checkpointable graph. Each step is a BaseNode; state flows via
SessionState. On any node failure the graph can be resumed from the last
completed node.

Graph:
  PrepareProfile
    → SetupWorkspace (optional, only on first session or reshape_workspace=True)
    → PlanSession
    → BuildContent   (parallel: explain_math + build_task)
    → RenderReply
    → PostSession    (parallel: workspace analysis + roadmap record + memory log)
    → End

Usage:
  from sarthak.spaces.session_graph import run_session_graph
  result: MasteryResult = await run_session_graph(workspace_dir, **kwargs)

pydantic-graph docs: https://ai.pydantic.dev/graph/
"""
from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import TYPE_CHECKING

from pydantic_graph import BaseNode, End, Graph, GraphRunContext

from sarthak.core.logging import get_logger
from sarthak.spaces.models import (
    LEVEL_LABELS, LearningTask, MasteryResult, SkillLevel,
    SpaceContext, SpaceProfile, SpaceType, award_xp, update_streak,
)

if TYPE_CHECKING:
    from sarthak.spaces.agents import SpacesSkills, WorkspaceAnalyserAgent

log = get_logger(__name__)


# ── Shared state flowing through the graph ────────────────────────────────────

@dataclass
class SessionState:
    """All state accumulated across graph nodes. Serialisable for checkpointing."""
    workspace_dir: str
    space_type: str = "data_science"
    reshape_workspace: bool = False
    planned_minutes: int = 30
    concept_override: str | None = None
    track_session: bool = False

    # Filled in as nodes execute
    profile_json: str = ""          # SpaceProfile.model_dump_json()
    curriculum: dict = field(default_factory=dict)
    concept: str = ""
    session_type: str = "new_concept"
    suggest_project: bool = False
    review_due: list[str] = field(default_factory=list)
    workspace_changes: list[str] = field(default_factory=list)
    tools_added: list[str] = field(default_factory=list)
    math_data: dict = field(default_factory=dict)
    task_json: str = ""             # LearningTask.model_dump_json()
    reply: str = ""
    xp_earned: int = 0
    new_badges: list[str] = field(default_factory=list)
    leveled_up: bool = False
    activity_prompt: str = ""

    def load_profile(self) -> SpaceProfile:
        return SpaceProfile.model_validate_json(self.profile_json)

    def save_profile(self, profile: SpaceProfile) -> None:
        self.profile_json = profile.model_dump_json()

    def load_task(self) -> LearningTask:
        return LearningTask.model_validate_json(self.task_json)

    def save_task(self, task: LearningTask) -> None:
        self.task_json = task.model_dump_json()

    @property
    def workspace_path(self) -> Path:
        return Path(self.workspace_dir)

    @property
    def space_type_enum(self) -> SpaceType:
        try:
            return SpaceType(self.space_type)
        except ValueError:
            return SpaceType.DATA_SCIENCE


# ── Node 1: PrepareProfile ─────────────────────────────────────────────────────

@dataclass
class PrepareProfile(BaseNode[SessionState]):
    """Load or init profile, run onboarding if first session, update streak."""

    async def run(self, ctx: GraphRunContext[SessionState]) -> "SetupWorkspace | PlanSession":
        from sarthak.spaces.store import init_space_profile, load_profile, save_profile
        from sarthak.spaces.agents import SpacesSkills, detect_platform, is_technical
        from sarthak.spaces.learner_context import build_learner_context, learner_context_for_prompt

        s = ctx.state
        ws = s.workspace_path
        skills = SpacesSkills()

        profile = load_profile(ws) or init_space_profile(ws, s.space_type_enum)

        # Onboarding — only on first session with background set
        if profile.learner.total_sessions == 0 and profile.learner.background:
            analysis = await skills.onboard(
                background=profile.learner.background,
                goal=profile.learner.goal or "",
                domain=profile.domain,
            )
            profile.learner.is_technical = analysis.get("is_technical", True)
            if not profile.learner.goal and analysis.get("inferred_goal"):
                profile.learner.goal = analysis["inferred_goal"]
            if analysis.get("learning_style_hint"):
                profile.learner.preferred_style = analysis["learning_style_hint"]
            try:
                profile.learner.skill_level = SkillLevel(
                    analysis.get("recommended_start_level", "novice"))
            except ValueError:
                pass

        profile = update_streak(profile)
        s.save_profile(profile)

        # Build learner context for activity prompt
        lc = await build_learner_context(ws, profile, days=14)
        s.activity_prompt = learner_context_for_prompt(lc)
        s.review_due = lc.srs_due_by_evidence[:2]

        # Decide whether workspace setup is needed
        if s.reshape_workspace or not profile.expert_tools_installed:
            return SetupWorkspace()
        return PlanSession()


# ── Node 2: SetupWorkspace (optional) ─────────────────────────────────────────

@dataclass
class SetupWorkspace(BaseNode[SessionState]):
    """Scan environment and design workspace structure. Runs only when needed."""

    async def run(self, ctx: GraphRunContext[SessionState]) -> "PlanSession":
        from sarthak.spaces.agents import SpacesSkills, detect_platform
        from sarthak.spaces.tools import scan_environment, apply_workspace_design

        s       = ctx.state
        profile = s.load_profile()
        skills  = SpacesSkills()
        space_ctx = SpaceContext(
            workspace_dir=s.workspace_dir, profile=profile, platform=detect_platform())

        scan_data = scan_environment(space_ctx)
        ws_design, env_result = await asyncio.gather(
            skills.design_workspace(space_ctx),
            skills.recommend_environment(scan_data, space_ctx),
        )
        s.workspace_changes = apply_workspace_design(ws_design, s.workspace_path)
        s.tools_added = [t["name"] for t in env_result.get("missing", [])]
        profile.expert_tools_installed = env_result.get("installed", [])
        s.save_profile(profile)
        return PlanSession()


# ── Node 3: PlanSession ────────────────────────────────────────────────────────

@dataclass
class PlanSession(BaseNode[SessionState]):
    """Select next concept using ZPD + review due signals."""

    async def run(self, ctx: GraphRunContext[SessionState]) -> "BuildContent":
        from sarthak.spaces.agents import SpacesSkills, detect_platform
        from sarthak.spaces.domain_loader import get_next_concepts

        s       = ctx.state
        profile = s.load_profile()
        skills  = SpacesSkills()
        space_ctx = SpaceContext(
            workspace_dir=s.workspace_dir, profile=profile, platform=detect_platform())

        available  = get_next_concepts(
            profile.space_type, profile.learner.mastered_concepts, profile.learner.skill_level)
        curriculum = await skills.plan_curriculum(
            space_ctx, available, s.review_due, activity_context=s.activity_prompt)

        s.curriculum    = curriculum
        s.concept       = s.concept_override or curriculum.get("next_concept") or (
            available[0] if available else "Python basics")
        s.session_type  = curriculum.get("session_type", "new_concept")
        s.suggest_project = curriculum.get("suggest_project", False)

        if not s.review_due:
            from sarthak.spaces.tools.srs import get_due_reviews
            s.review_due = get_due_reviews(profile)

        return BuildContent()


# ── Node 4: BuildContent ───────────────────────────────────────────────────────

@dataclass
class BuildContent(BaseNode[SessionState]):
    """Parallel: explain math + build task. Pure LLM — no side effects."""

    async def run(self, ctx: GraphRunContext[SessionState]) -> "RenderReply":
        from sarthak.spaces.agents import SpacesSkills, detect_platform

        s       = ctx.state
        profile = s.load_profile()
        skills  = SpacesSkills()
        space_ctx = SpaceContext(
            workspace_dir=s.workspace_dir, profile=profile, platform=detect_platform())

        math_data, task = await asyncio.gather(
            skills.explain_math(
                s.concept, profile.learner.skill_level,
                profile.learner.background,
                is_technical_flag=profile.learner.is_technical,
            ),
            skills.build_task(s.concept, space_ctx, {}),
        )
        task.math_foundation = math_data.get("numpy_equivalent", task.math_foundation)
        s.math_data = math_data
        s.save_task(task)
        s.xp_earned = task.xp_reward
        return RenderReply()


# ── Node 5: RenderReply ────────────────────────────────────────────────────────

@dataclass
class RenderReply(BaseNode[SessionState]):
    """Award XP, check badges, render the engagement reply string."""

    async def run(self, ctx: GraphRunContext[SessionState]) -> "PostSession":
        from sarthak.spaces.agents import SpacesSkills
        from sarthak.spaces.tools.badges import check_and_award

        s       = ctx.state
        profile = s.load_profile()
        skills  = SpacesSkills()
        task    = s.load_task()

        profile, leveled_up = award_xp(profile, s.xp_earned)
        s.leveled_up = leveled_up

        content = {
            "concept": s.concept, "session_type": s.session_type,
            "why_now":   s.curriculum.get("why_now", ""),
            "review_concept": s.curriculum.get("review_concept", ""),
            "intuition": s.math_data.get("intuition", ""),
            "key_formulas": s.math_data.get("key_formulas", []),
            "derivation_steps": s.math_data.get("derivation_steps", []),
            "numpy_equivalent": s.math_data.get("numpy_equivalent", ""),
            "common_misconceptions": s.math_data.get("common_misconceptions", []),
            "task": {
                "title": task.title, "real_world_hook": task.real_world_hook,
                "instructions": task.instructions, "starter_code": task.starter_code,
                "no_code_version": task.no_code_version,
                "expected_outcome": task.expected_outcome,
                "hints": task.hints, "bonus_challenge": task.bonus_challenge,
                "estimated_minutes": task.estimated_minutes,
            },
            "learning_path": s.curriculum.get("learning_path", []),
            "tools_to_use": profile.expert_tools_installed[:3],
            "streak": profile.learner.streak_days, "xp": profile.learner.xp,
            "level": LEVEL_LABELS.get(profile.learner.skill_level, ""),
            "suggest_project": s.suggest_project,
            "activity_context": s.activity_prompt,
        }
        if leveled_up:
            content["level_up"] = LEVEL_LABELS.get(profile.learner.skill_level, "")

        s.reply = await skills.render_engagement(
            content, profile.learner.background, s.xp_earned,
            novel_approach=False, is_technical_flag=profile.learner.is_technical,
        )

        profile.learner.total_sessions += 1
        s.new_badges = check_and_award(profile, {"novel_approach": False})
        if s.new_badges:
            suffix = "s" if len(s.new_badges) > 1 else ""
            s.reply += f"\n\n---\n**Badge{suffix}**: {', '.join(s.new_badges)}"

        s.save_profile(profile)
        return PostSession()


# ── Node 6: PostSession ────────────────────────────────────────────────────────

@dataclass
class PostSession(BaseNode[SessionState]):
    """Parallel: workspace analysis + roadmap record + memory log. Then persist."""

    async def run(self, ctx: GraphRunContext[SessionState]) -> End[MasteryResult]:
        from sarthak.spaces.agents import WorkspaceAnalyserAgent, detect_platform
        from sarthak.spaces.tools import detect_external_tools
        from sarthak.spaces.roadmap_tracker import record_session_to_roadmap
        from sarthak.spaces.store import save_profile as _save_profile

        s       = ctx.state
        profile = s.load_profile()
        task    = s.load_task()
        ws      = s.workspace_path
        ext_tools = detect_external_tools(ws)

        async def _analyse() -> None:
            try:
                space_ctx = SpaceContext(
                    workspace_dir=s.workspace_dir, profile=profile,
                    platform=detect_platform())
                analyser = WorkspaceAnalyserAgent()
                content  = await analyser.analyse(space_ctx)
                analyser.write_optimal_learn(ws, content)
            except Exception as exc:
                log.warning("post_session_analyse_skipped", error=str(exc))

        async def _record() -> None:
            try:
                await asyncio.to_thread(
                    record_session_to_roadmap,
                    ws, profile, concept=s.concept, xp_earned=s.xp_earned,
                    tools_used=profile.expert_tools_installed[:5],
                    external_tools=ext_tools, mastered=False,
                )
            except Exception as exc:
                log.warning("post_session_record_skipped", error=str(exc))

        async def _log_memory() -> None:
            try:
                from sarthak.spaces.memory import append_daily_log, sync_heartbeat_md
                from sarthak.spaces.roadmap.srs import get_due
                from sarthak.spaces.session_tracker import SpaceSession
                from sarthak.spaces.models import SessionSignals, SelfReport as _SR
                _session = SpaceSession(
                    session_id="orch", space_dir=s.workspace_dir, concept=s.concept,
                    started_at=datetime.now(timezone.utc),
                    ended_at=datetime.now(timezone.utc),
                    planned_minutes=s.planned_minutes,
                    signals=SessionSignals(), self_report=_SR(),
                )
                due_cards: list[str] = []
                try:
                    cards = await get_due(str(ws / ".spaces" / "sarthak.db"))
                    due_cards = [c.concept for c in cards[:8]]
                except Exception:
                    pass
                await asyncio.gather(
                    append_daily_log(ws, _session, profile,
                                     xp_earned=s.xp_earned, badges_earned=s.new_badges),
                    asyncio.to_thread(sync_heartbeat_md, ws, profile, due_cards),
                )
            except Exception as exc:
                log.debug("post_session_memory_skipped", error=str(exc))

        await asyncio.gather(_analyse(), _record(), _log_memory())

        # Persist final profile state
        profile.updated_at = datetime.now(timezone.utc).isoformat()
        _save_profile(ws, profile)

        return End(MasteryResult(
            reply=s.reply,
            next_task=task,
            workspace_changes=s.workspace_changes,
            tools_added=s.tools_added,
            xp_earned=s.xp_earned,
            action_taken=f"Taught: {s.concept}",
            badges_earned=s.new_badges,
            review_due=s.review_due,
        ))


# ── Graph definition ──────────────────────────────────────────────────────────

_SESSION_GRAPH: Graph[SessionState, None, MasteryResult] = Graph(
    nodes=[PrepareProfile, SetupWorkspace, PlanSession, BuildContent, RenderReply, PostSession],
)


# ── Public entry point ────────────────────────────────────────────────────────

async def run_session_graph(
    workspace_dir: str | Path,
    space_type: SpaceType | None = None,
    reshape_workspace: bool = False,
    planned_minutes: int = 30,
    concept_override: str | None = None,
    track_session: bool = False,
) -> MasteryResult:
    """
    Execute the session graph from PrepareProfile to PostSession.
    Each node is a typed step; state is passed via SessionState.
    On failure, the graph raises — the caller (SpacesOrchestrator) handles it.
    """
    state = SessionState(
        workspace_dir=str(Path(workspace_dir).resolve()),
        space_type=(space_type.value if space_type else "data_science"),
        reshape_workspace=reshape_workspace,
        planned_minutes=planned_minutes,
        concept_override=concept_override,
        track_session=track_session,
    )
    result, _ = await _SESSION_GRAPH.run(PrepareProfile(), state=state)
    return result
