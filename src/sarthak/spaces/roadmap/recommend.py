"""
Sarthak Spaces — Recommendation engine (derived; no storage).

Derived from roadmap + learner state. Returns top-N next concepts using
a multi-signal scoring strategy that mirrors how a real tutor would decide.

Strategy (ranked by weight):
  1. BLOCK concepts — prerequisite completions gate later concepts
  2. STRUGGLE concepts — fix gaps before advancing (highest priority)
  3. REVIEW due — weave SRS reviews in naturally
  4. ZPD advancement — concepts just beyond current mastery
  5. Tag continuity — thematic momentum from recently completed tags
  6. Structural order — tie-break by chapter → topic → concept order

Public API:
    recommend_next(roadmap, top_k, mastered, struggling, review_due) → list[Concept]
    recommend_with_reasons(roadmap, ...) → list[tuple[Concept, str]]
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from .models import Concept, Roadmap, RoadmapStatus

if TYPE_CHECKING:
    pass


# ── Score weights (tune here, not in logic) ────────────────────────────────────

_W_STRUGGLE     = 100   # fix known gaps first — absolute priority
_W_REVIEW       = 80    # SRS review due — nearly as important as fixing gaps
_W_PREREQ_READY = 60    # all prerequisites met → concept is now unlocked
_W_IN_PROGRESS  = 40    # already started, finish before starting new
_W_TAG_OVERLAP  = 10    # per overlapping tag with recently completed concepts
_W_ORDER_DECAY  = -1    # per structural position unit (favor earlier in roadmap)


@dataclass
class _Scored:
    concept: Concept
    ch_order: int
    tp_order: int
    cn_order: int
    score: float = 0.0
    reason: str = ""


# ── Public API ─────────────────────────────────────────────────────────────────

def recommend_next(
    roadmap: Roadmap,
    top_k: int = 3,
    mastered: list[str] | None = None,
    struggling: list[str] | None = None,
    review_due: list[str] | None = None,
) -> list[Concept]:
    """
    Return top_k concept recommendations.

    Args:
        roadmap:    Current roadmap (with concept statuses set).
        top_k:      How many recommendations to return.
        mastered:   Concept titles the learner has mastered (for prerequisite check).
        struggling: Concept titles the learner is stuck on (highest priority fix).
        review_due: Concept titles due for spaced-repetition review.
    """
    scored = _score_all(roadmap, mastered or [], struggling or [], review_due or [])
    scored.sort(key=lambda s: (-s.score, s.ch_order, s.tp_order, s.cn_order))
    return [s.concept for s in scored[:top_k]]


def recommend_with_reasons(
    roadmap: Roadmap,
    top_k: int = 3,
    mastered: list[str] | None = None,
    struggling: list[str] | None = None,
    review_due: list[str] | None = None,
) -> list[tuple[Concept, str]]:
    """
    Same as recommend_next but also returns a human-readable reason per concept.
    Used by WorkspaceAnalyserAgent and digest builders.
    """
    scored = _score_all(roadmap, mastered or [], struggling or [], review_due or [])
    scored.sort(key=lambda s: (-s.score, s.ch_order, s.tp_order, s.cn_order))
    return [(s.concept, s.reason) for s in scored[:top_k]]


# ── Scoring engine ─────────────────────────────────────────────────────────────

def _score_all(
    roadmap: Roadmap,
    mastered: list[str],
    struggling: list[str],
    review_due: list[str],
) -> list[_Scored]:
    """Build a scored list of all actionable (not-completed) concepts."""

    mastered_set   = set(mastered)
    struggling_set = set(s.lower() for s in struggling)
    review_set     = set(r.lower() for r in review_due)

    # Collect completed concept IDs (for prerequisite checks) and tags
    completed_ids:  set[str] = set()
    completed_tags: set[str] = set()

    for ch in roadmap.chapters:
        for tp in ch.topics:
            for cn in tp.concepts:
                if cn.status == RoadmapStatus.COMPLETED:
                    completed_ids.add(cn.id)
                    completed_tags.update(cn.tags)
                    mastered_set.add(cn.title)

    if not roadmap.chapters:
        return []

    scored: list[_Scored] = []

    for ch in roadmap.chapters:
        for tp in ch.topics:
            for cn in tp.concepts:
                if cn.status == RoadmapStatus.COMPLETED:
                    continue

                s = _Scored(concept=cn, ch_order=ch.order, tp_order=tp.order, cn_order=cn.order)

                # ── Signal 1: struggling — fix gaps first ──────────────────────
                if cn.title.lower() in struggling_set:
                    s.score += _W_STRUGGLE
                    s.reason = f"you're struggling with {cn.title} — fix this gap first"

                # ── Signal 2: SRS review due ───────────────────────────────────
                elif cn.title.lower() in review_set:
                    s.score += _W_REVIEW
                    s.reason = f"{cn.title} is due for spaced-repetition review"

                # ── Signal 3: prerequisite gate ────────────────────────────────
                prereqs_met = _all_prereqs_met(cn, completed_ids, mastered_set, roadmap)
                if prereqs_met and s.score == 0:
                    s.score += _W_PREREQ_READY

                # ── Signal 4: in-progress — finish before starting new ─────────
                if cn.status == RoadmapStatus.IN_PROGRESS:
                    s.score += _W_IN_PROGRESS
                    if not s.reason:
                        s.reason = f"{cn.title} is already in progress — finish it"

                # ── Signal 5: tag continuity ───────────────────────────────────
                tag_overlap = len(set(cn.tags) & completed_tags)
                s.score += tag_overlap * _W_TAG_OVERLAP

                # ── Signal 6: structural order decay ──────────────────────────
                position = ch.order * 1000 + tp.order * 100 + cn.order
                s.score += position * _W_ORDER_DECAY

                # ── Skip if prerequisites not met and no special signals ───────
                # (concept is locked — can't learn it yet)
                if not prereqs_met and s.score < _W_REVIEW:
                    continue

                # Fallback reason
                if not s.reason:
                    if tag_overlap > 0:
                        s.reason = (
                            f"{cn.title} shares {tag_overlap} tag(s) with what you just completed"
                        )
                    else:
                        s.reason = f"next in curriculum order for {ch.title} → {tp.title}"

                scored.append(s)

    return scored


def _all_prereqs_met(
    concept: Concept,
    completed_ids: set[str],
    mastered_titles: set[str],
    roadmap: Roadmap,
) -> bool:
    """
    Returns True if all listed prerequisite concept IDs are completed
    OR if the concept has no prerequisites.
    Falls back to True for concepts without related_concepts set
    (so legacy roadmaps without prereq data are not blocked).
    """
    if not concept.related_concepts:
        return True
    for prereq_id in concept.related_concepts:
        if prereq_id in completed_ids:
            continue
        # Try resolving by title for robustness
        prereq_concept = roadmap.get_concept(prereq_id)
        if prereq_concept and prereq_concept.title in mastered_titles:
            continue
        return False
    return True
