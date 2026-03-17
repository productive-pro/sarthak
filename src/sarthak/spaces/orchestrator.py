"""
Sarthak Spaces — Main Orchestrator.

Coordinates SpacesSkills + pure-logic tools to deliver mastery sessions.
All state lives on disk (SpaceProfile). This class is stateless per call.

Public API:
  await orch.next_session()        → full adaptive learning session
  await orch.quicktest()           → 5-minute QuickTest
  await orch.evaluate(task, code)  → assess submitted work
  await orch.start_project()       → scaffold a real end-to-end project
  await orch.setup_environment()   → scan + reshape workspace only
       orch.update_learner(**kw)   → update profile fields
       orch.get_status()           → rich summary string
"""
from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from pathlib import Path

from sarthak.core.logging import get_logger
from sarthak.spaces.domain_loader import get_available_projects, get_next_concepts
from sarthak.spaces.learner_context import build_learner_context, learner_context_for_prompt
from sarthak.spaces.models import (
    LEVEL_LABELS, XP_THRESHOLDS,
    LearningTask, MasteryResult, SelfReport, SkillLevel,
    SpaceContext, SpaceProfile, SpaceType,
    award_xp, update_streak,
)
from sarthak.spaces.optimizer import SignalOptimizer
from sarthak.spaces.practice import PracticeEngine
from sarthak.spaces.session_tracker import SpaceSessionTracker, save_session
from sarthak.spaces.store import init_space_profile, load_profile, save_profile
from sarthak.spaces.agents import SpacesSkills, WorkspaceAnalyserAgent, detect_platform, is_technical
from sarthak.spaces.tools import (
    get_due_reviews, update_after_review, check_and_award,
    scan_environment, detect_external_tools, apply_workspace_design,
)

log = get_logger(__name__)


class SpacesOrchestrator:
    """
    Entry point for all Sarthak Spaces interactions.
    Stateless per call — all state lives in SpaceProfile on disk.

    Architecture (single-responsibility):
      self._skills      — all LLM calls (SpacesSkills, one instance)
      self._ws_analyser — complex multi-step workspace analysis
      self._practice    — timed practice test engine
      self._optimizer   — signal-based learning optimization
    Pure-logic tools (SRS, badges, env scan) are module-level functions.
    """

    def __init__(self, workspace_dir: str | Path):
        self.workspace_dir = Path(workspace_dir).resolve()
        self._skills      = SpacesSkills()
        self._ws_analyser = WorkspaceAnalyserAgent()
        self._practice    = PracticeEngine()
        self._optimizer   = SignalOptimizer()

    # ── Profile helpers ────────────────────────────────────────────────────────

    def _load_or_init(self, space_type: SpaceType | None = None) -> SpaceProfile:
        return load_profile(self.workspace_dir) or init_space_profile(
            self.workspace_dir, space_type or SpaceType.DATA_SCIENCE
        )

    def _save(self, profile: SpaceProfile) -> None:
        profile.updated_at = datetime.now(timezone.utc).isoformat()
        save_profile(self.workspace_dir, profile)

    def _build_ctx(self, profile: SpaceProfile) -> SpaceContext:
        return SpaceContext(
            workspace_dir=str(self.workspace_dir),
            profile=profile,
            platform=detect_platform(),
        )

    async def _prepare_profile(self, space_type: SpaceType | None) -> tuple[SpaceProfile, SpaceContext]:
        profile = self._load_or_init(space_type)
        profile = await self._maybe_onboard(profile)
        profile = update_streak(profile)
        return profile, self._build_ctx(profile)

    async def _maybe_setup_workspace(
        self, profile: SpaceProfile, ctx: SpaceContext, reshape: bool,
    ) -> tuple[SpaceProfile, SpaceContext, list[str], list[str]]:
        if not (reshape or not profile.expert_tools_installed):
            return profile, ctx, [], []
        scan_data = scan_environment(ctx)
        ws_design, env_result = await asyncio.gather(
            self._skills.design_workspace(ctx),
            self._skills.recommend_environment(scan_data, ctx),
        )
        workspace_changes = apply_workspace_design(ws_design, self.workspace_dir)
        profile.expert_tools_installed = env_result.get("installed", [])
        tools_added = [t["name"] for t in env_result.get("missing", [])]
        self._save(profile)
        return profile, self._build_ctx(profile), workspace_changes, tools_added

    async def _plan_session(
        self, profile: SpaceProfile, ctx: SpaceContext, lc, activity_prompt: str, concept_override: str | None,
    ) -> tuple[dict, str, str, bool, list[str]]:
        review_due = lc.srs_due_by_evidence[:2] or get_due_reviews(profile)
        available  = get_next_concepts(profile.space_type, profile.learner.mastered_concepts, profile.learner.skill_level)
        curriculum = await self._skills.plan_curriculum(ctx, available, review_due, activity_context=activity_prompt)
        next_concept  = concept_override or curriculum.get("next_concept") or (available[0] if available else "Python basics")
        session_type  = curriculum.get("session_type", "new_concept")
        suggest_project = curriculum.get("suggest_project", False)
        return curriculum, next_concept, session_type, suggest_project, review_due

    async def _build_math_task(
        self, profile: SpaceProfile, ctx: SpaceContext, concept: str,
    ) -> tuple[dict, LearningTask]:
        math_data, task = await asyncio.gather(
            self._skills.explain_math(
                concept, profile.learner.skill_level,
                profile.learner.background, is_technical_flag=profile.learner.is_technical,
            ),
            self._skills.build_task(concept, ctx, {}),
        )
        task.math_foundation = math_data.get("numpy_equivalent", task.math_foundation)
        return math_data, task

    def _build_content(
        self, profile: SpaceProfile, curriculum: dict, concept: str,
        session_type: str, suggest_project: bool, math_data: dict, task: LearningTask,
    ) -> dict:
        return {
            "concept": concept, "session_type": session_type,
            "why_now": curriculum.get("why_now", ""),
            "review_concept": curriculum.get("review_concept", ""),
            "intuition": math_data.get("intuition", ""),
            "key_formulas": math_data.get("key_formulas", []),
            "derivation_steps": math_data.get("derivation_steps", []),
            "numpy_equivalent": math_data.get("numpy_equivalent", ""),
            "common_misconceptions": math_data.get("common_misconceptions", []),
            "task": {
                "title": task.title, "real_world_hook": task.real_world_hook,
                "instructions": task.instructions, "starter_code": task.starter_code,
                "no_code_version": task.no_code_version, "expected_outcome": task.expected_outcome,
                "hints": task.hints, "bonus_challenge": task.bonus_challenge,
                "estimated_minutes": task.estimated_minutes,
            },
            "learning_path": curriculum.get("learning_path", []),
            "tools_to_use": profile.expert_tools_installed[:3],
            "streak": profile.learner.streak_days, "xp": profile.learner.xp,
            "level": LEVEL_LABELS.get(profile.learner.skill_level, ""),
            "suggest_project": suggest_project,
        }

    async def _render_reply(self, profile: SpaceProfile, content: dict, xp: int) -> tuple[str, SpaceProfile]:
        profile, leveled_up = award_xp(profile, xp)
        if leveled_up:
            content["level_up"] = LEVEL_LABELS.get(profile.learner.skill_level, "")
        reply = await self._skills.render_engagement(
            content, profile.learner.background, xp,
            novel_approach=False, is_technical_flag=profile.learner.is_technical,
        )
        return reply, profile

    async def _post_session(
        self, profile: SpaceProfile, ctx: SpaceContext, concept: str,
        xp: int, new_badges: list[str], planned_minutes: int, activity_prompt: str,
    ) -> None:
        ext_tools = detect_external_tools(self.workspace_dir)

        async def _analyse() -> None:
            try:
                content = await self._ws_analyser.analyse(ctx)
                self._ws_analyser.write_optimal_learn(self.workspace_dir, content)
            except Exception as exc:
                log.warning("workspace_analyser_skipped", error=str(exc))

        async def _log_memory() -> None:
            try:
                from sarthak.spaces.memory import append_daily_log, sync_heartbeat_md
                from sarthak.spaces.roadmap.srs import get_due
                from sarthak.spaces.session_tracker import SpaceSession
                from sarthak.spaces.models import SessionSignals, SelfReport as _SelfReport
                _session = SpaceSession(
                    session_id="orch", space_dir=str(self.workspace_dir), concept=concept,
                    started_at=datetime.now(timezone.utc), ended_at=datetime.now(timezone.utc),
                    planned_minutes=planned_minutes, signals=SessionSignals(), self_report=_SelfReport(),
                )
                due_cards: list[str] = []
                try:
                    cards = await get_due(str(self.workspace_dir / ".spaces" / "sarthak.db"))
                    due_cards = [c.concept for c in cards[:8]]
                except Exception:
                    pass
                await asyncio.gather(
                    append_daily_log(self.workspace_dir, _session, profile, xp_earned=xp, badges_earned=new_badges),
                    asyncio.to_thread(sync_heartbeat_md, self.workspace_dir, profile, due_cards),
                )
            except Exception as exc:
                log.debug("memory_session_end_skipped", error=str(exc))

        await asyncio.gather(_analyse(), _record(), _log_memory())

    # ── Onboarding (first session) ─────────────────────────────────────────────

    async def _maybe_onboard(self, profile: SpaceProfile) -> SpaceProfile:
        if profile.learner.total_sessions > 0 or not profile.learner.background:
            return profile
        analysis = await self._skills.onboard(
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
            profile.learner.skill_level = SkillLevel(analysis.get("recommended_start_level", "novice"))
        except ValueError:
            pass
        return profile

    # ── Core: full adaptive learning session ───────────────────────────────────

    async def next_session(
        self,
        space_type: SpaceType | None = None,
        reshape_workspace: bool = False,
        planned_minutes: int = 30,
        concept_override: str | None = None,
        track_session: bool = False,
    ) -> MasteryResult:
        """Full adaptive learning session. The main entry point."""
        profile, ctx = await self._prepare_profile(space_type)
        lc = await build_learner_context(self.workspace_dir, profile, days=14)

        profile, ctx, workspace_changes, tools_added = await self._maybe_setup_workspace(
            profile, ctx, reshape_workspace
        )
        activity_prompt = learner_context_for_prompt(lc)

        curriculum, concept, session_type, suggest_project, review_due = await self._plan_session(
            profile, ctx, lc, activity_prompt, concept_override
        )

        if track_session:
            self._tracker = SpaceSessionTracker(self.workspace_dir, concept, planned_minutes=planned_minutes)
            await self._tracker.start()

        math_data, task = await self._build_math_task(profile, ctx, concept)
        content = self._build_content(profile, curriculum, concept, session_type, suggest_project, math_data, task)

        xp = task.xp_reward
        reply, profile = await self._render_reply(profile, content, xp)

        profile.learner.total_sessions += 1
        new_badges = check_and_award(profile, {"novel_approach": False})
        if new_badges:
            reply += f"\n\n---\n**Badge{'s' if len(new_badges) > 1 else ''}**: {', '.join(new_badges)}"

        ctx = self._build_ctx(profile)
        content["activity_context"] = activity_prompt
        await self._post_session(profile, ctx, concept, xp, new_badges, planned_minutes, activity_prompt)
        self._save(profile)

        return MasteryResult(
            reply=reply, next_task=task, workspace_changes=workspace_changes,
            tools_added=tools_added, xp_earned=xp,
            action_taken=f"Taught: {concept}", badges_earned=new_badges, review_due=review_due,
        )

    # ── QuickTest: 5-minute micro-session ──────────────────────────────────────

    async def quicktest(self) -> MasteryResult:
        """5-minute QuickTest. Perfect for busy learners."""
        profile = self._load_or_init()
        available = get_next_concepts(profile.space_type, profile.learner.mastered_concepts, profile.learner.skill_level)
        concept = available[0] if available else "Python basics"

        from sarthak.spaces.roadmap.quicktest import create_quicktest
        qt, micro = await create_quicktest(
            self.workspace_dir, input_mode="random", prompt="", concept_label=concept,
            level=profile.learner.skill_level, background=profile.learner.background,
            is_technical=profile.learner.is_technical, return_micro=True,
        )
        xp = micro.get("xp_reward", 5)
        profile, leveled_up = award_xp(profile, xp)
        profile.learner.total_sessions += 1
        profile = update_streak(profile)
        self._save(profile)

        reply = f"{qt.response_md}\n\n*streak {profile.learner.streak_days}*"
        if leveled_up:
            reply += f"\n\n**Level Up: {LEVEL_LABELS.get(profile.learner.skill_level)}!**"
        return MasteryResult(reply=reply, xp_earned=xp, action_taken=f"QuickTest: {concept}")

    # ── Evaluate submitted work ────────────────────────────────────────────────

    async def evaluate(self, task_concept: str, task_title: str, submission: str) -> MasteryResult:
        """Evaluate a learner's submission and update mastery state."""
        profile = self._load_or_init()
        task = LearningTask(
            task_id="eval", title=task_title, concept=task_concept,
            difficulty=profile.learner.skill_level, task_type="submission",
            instructions="", expected_outcome="",
        )
        assessment = await self._skills.evaluate_submission(task, submission)

        mastered   = assessment.get("concept_mastered", "")
        struggling = assessment.get("concept_struggling", "")
        novel      = assessment.get("novel_approach", False)

        if mastered and mastered not in profile.learner.mastered_concepts:
            profile.learner.mastered_concepts.append(mastered)
            profile = update_after_review(profile, mastered, recalled=True)
            if mastered in profile.learner.struggling_concepts:
                profile.learner.struggling_concepts.remove(mastered)
        if struggling and struggling not in profile.learner.struggling_concepts:
            profile.learner.struggling_concepts.append(struggling)

        xp = max(5, int(assessment.get("score", 50) * 0.2))
        profile, leveled_up = award_xp(profile, xp)
        new_badges = check_and_award(profile, {"novel_approach": novel})

        try:
            record_session_to_roadmap(
                self.workspace_dir, profile, concept=task_concept, xp_earned=xp,
                tools_used=profile.expert_tools_installed[:5],
                external_tools=detect_external_tools(self.workspace_dir), mastered=bool(mastered),
            )
        except Exception as exc:
            log.warning("roadmap_record_skipped", error=str(exc))

        content = {
            "score": assessment.get("score"), "feedback": assessment.get("feedback", ""),
            "strengths": assessment.get("strengths", []), "gaps": assessment.get("gaps", []),
            "next_step": assessment.get("next_step", ""), "novel_approach": novel,
            "novel_approach_description": assessment.get("novel_approach_description", ""),
        }
        if leveled_up:
            content["level_up"] = LEVEL_LABELS.get(profile.learner.skill_level, "")

        reply = await self._skills.render_engagement(
            content, profile.learner.background, xp,
            novel_approach=novel, is_technical_flag=profile.learner.is_technical,
        )
        if new_badges:
            reply += f"\n\n---\n**Badge earned**: {', '.join(new_badges)}"

        profile.learner.total_sessions += 1
        self._save(profile)
        return MasteryResult(
            reply=reply, xp_earned=xp, concept_mastered=mastered, concept_struggling=struggling,
            action_taken=f"Evaluated: {task_concept}", badges_earned=new_badges,
        )

    # ── Start a real project ───────────────────────────────────────────────────

    async def start_project(self, project_id: str | None = None) -> MasteryResult:
        """Scaffold a real end-to-end project for the learner."""
        profile = self._load_or_init()
        ctx = self._build_ctx(profile)

        completed_ids   = [p.project_id for p in profile.learner.completed_projects]
        available       = get_available_projects(profile.space_type, profile.learner.skill_level, completed_ids)
        if not available:
            return MasteryResult(
                reply="# No Projects Available\n\nComplete more concepts to unlock projects!",
                action_taken="project_unavailable",
            )
        project_info = next((p for p in available if p["id"] == project_id), available[0])
        record, created = await self._skills.scaffold_project(project_info, ctx, self.workspace_dir)

        xp = 50
        profile, leveled_up = award_xp(profile, xp)
        new_badges = check_and_award(profile, {})
        self._save(profile)

        reply = (
            f"# Project Unlocked: {record.title}\n\n**{record.description}**\n\n"
            f"Scaffolded at: `{record.repo_path}`\n\nOpen `ROADMAP.md` for your guide.\n\n"
            f"---\n*+{xp} XP for starting a real project!*"
        )
        if leveled_up:
            reply += f"\n\n**Level Up: {LEVEL_LABELS.get(profile.learner.skill_level)}!**"
        return MasteryResult(
            reply=reply, workspace_changes=created, xp_earned=xp,
            action_taken=f"Started project: {record.title}",
            badges_earned=new_badges, project_scaffolded=record.repo_path,
        )

    # ── Environment setup only ─────────────────────────────────────────────────

    async def setup_environment(self, space_type: SpaceType | None = None) -> MasteryResult:
        """Scan environment + reshape workspace. No teaching."""
        profile = self._load_or_init(space_type)
        ctx     = self._build_ctx(profile)

        scan_data = scan_environment(ctx)
        ws_design, env_result = await asyncio.gather(
            self._skills.design_workspace(ctx),
            self._skills.recommend_environment(scan_data, ctx),
        )
        workspace_changes = apply_workspace_design(ws_design, self.workspace_dir)
        profile.expert_tools_installed = env_result.get("installed", [])
        self._save(profile)

        platform   = env_result.get("platform", "linux")
        missing    = env_result.get("missing", [])
        install_key = "install_windows" if platform == "windows" else \
                      "install_mac" if platform == "darwin" else "install_linux"
        tool_lines = "\n".join(
            f"- **{t['name']}** ({t.get('priority','medium')} priority): {t.get('why','')}  \n"
            f"  `{t.get(install_key) or t.get('install_linux', '')}`"
            for t in missing[:8]
        )
        reply = (
            f"# Expert Environment Setup\n\n"
            f"**Workspace**: `{self.workspace_dir}` | **Platform**: {platform}\n\n"
            f"{env_result.get('summary', '')}\n\n"
            f"## Installed ({len(env_result.get('installed', []))} tools)\n"
            f"`{', '.join(env_result.get('installed', ['none']))}`\n\n"
            f"## Recommended Additions\n{tool_lines or 'Expert environment complete!'}\n\n"
            f"*{len(workspace_changes)} files/directories created.*"
        )
        return MasteryResult(
            reply=reply, workspace_changes=workspace_changes,
            tools_added=[t["name"] for t in missing], action_taken="Environment setup",
        )

    # ── Profile management ─────────────────────────────────────────────────────

    def update_learner(self, **kwargs) -> SpaceProfile:
        """Update learner profile fields directly."""
        profile = self._load_or_init()
        for key, val in kwargs.items():
            if hasattr(profile.learner, key):
                setattr(profile.learner, key, val)
        if "background" in kwargs:
            profile.learner.is_technical = is_technical(kwargs["background"])
        self._save(profile)
        return profile

    # ── Session end + optimization ─────────────────────────────────────────────

    async def end_session(self, report: SelfReport) -> MasteryResult:
        """End the current tracked session, collect signals, run optimizer."""
        if not hasattr(self, "_tracker") or not self._tracker:
            return MasteryResult(reply="No active tracked session.", action_taken="end_session_noop")

        session = await self._tracker.end(report)
        self._tracker = None
        save_session(self.workspace_dir, session)

        profile = self._load_or_init()
        depth = session.signals.depth_score
        xp = max(5, int(depth * 30)) + (10 if report.task_completed else 0)
        profile, leveled_up = award_xp(profile, xp)

        for concept in report.stuck_on:
            if concept and concept not in profile.learner.struggling_concepts:
                profile.learner.struggling_concepts.append(concept)
        if report.understanding_rating >= 4:
            if session.concept not in profile.learner.mastered_concepts:
                profile.learner.mastered_concepts.append(session.concept)
            profile = update_after_review(profile, session.concept, recalled=True)
        elif report.understanding_rating <= 2:
            profile = update_after_review(profile, session.concept, recalled=False)

        new_badges = check_and_award(profile, {})
        self._save(profile)

        lc            = await build_learner_context(self.workspace_dir, profile, days=14)
        optimizations = self._optimizer.analyze_from_context(self.workspace_dir, profile, lc)

        active_min = round(session.signals.active_seconds / 60, 1)
        focus_pct  = round(session.signals.focus_ratio * 100)
        lines = [
            "## Session Complete", "",
            f"**Concept**: {session.concept}",
            f"**Active time**: {active_min} min | **Focus**: {focus_pct}%",
            f"**Files edited**: {len(session.signals.files_edited)} | "
            f"**Lines written**: {session.signals.lines_written} | "
            f"**Commits**: {session.signals.git_commits}",
            f"**Depth score**: {session.signals.depth_score:.2f} / 1.0",
        ]
        if report.breakthrough:
            lines.append(f"\n*{report.breakthrough}*")
        if leveled_up:
            lines.append(f"\n**Level Up: {LEVEL_LABELS.get(profile.learner.skill_level)}!**")
        if new_badges:
            lines.append(f"\n{', '.join(new_badges)}")

        return MasteryResult(
            reply="\n".join(lines), xp_earned=xp,
            action_taken=f"Session ended: {session.concept}",
            badges_earned=new_badges, optimizations=optimizations,
        )

    # ── Practice tests ─────────────────────────────────────────────────────────

    async def run_practice(
        self,
        test_type: str = "concept", scope: str = "",
        source: str = "llm", source_prompt: str = "",
        n_questions: int | None = None, seconds_per_question: int = 120,
        interactive: bool = False,
    ) -> MasteryResult:
        """Generate and run a timed practice test."""
        import threading
        import time as _t

        profile = self._load_or_init()
        ctx     = self._build_ctx(profile)
        test = await self._practice.create_test(
            ctx, test_type=test_type, scope=scope, source=source,
            source_prompt=source_prompt, seconds_per_question=seconds_per_question,
            n_questions=n_questions,
        )

        if not interactive:
            lines = [
                f"# Practice Test — {test.scope}",
                f"**{len(test.questions)} questions** | "
                f"**{test.total_time_seconds // 60} min total** | "
                f"**{seconds_per_question}s per question**", "",
            ]
            for i, q in enumerate(test.questions, 1):
                lines.append(f"**Q{i}. [{q.question_type.upper()}]** {q.question}")
                for opt in q.options:
                    lines.append(f"  - {opt}")
                lines.append("")
            return MasteryResult(reply="\n".join(lines), action_taken=f"Practice test generated: {test.scope}")

        # Interactive CLI runner
        answers:    dict[str, str] = {}
        time_taken: dict[str, int] = {}
        print(f"\n Practice Test: {test.scope}")
        print(f"{len(test.questions)} questions | {seconds_per_question}s per question")
        print("─" * 50)

        for i, q in enumerate(test.questions, 1):
            print(f"\nQ{i}/{len(test.questions)} [{q.question_type.upper()}] ({q.time_limit_seconds}s) — {q.concept}")
            print(q.question)
            for opt in q.options:
                print(f"  {opt}")

            start_t  = _t.time()
            done_evt = threading.Event()

            def _countdown(limit: int, done: threading.Event) -> None:
                for remaining in range(limit, 0, -1):
                    if done.is_set():
                        return
                    print(f"  {remaining}s  ", end="\r", flush=True)
                    _t.sleep(1)
                if not done.is_set():
                    print("\n  Time's up!   ")

            timer = threading.Thread(target=_countdown, args=(q.time_limit_seconds, done_evt), daemon=True)
            timer.start()
            try:
                answer = (await asyncio.to_thread(input, "Your answer: ")).strip()
            except EOFError:
                answer = ""
            finally:
                done_evt.set()

            answers[q.question_id]    = answer
            time_taken[q.question_id] = min(int(_t.time() - start_t), q.time_limit_seconds)

        print("\nGrading…")
        result = await self._practice.grade_test(test, answers, time_taken)

        for concept in result.strong_concepts:
            if concept not in profile.learner.mastered_concepts:
                profile.learner.mastered_concepts.append(concept)
            profile = update_after_review(profile, concept, recalled=True)
        for concept in result.weak_concepts:
            if concept not in profile.learner.struggling_concepts:
                profile.learner.struggling_concepts.append(concept)
            profile = update_after_review(profile, concept, recalled=False)

        profile, leveled_up = award_xp(profile, result.xp_earned)
        new_badges = check_and_award(profile, {})
        self._save(profile)

        lc            = await build_learner_context(self.workspace_dir, profile, days=14)
        optimizations = self._optimizer.analyze_from_context(self.workspace_dir, profile, lc)
        reply = self._practice.format_test_result(test, result)
        if leveled_up:
            reply += f"\n\n**Level Up: {LEVEL_LABELS.get(profile.learner.skill_level)}!**"
        if new_badges:
            reply += f"\n\n{', '.join(new_badges)}"

        return MasteryResult(
            reply=reply, xp_earned=result.xp_earned,
            action_taken=f"Practice test: {test.scope}",
            badges_earned=new_badges, test_result=result, optimizations=optimizations,
        )

    # ── Status ─────────────────────────────────────────────────────────────────

    def get_status(self) -> str:
        """Return a rich status summary."""
        profile = load_profile(self.workspace_dir)
        if not profile:
            return "No Sarthak Space initialized in this workspace."
        lr         = profile.learner
        level_name = LEVEL_LABELS.get(lr.skill_level, lr.skill_level.value)
        xp_to_next = max(0, XP_THRESHOLDS.get(lr.skill_level, 9999) - lr.xp)
        badges_str   = f" | {len(lr.badges)} badges" if lr.badges else ""
        projects_str = f" | {len(lr.completed_projects)} projects" if lr.completed_projects else ""
        goal_str     = f"\n**Goal**: {lr.goal}" if lr.goal else ""
        struggling   = f" | **Struggling**: {', '.join(lr.struggling_concepts[:3])}" if lr.struggling_concepts else ""
        return (
            f"**Space**: {profile.domain}{goal_str}\n"
            f"**Level**: {level_name} | **XP**: {lr.xp} (+{xp_to_next} to next)\n"
            f"**Sessions**: {lr.total_sessions} | **Streak**: {lr.streak_days}"
            f"{badges_str}{projects_str}\n"
            f"**Mastered**: {len(lr.mastered_concepts)} concepts{struggling}\n"
            f"**Active tools**: {', '.join(profile.expert_tools_installed[:6]) or 'none'}"
        )
