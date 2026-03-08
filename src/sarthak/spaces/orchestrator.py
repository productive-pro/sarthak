"""
Sarthak Spaces — Main Orchestrator.

Coordinates sub-agents to deliver mastery sessions.
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
from sarthak.spaces.domains import get_available_projects, get_next_concepts
from sarthak.spaces.learner_context import (
    build_learner_context,
    learner_context_for_prompt,
)
from sarthak.spaces.models import (
    LEVEL_LABELS,
    XP_THRESHOLDS,
    LearningTask,
    MasteryResult,
    SelfReport,
    SkillLevel,
    SpaceContext,
    SpaceProfile,
    SpaceType,
    award_xp,
    update_streak,
)
from sarthak.spaces.optimizer import SignalOptimizer
from sarthak.spaces.practice import PracticeEngine
from sarthak.spaces.roadmap_tracker import record_session_to_roadmap
from sarthak.spaces.session_tracker import SpaceSessionTracker, save_session
from sarthak.spaces.store import init_space_profile, load_profile, save_profile
from sarthak.spaces.sub_agents import (
    AssessmentAgent,
    BadgeAgent,
    CurriculumAgent,
    EngagementAgent,
    EnvironmentAgent,
    ExternalToolsAgent,
    MathAgent,
    OnboardingAgent,
    ProjectAgent,
    SpacedRepetitionAgent,
    TaskBuilderAgent,
    WorkspaceAgent,
    WorkspaceAnalyserAgent,
    detect_platform,
    is_technical,
)

log = get_logger(__name__)


class SpacesOrchestrator:
    """
    Entry point for all Sarthak Spaces interactions.
    Stateless per call — all state lives in SpaceProfile on disk.
    """

    def __init__(self, workspace_dir: str | Path):
        self.workspace_dir = Path(workspace_dir).resolve()
        # Instantiate agents once — they're all stateless
        self._env           = EnvironmentAgent()
        self._onboarding    = OnboardingAgent()
        self._curriculum    = CurriculumAgent()
        self._math          = MathAgent()
        self._task          = TaskBuilderAgent()
        self._project       = ProjectAgent()
        self._engage        = EngagementAgent()
        self._workspace     = WorkspaceAgent()
        self._assessor      = AssessmentAgent()
        self._srs           = SpacedRepetitionAgent()
        self._badges        = BadgeAgent()
        self._ws_analyser   = WorkspaceAnalyserAgent()
        self._ext_tools     = ExternalToolsAgent()
        self._practice      = PracticeEngine()
        self._optimizer     = SignalOptimizer()
        # Active session tracker (one at a time per orchestrator instance)
        self._tracker: SpaceSessionTracker | None = None

    # ── Profile helpers ────────────────────────────────────────────────────────

    def _load_or_init(self, space_type: SpaceType | None = None) -> SpaceProfile:
        profile = load_profile(self.workspace_dir)
        return profile or init_space_profile(
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

    # ── Onboarding (first session) ─────────────────────────────────────────────

    async def _maybe_onboard(self, profile: SpaceProfile) -> SpaceProfile:
        """On first session, run onboarding to personalize the profile."""
        if profile.learner.total_sessions > 0:
            return profile
        if not profile.learner.background:
            return profile  # Will be set by caller via update_learner

        analysis = await self._onboarding.analyze(
            background=profile.learner.background,
            goal=profile.learner.goal,
            domain=profile.domain,
        )

        # Apply onboarding results
        profile.learner.is_technical = analysis.get("is_technical", True)
        if not profile.learner.goal and analysis.get("inferred_goal"):
            profile.learner.goal = analysis["inferred_goal"]
        if analysis.get("learning_style_hint"):
            profile.learner.preferred_style = analysis["learning_style_hint"]

        # Respect recommended start level
        level_str = analysis.get("recommended_start_level", "novice")
        try:
            profile.learner.skill_level = SkillLevel(level_str)
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
        profile = self._load_or_init(space_type)
        profile = await self._maybe_onboard(profile)
        profile = update_streak(profile)
        ctx = self._build_ctx(profile)

        # Pull real learner context (notes, tests, sessions)
        lc = await build_learner_context(self.workspace_dir, profile, days=14)

        workspace_changes: list[str] = []
        tools_added: list[str] = []

        # ── Step 1: Workspace setup (first run or explicit) ────────────────────
        if reshape_workspace or not profile.expert_tools_installed:
            ws_design, env_scan = await asyncio.gather(
                self._workspace.design(ctx),
                self._env.scan(ctx),
            )
            workspace_changes = await self._workspace.apply(ws_design, self.workspace_dir)
            profile.expert_tools_installed = env_scan.get("installed", [])
            tools_added = [t["name"] for t in env_scan.get("missing", [])]
            self._save(profile)
            ctx = self._build_ctx(profile)

        # Inject real learner context into curriculum planning
        activity_prompt = learner_context_for_prompt(lc)

        # ── Step 2: Spaced repetition — use evidence-based queue ───────────────
        review_due = lc.srs_due_by_evidence[:2] or self._srs.get_due_reviews(profile)

        # ── Step 3: Curriculum — what to learn next? ───────────────────────────
        available = get_next_concepts(
            profile.space_type,
            profile.learner.mastered_concepts,
            profile.learner.skill_level,
        )
        curriculum = await self._curriculum.plan(ctx, available, review_due, activity_context=activity_prompt)
        next_concept = (
            concept_override
            or curriculum.get("next_concept")
            or (available[0] if available else "Python basics")
        )
        session_type = curriculum.get("session_type", "new_concept")
        suggest_project = curriculum.get("suggest_project", False)

        # ── Start session tracker if requested ─────────────────────────────────
        if track_session:
            self._tracker = SpaceSessionTracker(
                self.workspace_dir, next_concept,
                planned_minutes=planned_minutes,
            )
            await self._tracker.start()

        # ── Step 4: Math + Task in parallel ────────────────────────────────────
        math_data, task = await asyncio.gather(
            self._math.explain(
                next_concept,
                profile.learner.skill_level,
                profile.learner.background,
                is_technical=profile.learner.is_technical,
            ),
            self._task.build(next_concept, ctx, {}),
        )
        task.math_foundation = math_data.get("numpy_equivalent", task.math_foundation)

        # ── Step 5: Build engagement content ───────────────────────────────────
        content = {
            "concept": next_concept,
            "session_type": session_type,
            "why_now": curriculum.get("why_now", ""),
            "review_concept": curriculum.get("review_concept", ""),
            "intuition": math_data.get("intuition", ""),
            "key_formulas": math_data.get("key_formulas", []),
            "derivation_steps": math_data.get("derivation_steps", []),
            "numpy_equivalent": math_data.get("numpy_equivalent", ""),
            "common_misconceptions": math_data.get("common_misconceptions", []),
            "task": {
                "title": task.title,
                "real_world_hook": task.real_world_hook,
                "instructions": task.instructions,
                "starter_code": task.starter_code,
                "no_code_version": task.no_code_version,
                "expected_outcome": task.expected_outcome,
                "hints": task.hints,
                "bonus_challenge": task.bonus_challenge,
                "estimated_minutes": task.estimated_minutes,
            },
            "learning_path": curriculum.get("learning_path", []),
            "tools_to_use": profile.expert_tools_installed[:3],
            "streak": profile.learner.streak_days,
            "xp": profile.learner.xp,
            "level": LEVEL_LABELS.get(profile.learner.skill_level, ""),
            "suggest_project": suggest_project,
        }

        # ── Step 6: Render engaging reply ──────────────────────────────────────
        xp = task.xp_reward
        profile, leveled_up = award_xp(profile, xp)
        if leveled_up:
            content["level_up"] = LEVEL_LABELS.get(profile.learner.skill_level, "")

        reply = await self._engage.render(
            content,
            profile.learner.background,
            xp,
            novel_approach=False,
            is_technical=profile.learner.is_technical,
        )

        # ── Step 7: Badges ─────────────────────────────────────────────────────
        profile.learner.total_sessions += 1
        new_badges = self._badges.check_and_award(profile, {"novel_approach": False})
        if new_badges:
            reply += f"\n\n---\n**Badge{'s' if len(new_badges) > 1 else ''}**: {', '.join(new_badges)}"

        # ── Steps 8+9: Workspace analysis + roadmap record + optimizer — parallel
        ctx = self._build_ctx(profile)
        ext_tools = self._ext_tools.detect_from_workspace(self.workspace_dir)

        async def _analyse() -> None:
            try:
                optimal_content = await self._ws_analyser.analyse(ctx)
                self._ws_analyser.write_optimal_learn(self.workspace_dir, optimal_content)
            except Exception as exc:
                log.warning("workspace_analyser_skipped", error=str(exc))

        async def _record() -> None:
            try:
                await asyncio.to_thread(
                    record_session_to_roadmap,
                    self.workspace_dir, profile,
                    concept=next_concept, xp_earned=xp,
                    tools_used=profile.expert_tools_installed[:5],
                    external_tools=ext_tools,
                    mastered=False,
                )
            except Exception as exc:
                log.warning("roadmap_record_skipped", error=str(exc))

        await asyncio.gather(_analyse(), _record())

        # Store activity context on result for callers (e.g. recommendation agents)
        content["activity_context"] = activity_prompt

        self._save(profile)

        return MasteryResult(
            reply=reply,
            next_task=task,
            workspace_changes=workspace_changes,
            tools_added=tools_added,
            xp_earned=xp,
            action_taken=f"Taught: {next_concept}",
            badges_earned=new_badges,
            review_due=review_due,
        )

    # ── QuickTest: 5-minute micro-session ─────────────────────────────────────

    async def quicktest(self) -> MasteryResult:
        """5-minute QuickTest. Perfect for busy learners."""
        profile = self._load_or_init()
        available = get_next_concepts(
            profile.space_type,
            profile.learner.mastered_concepts,
            profile.learner.skill_level,
        )
        concept = available[0] if available else "Python basics"

        from sarthak.spaces.roadmap.quicktest import create_quicktest
        qt, micro = await create_quicktest(
            self.workspace_dir,
            input_mode="random",
            prompt="",
            concept_label=concept,
            level=profile.learner.skill_level,
            background=profile.learner.background,
            is_technical=profile.learner.is_technical,
            return_micro=True,
        )

        xp = micro.get("xp_reward", 5)
        profile, leveled_up = award_xp(profile, xp)
        profile.learner.total_sessions += 1
        profile = update_streak(profile)
        self._save(profile)

        reply = (
            f"{qt.response_md}\n\n"
            f"*streak {profile.learner.streak_days}*"
        )
        if leveled_up:
            reply += f"\n\n**Level Up: {LEVEL_LABELS.get(profile.learner.skill_level)}!**"

        return MasteryResult(reply=reply, xp_earned=xp, action_taken=f"QuickTest: {concept}")

    # ── Evaluate submitted work ────────────────────────────────────────────────

    async def evaluate(
        self,
        task_concept: str,
        task_title: str,
        submission: str,
    ) -> MasteryResult:
        """Evaluate a learner's submission and update mastery state."""
        profile = self._load_or_init()
        task = LearningTask(
            task_id="eval",
            title=task_title,
            concept=task_concept,
            difficulty=profile.learner.skill_level,
            task_type="submission",
            instructions="",
            expected_outcome="",
        )
        assessment = await self._assessor.evaluate(task, submission)

        mastered = assessment.get("concept_mastered", "")
        struggling = assessment.get("concept_struggling", "")
        novel = assessment.get("novel_approach", False)

        if mastered and mastered not in profile.learner.mastered_concepts:
            profile.learner.mastered_concepts.append(mastered)
            profile = self._srs.update_after_review(profile, mastered, recalled=True)
            if mastered in profile.learner.struggling_concepts:
                profile.learner.struggling_concepts.remove(mastered)

        if struggling and struggling not in profile.learner.struggling_concepts:
            profile.learner.struggling_concepts.append(struggling)

        xp = max(5, int(assessment.get("score", 50) * 0.2))
        profile, leveled_up = award_xp(profile, xp)
        new_badges = self._badges.check_and_award(profile, {"novel_approach": novel})

        # Record evaluation to roadmap
        ext_tools = self._ext_tools.detect_from_workspace(self.workspace_dir)
        try:
            record_session_to_roadmap(
                self.workspace_dir, profile,
                concept=task_concept, xp_earned=xp,
                tools_used=profile.expert_tools_installed[:5],
                external_tools=ext_tools,
                mastered=bool(mastered),
            )
        except Exception as exc:
            log.warning("roadmap_record_skipped", error=str(exc))

        content = {
            "score": assessment.get("score"),
            "feedback": assessment.get("feedback", ""),
            "strengths": assessment.get("strengths", []),
            "gaps": assessment.get("gaps", []),
            "next_step": assessment.get("next_step", ""),
            "novel_approach": novel,
            "novel_approach_description": assessment.get("novel_approach_description", ""),
        }
        if leveled_up:
            content["level_up"] = LEVEL_LABELS.get(profile.learner.skill_level, "")

        reply = await self._engage.render(
            content,
            profile.learner.background,
            xp,
            novel_approach=novel,
            is_technical=profile.learner.is_technical,
        )

        if new_badges:
            reply += f"\n\n---\n**Badge earned**: {', '.join(new_badges)}"

        profile.learner.total_sessions += 1
        self._save(profile)

        return MasteryResult(
            reply=reply,
            xp_earned=xp,
            concept_mastered=mastered,
            concept_struggling=struggling,
            action_taken=f"Evaluated: {task_concept}",
            badges_earned=new_badges,
        )

    # ── Start a real project ───────────────────────────────────────────────────

    async def start_project(
        self,
        project_id: str | None = None,
    ) -> MasteryResult:
        """Scaffold a real end-to-end project for the learner."""
        profile = self._load_or_init()
        ctx = self._build_ctx(profile)

        # Find appropriate project
        completed_ids = [p.project_id for p in profile.learner.completed_projects]
        available_projects = get_available_projects(
            profile.space_type, profile.learner.skill_level, completed_ids
        )

        if not available_projects:
            return MasteryResult(
                reply="# 🏗️ No Projects Available\n\nComplete more concepts to unlock projects!",
                action_taken="project_unavailable",
            )

        project_info = next(
            (p for p in available_projects if p["id"] == project_id),
            available_projects[0],
        )

        record, created = await self._project.scaffold(
            project_info, ctx, self.workspace_dir
        )

        # 50 XP bonus for starting a project
        xp = 50
        profile, leveled_up = award_xp(profile, xp)
        new_badges = self._badges.check_and_award(profile, {})
        self._save(profile)

        reply = (
            f"# Project Unlocked: {record.title}\n\n"
            f"**{record.description}**\n\n"
            f"Your project is scaffolded at:\n`{record.repo_path}`\n\n"
            f"Open `ROADMAP.md` for your step-by-step guide.\n\n"
            f"---\n*+{xp} XP for starting a real project!*"
        )
        if leveled_up:
            reply += f"\n\n**Level Up: {LEVEL_LABELS.get(profile.learner.skill_level)}!**"

        return MasteryResult(
            reply=reply,
            workspace_changes=created,
            xp_earned=xp,
            action_taken=f"Started project: {record.title}",
            badges_earned=new_badges,
            project_scaffolded=record.repo_path,
        )

    # ── Environment setup only ─────────────────────────────────────────────────

    async def setup_environment(
        self,
        space_type: SpaceType | None = None,
    ) -> MasteryResult:
        """Scan environment + reshape workspace. No teaching."""
        profile = self._load_or_init(space_type)
        ctx = self._build_ctx(profile)

        ws_design, env_scan = await asyncio.gather(
            self._workspace.design(ctx),
            self._env.scan(ctx),
        )
        workspace_changes = await self._workspace.apply(ws_design, self.workspace_dir)
        profile.expert_tools_installed = env_scan.get("installed", [])
        self._save(profile)

        platform = env_scan.get("platform", "linux")
        missing = env_scan.get("missing", [])
        install_key = "install_windows" if platform == "windows" else \
                      "install_mac" if platform == "darwin" else "install_linux"

        tool_lines = "\n".join(
            f"- **{t['name']}** ({t.get('priority', 'medium')} priority, "
            f"{t.get('category', 'core')}): {t.get('why', '')}  \n"
            f"  `{t.get(install_key) or t.get('install_linux', '')}`"
            for t in missing[:8]
        )

        reply = (
            f"# Expert Environment Setup\n\n"
            f"**Workspace**: `{self.workspace_dir}` | **Platform**: {platform}\n\n"
            f"{env_scan.get('summary', '')}\n\n"
            f"## Installed ({len(env_scan.get('installed', []))} tools)\n"
            f"`{', '.join(env_scan.get('installed', ['none']))}`\n\n"
            f"## Recommended Additions\n{tool_lines or 'Expert environment complete!'}\n\n"
            f"## Workspace Reshaped\n{ws_design.get('rationale', '')}\n\n"
            f"*{len(workspace_changes)} files/directories created.*"
        )

        return MasteryResult(
            reply=reply,
            workspace_changes=workspace_changes,
            tools_added=[t["name"] for t in missing],
            action_taken="Environment setup",
        )

    # ── Profile management ─────────────────────────────────────────────────────

    def update_learner(self, **kwargs) -> SpaceProfile:
        """Update learner profile fields directly."""
        profile = self._load_or_init()
        for key, val in kwargs.items():
            if hasattr(profile.learner, key):
                setattr(profile.learner, key, val)
        # Auto-detect is_technical if background changed
        if "background" in kwargs:
            profile.learner.is_technical = is_technical(kwargs["background"])
        self._save(profile)
        return profile

    # ── Session end + optimization ───────────────────────────────────────────────────

    async def end_session(self, report: SelfReport) -> MasteryResult:
        """End the current tracked session, collect signals, run optimizer."""

        if not self._tracker:
            return MasteryResult(
                reply="No active tracked session found.",
                action_taken="end_session_noop",
            )

        session = await self._tracker.end(report)
        self._tracker = None
        save_session(self.workspace_dir, session)

        profile = self._load_or_init()
        depth   = session.signals.depth_score
        xp = max(5, int(depth * 30)) + (10 if report.task_completed else 0)
        profile, leveled_up = award_xp(profile, xp)

        # Feed self-report into SRS
        for concept in report.stuck_on:
            if concept and concept not in profile.learner.struggling_concepts:
                profile.learner.struggling_concepts.append(concept)
        if report.understanding_rating >= 4:
            if session.concept not in profile.learner.mastered_concepts:
                profile.learner.mastered_concepts.append(session.concept)
            profile = self._srs.update_after_review(profile, session.concept, recalled=True)
        elif report.understanding_rating <= 2:
            profile = self._srs.update_after_review(profile, session.concept, recalled=False)

        new_badges = self._badges.check_and_award(profile, {})
        self._save(profile)

        lc = await build_learner_context(self.workspace_dir, profile, days=14)
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
            reply="\n".join(lines),
            xp_earned=xp,
            action_taken=f"Session ended: {session.concept}",
            badges_earned=new_badges,
            optimizations=optimizations,
        )

    # ── Practice tests ─────────────────────────────────────────────────────────

    async def run_practice(
        self,
        test_type: str = "concept",
        scope: str = "",
        source: str = "llm",
        source_prompt: str = "",
        n_questions: int | None = None,
        seconds_per_question: int = 120,
        interactive: bool = False,
    ) -> MasteryResult:
        """Generate and run a timed practice test."""
        import threading
        import time as _t

        profile = self._load_or_init()
        ctx     = self._build_ctx(profile)

        test = await self._practice.create_test(
            ctx,
            test_type=test_type,
            scope=scope,
            source=source,
            source_prompt=source_prompt,
            seconds_per_question=seconds_per_question,
            n_questions=n_questions,
        )

        if not interactive:
            lines = [
                f"# 📝 Practice Test — {test.scope}",
                f"**{len(test.questions)} questions** | "
                f"**{test.total_time_seconds // 60} min total** | "
                f"**{seconds_per_question}s per question**", "",
            ]
            for i, q in enumerate(test.questions, 1):
                lines.append(f"**Q{i}. [{q.question_type.upper()}]** {q.question}")
                for opt in q.options:
                    lines.append(f"  - {opt}")
                lines.append("")
            return MasteryResult(
                reply="\n".join(lines),
                action_taken=f"Practice test generated: {test.scope}",
            )

        # ── Interactive CLI runner with per-question timer ───────────────────────────
        answers:    dict[str, str] = {}
        time_taken: dict[str, int] = {}

        print(f"\n📝  Practice Test: {test.scope}")
        print(f"{len(test.questions)} questions | {seconds_per_question}s per question")
        print("─" * 50)

        for i, q in enumerate(test.questions, 1):
            print(f"\nQ{i}/{len(test.questions)} [{q.question_type.upper()}] "
                  f"({q.time_limit_seconds}s) — {q.concept}")
            print(q.question)
            for opt in q.options:
                print(f"  {opt}")

            start_t = _t.time()
            done_evt = threading.Event()

            def _countdown(limit: int, done: threading.Event) -> None:
                for remaining in range(limit, 0, -1):
                    if done.is_set():
                        return
                    print(f"  ⏱ {remaining}s  ", end="\r", flush=True)
                    _t.sleep(1)
                if not done.is_set():
                    print("\n  ⏰ Time's up!   ")

            timer = threading.Thread(target=_countdown,
                                     args=(q.time_limit_seconds, done_evt), daemon=True)
            timer.start()
            try:
                answer = (await asyncio.to_thread(input, "Your answer: ")).strip()
            except EOFError:
                answer = ""
            finally:
                done_evt.set()

            elapsed = int(_t.time() - start_t)
            answers[q.question_id]    = answer
            time_taken[q.question_id] = min(elapsed, q.time_limit_seconds)

        print("\n📊 Grading…")
        result = await self._practice.grade_test(test, answers, time_taken)

        # Update SRS + profile
        for concept in result.strong_concepts:
            if concept not in profile.learner.mastered_concepts:
                profile.learner.mastered_concepts.append(concept)
            profile = self._srs.update_after_review(profile, concept, recalled=True)
        for concept in result.weak_concepts:
            if concept not in profile.learner.struggling_concepts:
                profile.learner.struggling_concepts.append(concept)
            profile = self._srs.update_after_review(profile, concept, recalled=False)

        profile, leveled_up = award_xp(profile, result.xp_earned)
        new_badges = self._badges.check_and_award(profile, {})
        self._save(profile)

        lc = await build_learner_context(self.workspace_dir, profile, days=14)
        optimizations = self._optimizer.analyze_from_context(self.workspace_dir, profile, lc)

        reply = self._practice.format_test_result(test, result)
        if leveled_up:
            reply += f"\n\n**Level Up: {LEVEL_LABELS.get(profile.learner.skill_level)}!**"
        if new_badges:
            reply += f"\n\n{', '.join(new_badges)}"

        return MasteryResult(
            reply=reply,
            xp_earned=result.xp_earned,
            action_taken=f"Practice test: {test.scope}",
            badges_earned=new_badges,
            test_result=result,
            optimizations=optimizations,
        )

    def get_status(self) -> str:
        """Return a rich status summary."""
        profile = load_profile(self.workspace_dir)
        if not profile:
            return "No Sarthak Space initialized in this workspace."
        lr = profile.learner
        level_name = LEVEL_LABELS.get(lr.skill_level, lr.skill_level.value)
        threshold = XP_THRESHOLDS.get(lr.skill_level, 9999)
        xp_to_next = max(0, threshold - lr.xp)
        projects = len(lr.completed_projects)
        badges_str = f" | {len(lr.badges)} badges" if lr.badges else ""
        projects_str = f" | {projects} projects" if projects else ""
        goal_str = f"\n**Goal**: {lr.goal}" if lr.goal else ""
        return (
            f"**Space**: {profile.domain}{goal_str}\n"
            f"**Level**: {level_name} | **XP**: {lr.xp} (+{xp_to_next} to next)\n"
            f"**Sessions**: {lr.total_sessions} | **Streak**: {lr.streak_days}"
            f"{badges_str}{projects_str}\n"
            f"**Mastered**: {len(lr.mastered_concepts)} concepts"
            + (f" | **Struggling**: {', '.join(lr.struggling_concepts[:3])}"
               if lr.struggling_concepts else "")
            + f"\n**Active tools**: {', '.join(profile.expert_tools_installed[:6]) or 'none'}"
        )
