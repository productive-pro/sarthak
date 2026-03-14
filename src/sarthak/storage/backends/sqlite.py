"""
SQLite ActivityRepository — default backend.

Schema:  storage/sql/sqlite/schema_activity.sql
Queries: storage/sql/sqlite/queries_activity.sql

All SQL is loaded from .sql files at import time.
Business logic never constructs SQL strings directly.

Design notes:
- Date arithmetic is delegated to SQLite (datetime('now', '-N days')) so the
  query planner can use the ts index.
- The query() method uses a lookup table to pick the right pre-written
  SQL variant instead of building an f-string WHERE clause.
"""
from __future__ import annotations

import asyncio
import json

import structlog

from sarthak.storage.sql_loader import load_schema, load_queries
from sarthak.storage.db import connect

log = structlog.get_logger(__name__)

_SCHEMA = load_schema("sqlite", "schema_activity")
_Q = load_queries("sqlite", "queries_activity")

_ACTIVITY_INIT_DONE = False
_INIT_LOCK = asyncio.Lock()


async def _ensure_activity_table() -> None:
    """Apply activity schema to the global DB. Idempotent, async-safe."""
    global _ACTIVITY_INIT_DONE
    if _ACTIVITY_INIT_DONE:
        return
    async with _INIT_LOCK:
        if _ACTIVITY_INIT_DONE:
            return
        async with connect() as db:
            await db.executescript(_SCHEMA)
            await db.commit()
        _ACTIVITY_INIT_DONE = True


class SQLiteActivityRepo:
    """SQLite implementation of ActivityRepository protocol."""

    async def write(
        self,
        *,
        activity_type: str,
        space_dir: str = "",
        concept_id: str = "",
        concept_title: str = "",
        session_id: str = "",
        content_text: str = "",
        media_path: str = "",
        metadata: dict | None = None,
    ) -> int:
        await _ensure_activity_table()
        async with connect() as db:
            cur = await db.execute(
                _Q["insert_activity"],
                (activity_type, space_dir, concept_id, concept_title,
                 session_id, content_text, media_path,
                 json.dumps(metadata or {})),
            )
            await db.commit()
            return cur.lastrowid  # type: ignore[return-value]

    async def query(
        self,
        *,
        space_dir: str = "",
        activity_type: str | None = None,
        concept_title: str = "",
        days: int = 30,
        limit: int = 200,
    ) -> list[dict]:
        """Return activity rows newest-first using a pre-written SQL variant.

        We pick among the six named query variants to avoid f-string SQL
        construction. Each variant covers one combination of the three optional
        filters (space_dir, activity_type, concept_title).
        """
        await _ensure_activity_table()
        from datetime import datetime, timedelta, timezone

        # Python-side cutoff for the base timestamp filter (index-friendly).
        cutoff = (
            datetime.now(timezone.utc) - timedelta(days=days)
        ).isoformat()

        has_space   = bool(space_dir)
        has_type    = activity_type is not None
        has_concept = bool(concept_title)

        # Select the right pre-written query variant
        if has_space and has_type and has_concept:
            sql    = _Q["query_filtered_space_type_concept"]
            params = (cutoff, space_dir, activity_type, concept_title, limit)
        elif has_space and has_type:
            sql    = _Q["query_filtered_space_type"]
            params = (cutoff, space_dir, activity_type, limit)
        elif has_space and has_concept:
            sql    = _Q["query_filtered_space_concept"]
            params = (cutoff, space_dir, concept_title, limit)
        elif has_type:
            sql    = _Q["query_filtered_type"]
            params = (cutoff, activity_type, limit)
        elif has_space:
            sql    = _Q["query_filtered_space"]
            params = (cutoff, space_dir, limit)
        else:
            sql    = _Q["query_all"]
            params = (cutoff, limit)

        async with connect() as db:
            async with db.execute(sql, params) as cur:
                rows = await cur.fetchall()
        return [dict(r) for r in rows]

    async def summary(self, space_dir: str, days: int = 7) -> dict:
        """Aggregate counts by activity_type. Uses SQLite native date math."""
        await _ensure_activity_table()
        async with connect() as db:
            async with db.execute(_Q["summary"], (space_dir, days)) as cur:
                rows = await cur.fetchall()
        return {r["activity_type"]: r["cnt"] for r in rows}

    async def failed_code_concepts(
        self, space_dir: str, threshold: int = 3, days: int = 30
    ) -> list[str]:
        await _ensure_activity_table()
        async with connect() as db:
            async with db.execute(
                _Q["failed_code_concepts"], (space_dir, days, threshold)
            ) as cur:
                rows = await cur.fetchall()
        return [r["concept_title"] for r in rows]

    async def concepts_touched(self, space_dir: str, days: int = 14) -> list[str]:
        await _ensure_activity_table()
        async with connect() as db:
            async with db.execute(
                _Q["concepts_touched"], (space_dir, days)
            ) as cur:
                rows = await cur.fetchall()
        return [r["concept_title"] for r in rows]

    async def recent_media_notes(self, space_dir: str, days: int = 14) -> list[dict]:
        await _ensure_activity_table()
        async with connect() as db:
            async with db.execute(
                _Q["recent_media_notes"], (space_dir, days)
            ) as cur:
                rows = await cur.fetchall()
        return [dict(r) for r in rows]

    async def activity_by_session(self, session_id: str) -> list[dict]:
        """Return all activity rows for a session, oldest first."""
        await _ensure_activity_table()
        async with connect() as db:
            async with db.execute(
                _Q["activity_by_session"], (session_id,)
            ) as cur:
                rows = await cur.fetchall()
        return [dict(r) for r in rows]

    async def count(self, space_dir: str) -> int:
        """Total activity rows for a space — useful for health checks."""
        await _ensure_activity_table()
        async with connect() as db:
            async with db.execute(_Q["count_by_space"], (space_dir,)) as cur:
                row = await cur.fetchone()
        return int(row["cnt"]) if row else 0

    async def prune(self, space_dir: str, keep_days: int = 90) -> int:
        """Delete transient rows older than keep_days (preserves practice_test/note).

        Returns number of rows deleted.
        """
        await _ensure_activity_table()
        async with connect() as db:
            cur = await db.execute(
                _Q["delete_old_activity"], (keep_days, space_dir)
            )
            await db.commit()
            return cur.rowcount
