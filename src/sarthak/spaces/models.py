"""
Sarthak Spaces — Core data models.
Single source of truth for all learning state.

New in this version:
  - SpaceSession / SessionSignals / SelfReport  — precision session tracking
  - TestQuestion / PracticeTest / TestResult    — timed practice engine
  - SessionOptimization                         — signal→recommendation output
"""
from __future__ import annotations

from datetime import datetime, timezone
from enum import Enum
from typing import Literal

from pydantic import BaseModel, Field


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


# ── Taxonomy ──────────────────────────────────────────────────────────────────

class SpaceType(str, Enum):
    DATA_SCIENCE    = "data_science"
    AI_ENGINEERING  = "ai_engineering"
    MEDICINE        = "medicine"
    EDUCATION       = "education"
    SOFTWARE_ENG    = "software_engineering"
    BUSINESS        = "business"
    RESEARCH        = "research"
    EXAM_PREP       = "exam_prep"
    CUSTOM          = "custom"


class SkillLevel(str, Enum):
    NOVICE       = "novice"
    BEGINNER     = "beginner"
    INTERMEDIATE = "intermediate"
    ADVANCED     = "advanced"
    EXPERT       = "expert"


# ── XP + Progression ─────────────────────────────────────────────────────────

LEVEL_ORDER: list["SkillLevel"] = [
    SkillLevel.NOVICE,
    SkillLevel.BEGINNER,
    SkillLevel.INTERMEDIATE,
    SkillLevel.ADVANCED,
    SkillLevel.EXPERT,
]

XP_THRESHOLDS: dict["SkillLevel", int] = {
    SkillLevel.NOVICE:       100,
    SkillLevel.BEGINNER:     300,
    SkillLevel.INTERMEDIATE: 700,
    SkillLevel.ADVANCED:     1500,
    SkillLevel.EXPERT:       9999,
}

LEVEL_LABELS: dict["SkillLevel", str] = {
    SkillLevel.NOVICE:       "Novice",
    SkillLevel.BEGINNER:     "Beginner",
    SkillLevel.INTERMEDIATE: "Intermediate",
    SkillLevel.ADVANCED:     "Advanced",
    SkillLevel.EXPERT:       "Expert",
}


# ── Mastery tracking ───────────────────────────────────────────────────────────

class ConceptMastery(BaseModel):
    concept: str
    mastered_at: str = Field(default_factory=_now)
    last_reviewed: str = Field(default_factory=_now)
    review_count: int = 1
    strength: float = 1.0          # 0=forgotten → 1=solid
    next_review_due: str = Field(default_factory=_now)


class ProjectRecord(BaseModel):
    project_id: str
    title: str
    domain: str
    concepts_applied: list[str] = Field(default_factory=list)
    created_at: str = Field(default_factory=_now)
    completed: bool = False
    repo_path: str = ""
    description: str = ""


# ── Session tracking ──────────────────────────────────────────────────────────

class SelfReport(BaseModel):
    """Three-question self-report collected at end of every session."""
    task_completed: bool = False
    understanding_rating: int = 3          # 1 (confused) – 5 (solid)
    stuck_on: list[str] = Field(default_factory=list)   # concept names
    breakthrough: str = ""                 # free-text "aha moment"
    submitted_at: str = Field(default_factory=_now)


class SessionSignals(BaseModel):
    """Objective signals collected during a session (medium + high quality)."""
    # Medium signal
    active_seconds: int = 0        # time in space-relevant app, not idle
    idle_seconds: int = 0          # system idle during session
    focus_ratio: float = 0.0       # active / total  (0–1)
    # High signal
    files_edited: list[str] = Field(default_factory=list)
    lines_written: int = 0         # lines added (git diff or mtime scan)
    git_commits: int = 0
    # Composite
    depth_score: float = 0.0       # 0–1 weighted composite


class SpaceSession(BaseModel):
    """One complete learning session — the primary optimization unit."""
    session_id: str
    space_dir: str
    concept: str
    task_id: str = ""
    started_at: datetime
    ended_at: datetime | None = None
    planned_minutes: int = 30
    signals: SessionSignals = Field(default_factory=SessionSignals)
    self_report: SelfReport = Field(default_factory=SelfReport)

    @property
    def actual_minutes(self) -> float:
        if self.ended_at is None:
            return 0.0
        return (self.ended_at - self.started_at).total_seconds() / 60.0

    @property
    def efficiency(self) -> float:
        """active_minutes / planned_minutes capped at 1.5."""
        if self.planned_minutes <= 0:
            return 0.0
        active_min = self.signals.active_seconds / 60.0
        return min(1.5, active_min / self.planned_minutes)


# ── Practice / Testing ────────────────────────────────────────────────────────

class TestQuestion(BaseModel):
    question_id: str
    question: str
    question_type: Literal["mcq", "short_answer", "code", "true_false"] = "short_answer"
    options: list[str] = Field(default_factory=list)   # for MCQ
    correct_answer: str = ""
    explanation: str = ""
    concept: str = ""
    difficulty: SkillLevel = SkillLevel.NOVICE
    points: int = 10
    time_limit_seconds: int = 120   # per-question timer (user-configurable)
    source: str = "llm"             # "llm" | "rag:<file>"


class PracticeTest(BaseModel):
    test_id: str
    test_type: Literal["concept", "topic", "full_space"] = "concept"
    scope: str = ""                 # concept name / topic name / "full"
    source: Literal["llm", "rag", "prompt"] = "llm"
    source_prompt: str = ""         # custom prompt if source=="prompt"
    questions: list[TestQuestion] = Field(default_factory=list)
    total_time_seconds: int = 0     # 0 = sum of per-question timers
    created_at: str = Field(default_factory=_now)
    space_dir: str = ""
    domain: str = ""
    level: SkillLevel = SkillLevel.NOVICE


class QuestionResult(BaseModel):
    question_id: str
    user_answer: str
    correct: bool = False
    score: int = 0
    time_taken_seconds: int = 0
    timed_out: bool = False
    llm_feedback: str = ""


class TestResult(BaseModel):
    test_id: str
    session_id: str = ""
    started_at: str = Field(default_factory=_now)
    finished_at: str = ""
    question_results: list[QuestionResult] = Field(default_factory=list)
    total_score: int = 0
    max_score: int = 0
    percent: float = 0.0
    passed: bool = False
    weak_concepts: list[str] = Field(default_factory=list)
    strong_concepts: list[str] = Field(default_factory=list)
    xp_earned: int = 0


# ── Optimization output ───────────────────────────────────────────────────────

class SessionOptimization(BaseModel):
    """One concrete optimization derived from session signals."""
    signal_source: str             # e.g. "focus_ratio", "depth_score_trend"
    observation: str               # what the signal shows
    recommendation: str            # specific actionable advice
    priority: Literal["high", "medium", "low"] = "medium"
    xp_bonus: int = 0              # bonus XP if learner acts on this


# ── Learner profile ───────────────────────────────────────────────────────────

class LearnerProfile(BaseModel):
    name: str = ""
    background: str = ""
    goal: str = ""
    skill_level: SkillLevel = SkillLevel.NOVICE
    mastered_concepts: list[str] = Field(default_factory=list)
    concept_mastery_map: dict[str, ConceptMastery] = Field(default_factory=dict)
    struggling_concepts: list[str] = Field(default_factory=list)
    preferred_style: str = "visual + hands-on"
    streak_days: int = 0
    total_sessions: int = 0
    last_seen: str = Field(default_factory=_now)
    xp: int = 0
    daily_goal_minutes: int = 30
    completed_tasks: list[str] = Field(default_factory=list)
    completed_projects: list[ProjectRecord] = Field(default_factory=list)
    badges: list[str] = Field(default_factory=list)
    is_technical: bool = False
    language: str = "en"


# ── Tool registry ─────────────────────────────────────────────────────────────

class ToolRecommendation(BaseModel):
    name: str
    purpose: str
    install_linux: str = ""
    install_mac: str = ""
    install_windows: str = ""
    url: str = ""
    why_experts_use_it: str = ""
    category: str = "general"


# ── Space profile ─────────────────────────────────────────────────────────────

class SpaceProfile(BaseModel):
    space_type: SpaceType
    domain: str
    learner: LearnerProfile = Field(default_factory=LearnerProfile)
    core_concepts: list[str] = Field(default_factory=list)
    recommended_tools: list[ToolRecommendation] = Field(default_factory=list)
    expert_tools_installed: list[str] = Field(default_factory=list)
    workspace_dir: str = ""
    created_at: str = Field(default_factory=_now)
    updated_at: str = Field(default_factory=_now)
    custom_domain_description: str = ""
    latest_tools_fetched_at: str = ""
    rag_enabled: bool = False

    def to_context_block(self) -> str:
        lr = self.learner
        lines = [
            f"## Sarthak Space: {self.domain}",
            f"**Learner**: {lr.name or 'Learner'} | Level: {lr.skill_level.value}",
            f"**Background**: {lr.background or 'Not specified'}",
            f"**Goal**: {lr.goal or 'Mastery'}",
            f"**XP**: {lr.xp} | Streak: {lr.streak_days}d | Sessions: {lr.total_sessions}",
        ]
        if lr.mastered_concepts:
            lines.append(f"**Mastered (recent)**: {', '.join(lr.mastered_concepts[-5:])}")
        if lr.struggling_concepts:
            lines.append(f"**Struggling**: {', '.join(lr.struggling_concepts)}")
        if self.expert_tools_installed:
            lines.append(f"**Active tools**: {', '.join(self.expert_tools_installed[:6])}")
        return "\n".join(lines)


# ── Learning task ─────────────────────────────────────────────────────────────

class LearningTask(BaseModel):
    task_id: str
    title: str
    concept: str
    difficulty: SkillLevel
    task_type: str
    instructions: str
    expected_outcome: str
    hints: list[str] = Field(default_factory=list)
    resources: list[str] = Field(default_factory=list)
    math_foundation: str = ""
    real_world_hook: str = ""
    starter_code: str = ""
    no_code_version: str = ""
    bonus_challenge: str = ""
    xp_reward: int = 10
    estimated_minutes: int = 30
    project_id: str = ""


# ── Space context (runtime) ───────────────────────────────────────────────────

class SpaceContext(BaseModel):
    workspace_dir: str
    profile: SpaceProfile
    current_task: LearningTask | None = None
    recent_activity: str = ""
    shell_available: bool = True
    web_available: bool = True
    platform: str = "linux"


# ── Mastery result ────────────────────────────────────────────────────────────

class MasteryResult(BaseModel):
    reply: str
    next_task: LearningTask | None = None
    workspace_changes: list[str] = Field(default_factory=list)
    tools_added: list[str] = Field(default_factory=list)
    concept_mastered: str = ""
    concept_struggling: str = ""
    xp_earned: int = 0
    action_taken: str = ""
    badges_earned: list[str] = Field(default_factory=list)
    review_due: list[str] = Field(default_factory=list)
    project_scaffolded: str = ""
    test_result: TestResult | None = None
    optimizations: list[SessionOptimization] = Field(default_factory=list)


# ── Profile mutation helpers ───────────────────────────────────────────────────

def award_xp(profile: SpaceProfile, xp: int) -> tuple[SpaceProfile, bool]:
    """Add XP to learner. Advances skill level when threshold is crossed.

    Returns:
        (profile, leveled_up) — profile mutated in-place, leveled_up is True
        when the learner crossed into the next SkillLevel.
    """
    profile.learner.xp += xp
    threshold = XP_THRESHOLDS.get(profile.learner.skill_level, 9999)
    leveled_up = False
    if profile.learner.xp >= threshold:
        idx = LEVEL_ORDER.index(profile.learner.skill_level)
        if idx < len(LEVEL_ORDER) - 1:
            profile.learner.skill_level = LEVEL_ORDER[idx + 1]
            leveled_up = True
    return profile, leveled_up


def update_streak(profile: SpaceProfile) -> SpaceProfile:
    """Increment daily streak or reset it based on last_seen date."""
    now = datetime.now(timezone.utc)
    try:
        last = datetime.fromisoformat(profile.learner.last_seen)
        delta = (now.date() - last.date()).days
        if delta == 1:
            profile.learner.streak_days += 1
        elif delta > 1:
            profile.learner.streak_days = 1
    except Exception:
        profile.learner.streak_days = 1
    profile.learner.last_seen = now.isoformat()
    return profile
