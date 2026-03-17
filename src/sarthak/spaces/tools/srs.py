"""
spaces/tools/srs.py — Spaced Repetition System (SM-2 algorithm)

Pure logic. No LLM. No I/O beyond the profile object.
Reusable by any agent, scheduler, or CLI that needs SRS scheduling.

Public API:
    get_due_reviews(profile, max_reviews)       → list[str]
    update_after_review(profile, concept, recalled) → SpaceProfile
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

from sarthak.spaces.models import ConceptMastery, SpaceProfile


def get_due_reviews(profile: SpaceProfile, max_reviews: int = 2) -> list[str]:
    """Return concepts due for spaced repetition review."""
    now = datetime.now(timezone.utc)
    due: list[str] = []
    for concept, mastery in profile.learner.concept_mastery_map.items():
        try:
            if datetime.fromisoformat(mastery.next_review_due) <= now:
                due.append(concept)
        except Exception:
            pass
    # Fallback: mastered concepts not yet scheduled
    if not due:
        for concept in profile.learner.mastered_concepts[-10:]:
            if concept not in profile.learner.concept_mastery_map:
                due.append(concept)
            if len(due) >= max_reviews:
                break
    return due[:max_reviews]


def update_after_review(
    profile: SpaceProfile,
    concept: str,
    recalled: bool,
) -> SpaceProfile:
    """
    Update SM-2 scheduling for a concept after a review attempt.
    Interval doubles on recall (capped at 30 days), resets to 1 day on failure.
    """
    now = datetime.now(timezone.utc)
    mastery = profile.learner.concept_mastery_map.get(concept) or ConceptMastery(concept=concept)
    mastery.review_count += 1
    mastery.last_reviewed = now.isoformat()
    if recalled:
        mastery.strength = min(1.0, mastery.strength + 0.2)
        interval_days = min(2 ** max(0, mastery.review_count - 1), 30)
    else:
        mastery.strength = max(0.0, mastery.strength - 0.3)
        interval_days = 1
    mastery.next_review_due = (now + timedelta(days=interval_days)).isoformat()
    profile.learner.concept_mastery_map[concept] = mastery
    return profile
