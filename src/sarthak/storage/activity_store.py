"""
Sarthak AI — User activity store (public API).

All reads/writes go through the factory-provided ActivityRepository,
so the backend (SQLite by default) is swappable via config.toml [storage].

This module is the stable public API — all callers import from here,
never from the backend directly.

Backward compatible: same function signatures as before.
"""
from __future__ import annotations

from typing import Literal

ActivityType = Literal[
    "audio_note", "video_note", "code_run", "chat",
    "file_upload", "practice_test", "quicktest", "note",
]


def _repo():
    from sarthak.storage.factory import get_activity_repo
    return get_activity_repo()


async def _get_concept_title(space_dir: str, concept_id: str, db_obj=None) -> str:
    """Resolve concept title from roadmap DB. Returns concept_id on failure."""
    if not concept_id:
        return ""
    try:
        from pathlib import Path
        from sarthak.spaces.roadmap.db import RoadmapDB
        db = db_obj or RoadmapDB(Path(space_dir))
        if db_obj is None:
            await db.init()
        roadmap = await db.load_roadmap()
        if roadmap:
            cn = roadmap.get_concept(concept_id)
            if cn:
                return cn.title
    except Exception:
        pass
    return concept_id


async def record(
    *,
    activity_type: ActivityType,
    space_dir: str = "",
    concept_id: str = "",
    concept_title: str = "",
    session_id: str = "",
    content_text: str = "",
    media_path: str = "",
    metadata: dict | None = None,
    db=None,
) -> int:
    """Resolve concept_title if missing, then write. Returns row id."""
    if concept_id and not concept_title:
        concept_title = await _get_concept_title(space_dir, concept_id, db)
    return await write_activity(
        activity_type=activity_type,
        space_dir=space_dir,
        concept_id=concept_id,
        concept_title=concept_title,
        session_id=session_id,
        content_text=content_text,
        media_path=media_path,
        metadata=metadata,
    )


async def write_activity(
    *,
    activity_type: ActivityType,
    space_dir: str = "",
    concept_id: str = "",
    concept_title: str = "",
    session_id: str = "",
    content_text: str = "",
    media_path: str = "",
    metadata: dict | None = None,
) -> int:
    """Insert one user activity row. Returns the new row id."""
    return await _repo().write(
        activity_type=activity_type,
        space_dir=space_dir,
        concept_id=concept_id,
        concept_title=concept_title,
        session_id=session_id,
        content_text=content_text,
        media_path=media_path,
        metadata=metadata or {},
    )


async def query_activity(
    *,
    space_dir: str = "",
    activity_type: ActivityType | None = None,
    concept_title: str = "",
    days: int = 30,
    limit: int = 200,
) -> list[dict]:
    """Return activity rows, newest first, filtered by optional dimensions."""
    return await _repo().query(
        space_dir=space_dir,
        activity_type=activity_type,
        concept_title=concept_title,
        days=days,
        limit=limit,
    )


async def activity_summary(space_dir: str, days: int = 7) -> dict:
    """Aggregate counts by activity_type for a space."""
    return await _repo().summary(space_dir, days)


async def recent_code_runs(space_dir: str, limit: int = 10) -> list[dict]:
    return await query_activity(
        space_dir=space_dir, activity_type="code_run", limit=limit, days=30
    )


async def recent_media_notes(space_dir: str, days: int = 14) -> list[dict]:
    return await _repo().recent_media_notes(space_dir, days)


async def failed_code_run_concepts(
    space_dir: str, threshold: int = 3, days: int = 30
) -> list[str]:
    return await _repo().failed_code_concepts(space_dir, threshold, days)


async def concepts_touched(space_dir: str, days: int = 14) -> list[str]:
    return await _repo().concepts_touched(space_dir, days)


async def activity_by_session(session_id: str) -> list[dict]:
    """Return all activity rows for a specific session (oldest first)."""
    repo = _repo()
    if hasattr(repo, "activity_by_session"):
        return await repo.activity_by_session(session_id)
    return []


async def prune_activity(space_dir: str, keep_days: int = 90) -> int:
    """
    Delete old transient activity rows to keep the DB lean.
    Safe: preserves 'practice_test' and 'note' rows permanently.
    Returns number of rows deleted.
    """
    repo = _repo()
    if hasattr(repo, "prune"):
        return await repo.prune(space_dir, keep_days)
    return 0
