from __future__ import annotations

from datetime import datetime, timedelta, timezone

from sarthak.spaces.models import ConceptMastery, SpaceProfile, SkillLevel


class SpacedRepetitionAgent:
    """SM-2 inspired spaced repetition. Determines which concepts need review."""

    def get_due_reviews(
        self,
        profile: SpaceProfile,
        max_reviews: int = 2,
    ) -> list[str]:
        now = datetime.now(timezone.utc)
        due: list[str] = []
        for concept, mastery in profile.learner.concept_mastery_map.items():
            try:
                if datetime.fromisoformat(mastery.next_review_due) <= now:
                    due.append(concept)
            except Exception:
                pass
        # Fallback: mastered concepts not yet in the map
        if not due:
            for concept in profile.learner.mastered_concepts[-10:]:
                if concept not in profile.learner.concept_mastery_map:
                    due.append(concept)
                if len(due) >= max_reviews:
                    break
        return due[:max_reviews]

    def update_after_review(
        self,
        profile: SpaceProfile,
        concept: str,
        recalled: bool,
    ) -> SpaceProfile:
        now = datetime.now(timezone.utc)
        mastery = profile.learner.concept_mastery_map.get(concept) or ConceptMastery(concept=concept)
        mastery.review_count += 1
        mastery.last_reviewed = now.isoformat()
        if recalled:
            mastery.strength = min(1.0, mastery.strength + 0.2)
            # SM-2 style: interval doubles per successive recall, capped at 30 days.
            # review_count was already incremented above, so subtract 1 to get 0-based index.
            interval_days = min(2 ** max(0, mastery.review_count - 1), 30)
        else:
            mastery.strength = max(0.0, mastery.strength - 0.3)
            interval_days = 1  # failed recall → review again tomorrow
        mastery.next_review_due = (now + timedelta(days=interval_days)).isoformat()
        profile.learner.concept_mastery_map[concept] = mastery
        return profile


class BadgeAgent:
    """Awards achievement badges. Milestones create motivation."""

    BADGES = {
        "first_session":         ("First Step", "Completed first session"),
        "streak_3":              ("On Fire", "3-day streak"),
        "streak_7":              ("Week Warrior", "7-day streak"),
        "streak_30":             ("Diamond Streak", "30-day streak"),
        "level_beginner":        ("Leveling Up", "Reached Beginner"),
        "level_intermediate":    ("Intermediate", "Reached Intermediate"),
        "level_advanced":        ("Advanced", "Reached Advanced"),
        "level_expert":          ("Expert", "Reached Expert"),
        "concepts_10":           ("Explorer", "Mastered 10 concepts"),
        "concepts_25":           ("Deep Thinker", "Mastered 25 concepts"),
        "concepts_50":           ("Thought Leader", "Mastered 50 concepts"),
        "first_project":         ("Builder", "Completed first project"),
        "projects_3":            ("Maker", "Completed 3 projects"),
        "novel_approach":        ("Innovator", "Solved in a novel way"),
        "math_5":                ("Math Master", "Completed 5 math derivations"),
        "quick_streak_5":        ("Sprint Master", "5 quicktests in a row"),
    }

    def check_and_award(
        self,
        profile: SpaceProfile,
        context: dict,
    ) -> list[str]:
        earned: list[str] = []
        # Use profile.learner.badges as the live source so within-call dedup works correctly.
        existing = set(profile.learner.badges)

        def award(badge_id: str) -> None:
            name, _ = self.BADGES[badge_id]
            if name not in existing:  # dedup: check live set
                profile.learner.badges.append(name)
                existing.add(name)  # keep set in sync so the same badge can't fire twice
                earned.append(name)

        s = profile.learner.total_sessions
        streak = profile.learner.streak_days
        mc = len(profile.learner.mastered_concepts)
        level = profile.learner.skill_level
        projects = len(profile.learner.completed_projects)

        if s == 1:
            award("first_session")
        if streak >= 3:
            award("streak_3")
        if streak >= 7:
            award("streak_7")
        if streak >= 30:
            award("streak_30")
        if mc >= 10:
            award("concepts_10")
        if mc >= 25:
            award("concepts_25")
        if mc >= 50:
            award("concepts_50")
        if level == SkillLevel.BEGINNER:
            award("level_beginner")
        if level == SkillLevel.INTERMEDIATE:
            award("level_intermediate")
        if level == SkillLevel.ADVANCED:
            award("level_advanced")
        if level == SkillLevel.EXPERT:
            award("level_expert")
        if projects >= 1:
            award("first_project")
        if projects >= 3:
            award("projects_3")
        if context.get("novel_approach"):
            award("novel_approach")
        if context.get("math_sessions", 0) >= 5:
            award("math_5")

        return earned
