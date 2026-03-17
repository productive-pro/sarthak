"""
spaces/tools/badges.py — Achievement badge logic

Pure logic. No LLM. No I/O.
Reusable by orchestrator, scheduler, and any scoring context.

Public API:
    check_and_award(profile, context) → list[str]   (badge names earned this call)
    BADGES                            → dict         (full badge registry)
"""
from __future__ import annotations

from sarthak.spaces.models import SpaceProfile, SkillLevel


BADGES: dict[str, tuple[str, str]] = {
    "first_session":      ("First Step",       "Completed first session"),
    "streak_3":           ("On Fire",           "3-day streak"),
    "streak_7":           ("Week Warrior",      "7-day streak"),
    "streak_30":          ("Diamond Streak",    "30-day streak"),
    "level_beginner":     ("Leveling Up",       "Reached Beginner"),
    "level_intermediate": ("Intermediate",      "Reached Intermediate"),
    "level_advanced":     ("Advanced",          "Reached Advanced"),
    "level_expert":       ("Expert",            "Reached Expert"),
    "concepts_10":        ("Explorer",          "Mastered 10 concepts"),
    "concepts_25":        ("Deep Thinker",      "Mastered 25 concepts"),
    "concepts_50":        ("Thought Leader",    "Mastered 50 concepts"),
    "first_project":      ("Builder",           "Completed first project"),
    "projects_3":         ("Maker",             "Completed 3 projects"),
    "novel_approach":     ("Innovator",         "Solved in a novel way"),
    "math_5":             ("Math Master",       "Completed 5 math derivations"),
    "quick_streak_5":     ("Sprint Master",     "5 quicktests in a row"),
}


def check_and_award(profile: SpaceProfile, context: dict) -> list[str]:
    """
    Check milestone conditions and award any newly earned badges.
    Mutates profile.learner.badges in place.
    Returns list of newly earned badge names.
    """
    earned: list[str] = []
    existing = set(profile.learner.badges)

    def _award(badge_id: str) -> None:
        name, _ = BADGES[badge_id]
        if name not in existing:
            profile.learner.badges.append(name)
            existing.add(name)
            earned.append(name)

    s       = profile.learner.total_sessions
    streak  = profile.learner.streak_days
    mc      = len(profile.learner.mastered_concepts)
    level   = profile.learner.skill_level
    projects = len(profile.learner.completed_projects)

    if s == 1:        _award("first_session")
    if streak >= 3:   _award("streak_3")
    if streak >= 7:   _award("streak_7")
    if streak >= 30:  _award("streak_30")
    if mc >= 10:      _award("concepts_10")
    if mc >= 25:      _award("concepts_25")
    if mc >= 50:      _award("concepts_50")
    if level == SkillLevel.BEGINNER:     _award("level_beginner")
    if level == SkillLevel.INTERMEDIATE: _award("level_intermediate")
    if level == SkillLevel.ADVANCED:     _award("level_advanced")
    if level == SkillLevel.EXPERT:       _award("level_expert")
    if projects >= 1: _award("first_project")
    if projects >= 3: _award("projects_3")
    if context.get("novel_approach"):             _award("novel_approach")
    if context.get("math_sessions", 0) >= 5:      _award("math_5")

    return earned
