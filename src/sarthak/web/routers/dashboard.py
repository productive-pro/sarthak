"""
dashboard.py — Dashboard summary endpoint.
"""
from __future__ import annotations

from fastapi import APIRouter

router = APIRouter()


@router.get("/api/dashboard")
async def dashboard(hours: int = 24) -> dict:
    from pathlib import Path
    from sarthak.spaces.store import get_active_space, list_spaces, load_space

    data: dict = {
        "active_space":    None,
        "spaces_count":    0,
        "spaces":          [],
    }

    # ── Active space ──────────────────────────────────────────────────────────
    try:
        active = get_active_space()
        if active and active.get("directory"):
            ws_dir = Path(active["directory"])
            ws = load_space(ws_dir) or {}
            from sarthak.spaces.store import load_profile
            prof_obj = load_profile(ws_dir)
            lr = prof_obj.learner if prof_obj else None
            from sarthak.spaces.models import XP_THRESHOLDS, LEVEL_ORDER, LEVEL_LABELS
            xp = lr.xp if lr else 0
            _thresholds = [0] + [XP_THRESHOLDS[lvl] for lvl in LEVEL_ORDER]
            cur_lvl_xp  = next((t for t in reversed(_thresholds) if xp >= t), 0)
            next_lvl_xp = next((t for t in _thresholds if t > xp), _thresholds[-1])
            progress_pct = (
                round((xp - cur_lvl_xp) / max(next_lvl_xp - cur_lvl_xp, 1) * 100)
                if next_lvl_xp > cur_lvl_xp else 100
            )
            data["active_space"] = {
                "name":          active.get("name") or ws.get("name", ""),
                "directory":     active["directory"],
                "space_type":    ws.get("space_type", ""),
                "domain":        prof_obj.domain if prof_obj else "",
                "level":         LEVEL_LABELS.get(lr.skill_level, lr.skill_level.value) if lr else "",
                "xp":            xp,
                "xp_to_next":    next_lvl_xp - xp,
                "progress_pct":  progress_pct,
                "streak_days":   lr.streak_days if lr else 0,
                "session_count": lr.total_sessions if lr else 0,
                "skills":        (lr.mastered_concepts[-5:] if lr else []),
                "current_concept": "",
                "activated_at":  active.get("activated_at", ""),
            }
    except Exception:
        pass

    # ── Spaces list ───────────────────────────────────────────────────────────
    try:
        spaces = list_spaces()
        data["spaces_count"] = len(spaces)
        data["spaces"] = [
            {
                "name":       s.get("name", ""),
                "space_type": s.get("space_type", ""),
                "progress":   s.get("progress", 0),
                "updated_at": s.get("updated_at", ""),
            }
            for s in spaces[:5]
        ]
    except Exception:
        pass

    return data
