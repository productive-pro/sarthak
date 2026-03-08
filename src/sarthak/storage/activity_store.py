"""
Sarthak AI — User activity store.

Unified read/write for the user_activity table.
Every artefact the user produces in the frontend (audio notes, video notes,
code runs, chat turns, file uploads, practice tests, quicktests, notes) is
written here so the intelligence pipeline can consume it.

Write helpers are called by API endpoints and internal recorders.
Read helpers are called by LearnerContext, digest agents, and SRS.
"""
from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Literal

from .db import connect

ActivityType = Literal[
    "audio_note", "video_note", "code_run", "chat",
    "file_upload", "practice_test", "quicktest", "note",
]


async def _get_concept_title(space_dir: str, concept_id: str, db_obj=None) -> str:
    """Resolve concept title from roadmap DB. Returns concept_id on failure."""
    if not concept_id:
        return ""
    try:
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
    db=None,  # optional open RoadmapDB for concept title resolution
) -> int:
    """Convenience wrapper: resolves concept_title if missing, then writes. Returns row id."""
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
    async with connect() as db:
        cur = await db.execute(
            """INSERT INTO user_activity
               (activity_type, space_dir, concept_id, concept_title,
                session_id, content_text, media_path, metadata)
               VALUES (?,?,?,?,?,?,?,?)""",
            (
                activity_type, space_dir, concept_id, concept_title,
                session_id, content_text, media_path,
                json.dumps(metadata or {}),
            ),
        )
        await db.commit()
        return cur.lastrowid  # type: ignore[return-value]


async def query_activity(
    *,
    space_dir: str = "",
    activity_type: ActivityType | None = None,
    concept_title: str = "",
    days: int = 30,
    limit: int = 200,
) -> list[dict]:
    """Return activity rows, newest first, filtered by optional dimensions."""
    cutoff = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()
    clauses = ["ts >= ?"]
    params: list = [cutoff]

    if space_dir:
        clauses.append("space_dir = ?")
        params.append(space_dir)
    if activity_type:
        clauses.append("activity_type = ?")
        params.append(activity_type)
    if concept_title:
        clauses.append("concept_title = ?")
        params.append(concept_title)

    where = " AND ".join(clauses)
    params.append(limit)

    async with connect() as db:
        async with db.execute(
            f"SELECT * FROM user_activity WHERE {where} ORDER BY ts DESC LIMIT ?",
            params,
        ) as cur:
            rows = await cur.fetchall()
    return [dict(r) for r in rows]


async def activity_summary(space_dir: str, days: int = 7) -> dict:
    """Aggregate counts by activity_type for a space, used by digest."""
    cutoff = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()
    async with connect() as db:
        async with db.execute(
            """SELECT activity_type, COUNT(*) as cnt
               FROM user_activity
               WHERE space_dir=? AND ts >= ?
               GROUP BY activity_type""",
            (space_dir, cutoff),
        ) as cur:
            rows = await cur.fetchall()
    return {r["activity_type"]: r["cnt"] for r in rows}


async def recent_code_runs(space_dir: str, limit: int = 10) -> list[dict]:
    """Most recent code playground executions with output snippets."""
    return await query_activity(
        space_dir=space_dir, activity_type="code_run", limit=limit, days=30
    )


async def recent_media_notes(space_dir: str, days: int = 14) -> list[dict]:
    """Audio and video notes with transcripts (content_text)."""
    cutoff = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()
    async with connect() as db:
        async with db.execute(
            """SELECT * FROM user_activity
               WHERE space_dir=? AND activity_type IN ('audio_note','video_note')
               AND ts >= ? ORDER BY ts DESC LIMIT 50""",
            (space_dir, cutoff),
        ) as cur:
            rows = await cur.fetchall()
    return [dict(r) for r in rows]


async def failed_code_run_concepts(space_dir: str, threshold: int = 3, days: int = 30) -> list[str]:
    """Concepts with >= threshold failed code runs — feed into SRS scheduler."""
    cutoff = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()
    async with connect() as db:
        async with db.execute(
            """SELECT concept_title, COUNT(*) as fails
               FROM user_activity
               WHERE space_dir=? AND activity_type='code_run' AND ts >= ?
               AND json_extract(metadata,'$.success') = 0
               AND concept_title != ''
               GROUP BY concept_title
               HAVING fails >= ?""",
            (space_dir, cutoff, threshold),
        ) as cur:
            rows = await cur.fetchall()
    return [r["concept_title"] for r in rows]


async def concepts_touched(space_dir: str, days: int = 14) -> list[str]:
    """Distinct concept titles with any activity in the window."""
    cutoff = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()
    async with connect() as db:
        async with db.execute(
            """SELECT DISTINCT concept_title FROM user_activity
               WHERE space_dir=? AND concept_title != '' AND ts >= ?
               ORDER BY ts DESC""",
            (space_dir, cutoff),
        ) as cur:
            rows = await cur.fetchall()
    return [r["concept_title"] for r in rows]
