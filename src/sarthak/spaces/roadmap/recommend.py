"""
Sarthak Spaces — Recommendation engine (derived; no storage).

Derived from roadmap blob only. Returns top-N not-yet-completed concepts
whose tags overlap with recently completed concept tags.
"""
from __future__ import annotations

from .models import Concept, Roadmap, RoadmapStatus


def recommend_next(roadmap: Roadmap, top_k: int = 3) -> list[Concept]:
    """
    Return top_k concept recommendations based on completed items + tag overlap.

    Strategy:
    1. Collect tags from all completed concepts.
    2. Score remaining not-started/in-progress concepts by tag overlap.
    3. Tie-break by chapter order then concept order (so we don't jump ahead).
    """
    completed_tags: set[str] = set()
    candidates: list[tuple[Concept, int, int, int]] = []  # concept, ch_order, tp_order, cn_order

    for ch in roadmap.chapters:
        for tp in ch.topics:
            for cn in tp.concepts:
                if cn.status == RoadmapStatus.COMPLETED:
                    completed_tags.update(cn.tags)
                else:
                    candidates.append((cn, ch.order, tp.order, cn.order))

    if not candidates:
        return []

    def score(item: tuple[Concept, int, int, int]) -> tuple[int, int, int, int]:
        cn, ch_o, tp_o, cn_o = item
        overlap = len(set(cn.tags) & completed_tags)
        # Negate overlap so higher overlap sorts first; use struct position as tiebreak
        return (-overlap, ch_o, tp_o, cn_o)

    candidates.sort(key=score)
    return [c for c, *_ in candidates[:top_k]]
