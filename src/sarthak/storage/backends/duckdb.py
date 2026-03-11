"""
DuckDB ActivityRepository implementation.

Schema:  storage/sql/duckdb/schema.sql
Queries: storage/sql/duckdb/queries.sql

Requires: pip install duckdb
Config:
    [storage.duckdb]
    path = "~/.sarthak_ai/sarthak.duckdb"

DuckDB excels at analytical queries (digest agents, weekly reviews).
Single-writer: all writes go through threading.Lock + asyncio.to_thread.
"""
from __future__ import annotations

import asyncio
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import structlog

from sarthak.storage.sql_loader import load_schema, load_queries

log = structlog.get_logger(__name__)

_SCHEMA = load_schema("duckdb", "schema")
_Q = load_queries("duckdb", "queries")


class DuckDBActivityRepo:
    """ActivityRepository backed by DuckDB."""

    def __init__(self, path: str = "~/.sarthak_ai/sarthak.duckdb") -> None:
        import threading
        self._path = str(Path(path).expanduser().resolve())
        self._write_lock = threading.Lock()
        self._conn_lock = threading.Lock()   # guards lazy _conn_cache creation
        self._initialized = False
        self._conn_cache: Any = None  # persistent DuckDB connection

    def _conn(self) -> Any:
        """Return a persistent DuckDB connection (thread-safe lazy init)."""
        if self._conn_cache is not None:
            return self._conn_cache
        with self._conn_lock:
            if self._conn_cache is None:
                import duckdb  # type: ignore
                self._conn_cache = duckdb.connect(self._path)
        return self._conn_cache

    def _ensure_schema(self) -> None:
        """Double-checked locking — safe against concurrent threads."""
        if self._initialized:
            return
        with self._write_lock:
            if self._initialized:
                return
            self._conn().execute(_SCHEMA)
            self._initialized = True

    def _cutoff(self, days: int) -> datetime:
        return datetime.now(timezone.utc) - timedelta(days=days)

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
        def _do() -> int:
            self._ensure_schema()
            with self._write_lock:
                conn = self._conn()
                row = conn.execute(
                    _Q["insert_activity"],
                    [activity_type, space_dir, concept_id, concept_title,
                     session_id, content_text, media_path,
                     json.dumps(metadata or {})],
                ).fetchone()
                return row[0]
        return await asyncio.to_thread(_do)

    async def query(
        self,
        *,
        space_dir: str = "",
        activity_type: str | None = None,
        concept_title: str = "",
        days: int = 30,
        limit: int = 200,
    ) -> list[dict]:
        cutoff = self._cutoff(days)

        def _do() -> list[dict]:
            self._ensure_schema()
            clauses = ["ts >= ?"]
            params: list[Any] = [cutoff]
            if space_dir:
                clauses.append("space_dir = ?"); params.append(space_dir)
            if activity_type:
                clauses.append("activity_type = ?"); params.append(activity_type)
            if concept_title:
                clauses.append("concept_title = ?"); params.append(concept_title)
            params.append(limit)
            where = " AND ".join(clauses)
            conn = self._conn()
            return conn.execute(
                f"SELECT * FROM user_activity WHERE {where} ORDER BY ts DESC LIMIT ?",
                params,
            ).fetchdf().to_dict("records")
        return await asyncio.to_thread(_do)

    async def summary(self, space_dir: str, days: int = 7) -> dict:
        cutoff = self._cutoff(days)

        def _do() -> dict:
            self._ensure_schema()
            rows = self._conn().execute(_Q["summary"], [space_dir, cutoff]).fetchall()
            return {r[0]: r[1] for r in rows}
        return await asyncio.to_thread(_do)

    async def failed_code_concepts(
        self, space_dir: str, threshold: int = 3, days: int = 30
    ) -> list[str]:
        cutoff = self._cutoff(days)

        def _do() -> list[str]:
            self._ensure_schema()
            rows = self._conn().execute(
                _Q["failed_code_concepts"], [space_dir, cutoff, threshold]
            ).fetchall()
            return [r[0] for r in rows]
        return await asyncio.to_thread(_do)

    async def concepts_touched(self, space_dir: str, days: int = 14) -> list[str]:
        cutoff = self._cutoff(days)

        def _do() -> list[str]:
            self._ensure_schema()
            rows = self._conn().execute(
                _Q["concepts_touched"], [space_dir, cutoff]
            ).fetchall()
            return [r[0] for r in rows]
        return await asyncio.to_thread(_do)

    async def recent_media_notes(self, space_dir: str, days: int = 14) -> list[dict]:
        cutoff = self._cutoff(days)

        def _do() -> list[dict]:
            self._ensure_schema()
            return self._conn().execute(
                _Q["recent_media_notes"], [space_dir, cutoff]
            ).fetchdf().to_dict("records")
        return await asyncio.to_thread(_do)
