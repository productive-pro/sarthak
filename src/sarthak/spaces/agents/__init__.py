"""
spaces/agents/__init__.py

Public surface of the Spaces agent layer.

Architecture:
  SpacesSkills            — all LLM skills in one class (primary interface)
  spaces/tools/           — pure-logic tools: SRS, badges, env scan, workspace apply

Backward-compat class aliases live here so callers don't need to know the
internal layout. These are thin 1-line wrappers; prefer SpacesSkills for new code.
"""
from __future__ import annotations
from pathlib import Path

from sarthak.spaces.agents._common import detect_platform, is_technical
from sarthak.spaces.agents.skills import SpacesSkills
from sarthak.spaces.agents._workspace_analyser import WorkspaceAnalyserAgent
from sarthak.spaces.models import LearningTask, ProjectRecord, SkillLevel, SpaceContext, SpaceProfile
from sarthak.spaces.tools.srs import get_due_reviews, update_after_review
from sarthak.spaces.tools.badges import check_and_award

_skills = SpacesSkills()


# ── Assessment ────────────────────────────────────────────────────────────────

class AssessmentAgent:
    async def evaluate(self, task: LearningTask, submission: str) -> dict:
        return await _skills.evaluate_submission(task, submission)


class QuickTestAgent:
    async def generate(
        self, concept: str, level: SkillLevel,
        background: str = "", is_technical: bool = True,
        user_prompt: str = "", notes_context: str = "",
    ) -> dict:
        return await _skills.generate_quicktest(
            concept, level, background, is_technical, user_prompt, notes_context
        )


# ── Content & teaching ────────────────────────────────────────────────────────

class MathAgent:
    async def explain(
        self, concept: str, level: SkillLevel,
        background: str = "", is_technical_flag: bool = True,
    ) -> dict:
        return await _skills.explain_math(concept, level, background, is_technical_flag)


class TaskBuilderAgent:
    async def build(self, concept: str, ctx: SpaceContext, math_context: dict) -> LearningTask:
        return await _skills.build_task(concept, ctx, math_context)


class ProjectAgent:
    async def scaffold(
        self, project_info: dict, ctx: SpaceContext, workspace_dir: Path
    ) -> tuple[ProjectRecord, list[str]]:
        return await _skills.scaffold_project(project_info, ctx, workspace_dir)


class EngagementAgent:
    async def render(
        self, content: dict, learner_background: str, xp_earned: int,
        novel_approach: bool = False, is_technical: bool = True,
    ) -> str:
        return await _skills.render_engagement(
            content, learner_background, xp_earned, novel_approach, is_technical
        )


# ── Curriculum ────────────────────────────────────────────────────────────────

class OnboardingAgent:
    async def analyze(self, background: str, goal: str, domain: str) -> dict:
        return await _skills.onboard(background, goal, domain)


class CurriculumAgent:
    async def plan(
        self, ctx: SpaceContext, available: list[str],
        review_due: list[str], activity_context: str = "",
    ) -> dict:
        return await _skills.plan_curriculum(ctx, available, review_due, activity_context)


# ── Pure-logic tools (no LLM) ─────────────────────────────────────────────────

class SpacedRepetitionAgent:
    """SM-2 spaced repetition scheduling. Pure logic — no LLM."""
    def get_due_reviews(self, profile: SpaceProfile, max_reviews: int = 2) -> list[str]:
        return get_due_reviews(profile, max_reviews)

    def update_after_review(
        self, profile: SpaceProfile, concept: str, recalled: bool
    ) -> SpaceProfile:
        return update_after_review(profile, concept, recalled)


class BadgeAgent:
    """Achievement milestone logic. Pure logic — no LLM."""
    def check_and_award(self, profile: SpaceProfile, context: dict) -> list[str]:
        return check_and_award(profile, context)


# ── Workspace ─────────────────────────────────────────────────────────────────

class EnvironmentAgent:
    async def scan(self, ctx: SpaceContext) -> dict:
        from sarthak.spaces.tools.env_scan import scan_environment
        scan_data = scan_environment(ctx)
        return await _skills.recommend_environment(scan_data, ctx)


class WorkspaceAgent:
    async def design(self, ctx: SpaceContext) -> dict:
        return await _skills.design_workspace(ctx)

    async def apply(self, design: dict, workspace_dir: Path) -> list[str]:
        from sarthak.spaces.tools.workspace_apply import apply_workspace_design
        return apply_workspace_design(design, workspace_dir)


class ExternalToolsAgent:
    """Pure filesystem signal detection — no LLM."""
    def detect_from_workspace(self, workspace_dir: Path) -> list[str]:
        from sarthak.spaces.tools.external_tools import detect_external_tools
        return detect_external_tools(workspace_dir)

    def get_recommendations(self, domain: str) -> list[dict]:
        from sarthak.spaces.tools.external_tools import get_domain_recommendations
        return get_domain_recommendations(domain)

    def format_guidance(self, detected: list[str], domain: str) -> str:
        from sarthak.spaces.tools.external_tools import format_guidance
        return format_guidance(detected, domain)


__all__ = [
    # Primary interface
    "SpacesSkills",
    # Shared helpers
    "detect_platform", "is_technical",
    # Backward-compat classes
    "AssessmentAgent", "BadgeAgent", "CurriculumAgent", "EngagementAgent",
    "EnvironmentAgent", "ExternalToolsAgent", "MathAgent", "OnboardingAgent",
    "ProjectAgent", "QuickTestAgent", "SpacedRepetitionAgent", "TaskBuilderAgent",
    "WorkspaceAgent", "WorkspaceAnalyserAgent",
]
