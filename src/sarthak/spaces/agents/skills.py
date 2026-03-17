"""
spaces/agents/skills.py — SpacesSkills

ONE class. All LLM-calling capabilities of the Spaces subsystem.
Each method is a skill: one system prompt (from a .md file) + one LLM call.

Why one class instead of 14 agent classes:
  - Each method is a single LLM call — that's a skill, not an agent
  - An agent implies autonomy, tool use, multi-step reasoning
  - These are pure transform functions: data in → structured data out
  - One class = one import, one place to find everything, easier to test

System prompts live in data/agents/spaces/*.md (loaded + cached by _load_system).
Pure logic (SRS, badges, env scan) lives in spaces/tools/*.py.

Public methods (all async, all return dict or str):
    onboard(background, goal, domain)              → dict
    plan_curriculum(ctx, available, review_due)    → dict
    explain_math(concept, level, background)       → dict
    build_task(concept, ctx, math_context)         → LearningTask
    scaffold_project(project_info, ctx, ws_dir)    → (ProjectRecord, list[str])
    generate_quicktest(concept, level, ...)        → dict
    evaluate_submission(task, submission)          → dict
    design_workspace(ctx)                          → dict
    recommend_environment(scan_data, ctx)          → dict
    render_engagement(content, background, xp)    → str
    analyse_workspace(ctx)                         → str  (Optimal_Learn.md content)
"""
from __future__ import annotations

import json
import uuid
from pathlib import Path

from sarthak.features.ai.agents._base import parse_json_response, run_llm
from sarthak.spaces.agents._common import _call_llm_json, _load_system, is_technical
from sarthak.spaces.models import LearningTask, ProjectRecord, SkillLevel, SpaceContext


class SpacesSkills:
    """
    All LLM skills for the Spaces subsystem.
    Stateless — instantiate once per session or share globally.
    """

    # ── Onboarding ─────────────────────────────────────────────────────────────

    async def onboard(self, background: str, goal: str, domain: str) -> dict:
        """Detect learner background and set personalisation flags."""
        prompt = (
            f"Domain they want to learn: {domain}\n"
            f"Their background: {background}\n"
            f"Their stated goal: {goal or 'not specified'}\n"
            "Analyze and return JSON."
        )
        return await _call_llm_json(
            _load_system("onboarding"), prompt,
            fallback={
                "background_category": "other", "is_technical": False,
                "inferred_goal": goal or "mastery", "recommended_start_level": "novice",
                "first_concept": "foundations", "learning_style_hint": "visual",
                "motivating_hook": f"You're about to unlock {domain}.",
                "welcome_message": f"Welcome! Let's start your {domain} journey.",
            },
            tag="onboarding", model_tier="balanced",
        )

    # ── Curriculum planning ────────────────────────────────────────────────────

    async def plan_curriculum(
        self,
        ctx: SpaceContext,
        available: list[str],
        review_due: list[str],
        activity_context: str = "",
    ) -> dict:
        """Select next concept using ZPD. Fast model — called every session."""
        p = ctx.profile.learner
        prompt = (
            f"Domain: {ctx.profile.domain}\n"
            f"Background: {p.background or 'not specified'}\n"
            f"Goal: {p.goal or 'mastery'}\n"
            f"Level: {p.skill_level.value}\n"
            f"Style: {p.preferred_style}\n"
            f"Mastered (last 6): {json.dumps(p.mastered_concepts[-6:])}\n"
            f"Struggling: {json.dumps(p.struggling_concepts)}\n"
            f"Available new: {json.dumps(available)}\n"
            f"Review due: {json.dumps(review_due)}\n"
            f"Total sessions: {p.total_sessions}\n"
        )
        if activity_context:
            prompt += f"\n{activity_context}\n"
        prompt += "Return JSON."
        return await _call_llm_json(
            _load_system("curriculum"), prompt,
            fallback={
                "next_concept": available[0] if available else "review basics",
                "why_now": "Continuing your learning path.",
                "review_concept": review_due[0] if review_due else "",
                "session_type": "new_concept", "suggest_project": False,
            },
            tag="curriculum", model_tier="fast",
        )

    # ── Math explanation ───────────────────────────────────────────────────────

    async def explain_math(
        self,
        concept: str,
        level: SkillLevel,
        background: str = "",
        is_technical_flag: bool = True,
    ) -> dict:
        """Explain mathematical foundations with intuition → derivation → code."""
        prompt = (
            f"Concept: {concept}\n"
            f"Learner level: {level.value}\n"
            f"Learner background: {background or 'technical professional'}\n"
            f"Technical background: {is_technical_flag}\n"
            "Return mathematical explanation as JSON."
        )
        return await _call_llm_json(
            _load_system("math"), prompt,
            fallback={
                "intuition": f"Core idea of {concept}", "key_formulas": [],
                "derivation_steps": [],
                "numpy_equivalent": f"# {concept}\n# See documentation",
                "common_misconceptions": [],
            },
            tag="math", model_tier="powerful",
        )

    # ── Task building ──────────────────────────────────────────────────────────

    _XP_MAP = {
        SkillLevel.NOVICE: 8, SkillLevel.BEGINNER: 12,
        SkillLevel.INTERMEDIATE: 18, SkillLevel.ADVANCED: 25, SkillLevel.EXPERT: 35,
    }

    async def build_task(
        self, concept: str, ctx: SpaceContext, math_context: dict
    ) -> LearningTask:
        """Build a hands-on task with real-world hook, hints, and starter code."""
        p = ctx.profile.learner
        technical = is_technical(p.background or "")
        prompt = (
            f"Concept: {concept}\nDomain: {ctx.profile.domain}\n"
            f"Level: {p.skill_level.value}\n"
            f"Background: {p.background or 'technical professional'}\n"
            f"Technical: {technical}\nGoal: {p.goal or 'mastery'}\n"
            f"Math formulas: {json.dumps(math_context.get('key_formulas', [])[:2])}\n"
            "Build hands-on task. Return JSON."
        )
        data = await _call_llm_json(
            _load_system("task-builder"), prompt,
            fallback={
                "title": f"Practice: {concept}",
                "instructions": f"Implement **{concept}** from scratch.",
                "expected_outcome": "Working implementation with 2 test cases",
            },
            tag="task_builder", model_tier="balanced",
        )
        return LearningTask(
            task_id=str(uuid.uuid4())[:8], title=data.get("title", concept),
            concept=concept, difficulty=p.skill_level, task_type="implement",
            instructions=data.get("instructions", ""),
            expected_outcome=data.get("expected_outcome", ""),
            hints=data.get("hints", []), resources=data.get("resources", []),
            math_foundation=data.get("math_foundation", ""),
            real_world_hook=data.get("real_world_hook", ""),
            starter_code=data.get("starter_code", ""),
            no_code_version=data.get("no_code_version", ""),
            bonus_challenge=data.get("bonus_challenge", ""),
            estimated_minutes=int(data.get("estimated_minutes", 30)),
            xp_reward=self._XP_MAP.get(p.skill_level, 10),
        )

    # ── Project scaffolding ────────────────────────────────────────────────────

    async def scaffold_project(
        self, project_info: dict, ctx: SpaceContext, workspace_dir: Path
    ) -> tuple[ProjectRecord, list[str]]:
        """Generate and materialise a full project directory structure."""
        from sarthak.spaces.tools.workspace_apply import apply_workspace_design
        p = ctx.profile.learner
        prompt = (
            f"Project: {project_info['title']}\nDescription: {project_info['description']}\n"
            f"Domain: {ctx.profile.domain}\nLevel: {p.skill_level.value}\n"
            f"Background: {p.background or 'technical'}\n"
            f"Mastered concepts: {json.dumps(p.mastered_concepts[-8:])}\n"
            "Design the complete project. Return JSON."
        )
        raw  = await run_llm(_load_system("project"), prompt, tier="powerful")
        data = parse_json_response(raw)

        # Materialise directory structure via the workspace_apply tool
        design = {
            "directories": list({
                str(Path(k).parent) for k in data.get("directory_structure", {})
                if str(Path(k).parent) != "."
            }),
            "starter_files": data.get("directory_structure", {}),
            "readme_files": {},
        }
        project_dir = workspace_dir / "projects" / project_info["id"]
        project_dir.mkdir(parents=True, exist_ok=True)
        created = apply_workspace_design(design, project_dir)

        roadmap_path = project_dir / "ROADMAP.md"
        lines = [
            f"# {data.get('title', project_info['title'])} — Project Roadmap\n",
            f"**{data.get('elevator_pitch', '')}**\n",
            f"Run: `{data.get('demo_command', 'python main.py')}`\n",
        ]
        for i, ms in enumerate(data.get("milestones", []), 1):
            lines += [f"## Milestone {i}: {ms.get('title', '')}\n", f"{ms.get('instructions', '')}\n"]
        roadmap_path.write_text("\n".join(lines), encoding="utf-8")
        created.append(str(roadmap_path))

        return ProjectRecord(
            project_id=project_info["id"],
            title=data.get("title", project_info["title"]),
            domain=ctx.profile.domain,
            concepts_applied=data.get("concepts_reinforced", []),
            repo_path=str(project_dir),
            description=data.get("elevator_pitch", project_info.get("description", "")),
        ), created

    # ── QuickTest generation ───────────────────────────────────────────────────

    async def generate_quicktest(
        self, concept: str, level: SkillLevel,
        background: str = "", is_technical_flag: bool = True,
        user_prompt: str = "", notes_context: str = "",
    ) -> dict:
        """Generate a focused 5-minute micro-challenge."""
        challenge_type = "code_snippet" if is_technical_flag else "explain_like_5"
        prompt = (
            f"Concept: {concept}\nLevel: {level.value}\n"
            f"Background: {background or 'technical'}\n"
            f"Preferred type: {challenge_type}\n"
            f"User request: {user_prompt or 'none'}\n"
            "Generate 5-minute micro-task. Return JSON."
        )
        if notes_context:
            prompt += f"\nNotes context:\n{notes_context}\n"
        return await _call_llm_json(
            _load_system("quicktest"), prompt,
            fallback={
                "type": challenge_type, "title": f"Quick: {concept}",
                "challenge": f"In 5 minutes, implement the core idea of **{concept}** in Python.",
                "success_criteria": "Code runs without errors.", "xp_reward": 5,
            },
            tag="quicktest", model_tier="fast",
        )

    # ── Assessment ─────────────────────────────────────────────────────────────

    async def evaluate_submission(self, task: LearningTask, submission: str) -> dict:
        """Evaluate a learner submission — honest, specific, detects novel approaches."""
        prompt = (
            f"Task: {task.title}\nConcept: {task.concept}\n"
            f"Expected: {task.expected_outcome}\nMath foundation: {task.math_foundation}\n"
            f"Submission:\n{submission}\nEvaluate. Return JSON."
        )
        return await _call_llm_json(
            _load_system("assessment"), prompt,
            fallback={
                "mastered": False, "score": 0, "feedback": "Assessment failed.",
                "gaps": [], "strengths": [], "novel_approach": False,
                "concept_mastered": "", "concept_struggling": "",
            },
            tag="assessment", model_tier="balanced",
        )

    # ── Workspace design ───────────────────────────────────────────────────────

    async def design_workspace(self, ctx: SpaceContext) -> dict:
        """Design expert-level workspace structure (non-destructive)."""
        from sarthak.spaces.agents._common import detect_platform
        ws = Path(ctx.workspace_dir)
        existing = [p.name for p in ws.iterdir() if p.is_dir()] if ws.exists() else []
        prompt = (
            f"Domain: {ctx.profile.domain}\nLevel: {ctx.profile.learner.skill_level.value}\n"
            f"Platform: {detect_platform()}\nExisting dirs: {existing}\n"
            "Design expert workspace. Return JSON."
        )
        return await _call_llm_json(
            _load_system("workspace-designer"), prompt,
            fallback={"directories": [], "readme_files": {}, "starter_files": {}, "rationale": "LLM unavailable."},
            tag="workspace_designer", model_tier="fast",
        )

    # ── Environment recommendations ────────────────────────────────────────────

    async def recommend_environment(self, scan_data: dict, ctx: SpaceContext) -> dict:
        """
        Given scan_data from env_scan.scan_environment(), generate LLM recommendations.
        The scan is pure logic; the recommendations need LLM judgment.
        """
        prompt = (
            f"Domain: {ctx.profile.domain}\nLevel: {ctx.profile.learner.skill_level.value}\n"
            f"Platform: {scan_data['platform']}\n"
            f"Installed: {json.dumps(scan_data['installed'])}\n"
            f"Missing from recommended: {json.dumps(scan_data['missing'][:12])}\n"
            "Return JSON with prioritized missing tools and install commands."
        )
        result = await _call_llm_json(
            _load_system("environment"), prompt,
            fallback={
                "missing": [
                    {"name": n, "priority": "medium", "category": "core",
                     "install_linux": f"uv add {n}", "install_mac": f"uv add {n}",
                     "install_windows": f"uv add {n}", "why": ""}
                    for n in scan_data["missing"][:6]
                ],
                "config_snippets": {},
                "summary": f"Found {len(scan_data['installed'])} tools.",
            },
            tag="environment", model_tier="fast",
        )
        # Merge raw scan data back in
        result["installed"] = scan_data["installed"]
        result["platform"]  = scan_data["platform"]
        return result

    # ── Engagement rendering ───────────────────────────────────────────────────

    async def render_engagement(
        self, content: dict, learner_background: str,
        xp_earned: int, novel_approach: bool = False, is_technical_flag: bool = True,
    ) -> str:
        """Transform structured content into engaging Markdown for the learner."""
        prompt = (
            f"Learner background: {learner_background or 'technical professional'}\n"
            f"Technical: {is_technical_flag}\nXP earned: {xp_earned}\n"
            f"Novel approach: {novel_approach}\n"
            f"Content:\n{json.dumps(content, indent=2)}\n\n"
            "Create the engaging Markdown learning message."
        )
        try:
            return await run_llm(_load_system("engagement"), prompt, tier="balanced")
        except Exception:
            return f"# Learning Session\n\n{json.dumps(content, indent=2)}\n\n*+{xp_earned} XP*"

    # ── Workspace analysis ─────────────────────────────────────────────────────

    async def analyse_workspace(self, ctx: SpaceContext) -> str:
        """
        Produce Optimal_Learn.md content from real learner signals.
        This skill is kept as a dedicated method because it is genuinely complex:
        it gathers data from multiple sources in parallel before the single LLM call.
        """
        from sarthak.spaces.agents._workspace_analyser import WorkspaceAnalyserAgent
        return await WorkspaceAnalyserAgent().analyse(ctx)
