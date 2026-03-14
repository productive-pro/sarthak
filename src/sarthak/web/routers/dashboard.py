"""
dashboard.py — Dashboard summary endpoint.

ActivityWatch data is fetched via the shared httpx client managed
by the app lifespan so no TCP connections are created per-request.
"""
from __future__ import annotations

from fastapi import APIRouter

router = APIRouter()

_LEARNING_APPS = frozenset({
    "code", "cursor", "nvim", "vim", "emacs", "terminal",
    "python", "jupyter", "zed", "intellij", "pycharm",
    "vscode", "obsidian", "notion", "logseq",
})


@router.get("/api/dashboard")
async def dashboard(hours: int = 24) -> dict:
    from pathlib import Path
    from sarthak.spaces.store import get_active_space, list_spaces, load_space

    data: dict = {
        "active_space":    None,
        "spaces_count":    0,
        "spaces":          [],
        "aw_available":    False,
        "total_minutes":   0,
        "focus_minutes":   0,
        "learning_minutes": 0,
        "focus_score":     0,
        "top_apps":        [],
        "is_afk":          False,
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

    # ── ActivityWatch ─────────────────────────────────────────────────────────
    # Use the shared httpx client from the app lifespan (no per-request teardown).
    try:
        from datetime import datetime, timezone, timedelta
        from sarthak.web.app import get_http_client

        aw_base = "http://localhost:5600/api/0"
        end     = datetime.now(timezone.utc)
        start   = end - timedelta(hours=hours)
        ts      = lambda dt: dt.strftime("%Y-%m-%dT%H:%M:%S.000Z")
        client  = get_http_client()

        r_info = await client.get(f"{aw_base}/info", timeout=2.0)
        r_info.raise_for_status()

        r_buckets = await client.get(f"{aw_base}/buckets", timeout=2.0)
        buckets = r_buckets.json() if r_buckets.is_success else {}

        afk_bucket = next((b for b in buckets if "afkstatus" in b), None)
        win_bucket = next((b for b in buckets if "window" in b and "afkstatus" not in b), None)

        total_minutes = focus_minutes = learning_minutes = 0
        top_apps: list[dict] = []
        is_afk = False

        if afk_bucket:
            r_afk = await client.get(
                f"{aw_base}/buckets/{afk_bucket}/events",
                params={"start": ts(start), "end": ts(end), "limit": -1},
                timeout=2.0,
            )
            if r_afk.is_success:
                for ev in r_afk.json():
                    dur = ev.get("duration", 0)
                    total_minutes += dur / 60
                    if ev.get("data", {}).get("status") == "not-afk":
                        focus_minutes += dur / 60
                afk_events = r_afk.json()
                if afk_events:
                    is_afk = afk_events[0].get("data", {}).get("status") == "afk"

        if win_bucket:
            r_win = await client.get(
                f"{aw_base}/buckets/{win_bucket}/events",
                params={"start": ts(start), "end": ts(end), "limit": -1},
                timeout=2.0,
            )
            if r_win.is_success:
                app_secs: dict[str, float] = {}
                app_is_learning: dict[str, bool] = {}
                for ev in r_win.json():
                    dur     = ev.get("duration", 0)
                    app     = ev.get("data", {}).get("app", "") or ""
                    is_learn = any(la in app.lower() for la in _LEARNING_APPS)
                    app_secs[app] = app_secs.get(app, 0) + dur
                    app_is_learning[app] = is_learn
                    if is_learn:
                        learning_minutes += dur / 60
                top_apps = sorted(
                    [{"app": a, "duration": s, "is_learning": app_is_learning.get(a, False)}
                     for a, s in app_secs.items()],
                    key=lambda x: x["duration"],
                    reverse=True,
                )[:12]

        focus_score = round(focus_minutes / max(total_minutes, 1) * 100) if total_minutes else 0
        data.update({
            "aw_available":    True,
            "total_minutes":   round(total_minutes),
            "focus_minutes":   round(focus_minutes),
            "learning_minutes": round(learning_minutes),
            "focus_score":     focus_score,
            "top_apps":        top_apps,
            "is_afk":          is_afk,
        })
    except Exception:
        pass  # AW not running — silently skip

    return data
