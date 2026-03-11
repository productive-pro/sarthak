"""
LibSQL / Turso ActivityRepository — edge-compatible SQLite wire protocol.

Schema:  storage/sql/sqlite/schema_libsql.sql
Queries: storage/sql/sqlite/queries_activity.sql  (identical to SQLite)

Supports two modes:
  1. Local  — embedded libsql file (fast, offline, same as SQLite)
  2. Remote — Turso cloud URL (ws:// or https://) with auth token

Requires: pip install libsql-client  (or libsql-experimental)
Config:
    [storage.libsql]
    url        = "file:///~/.sarthak_ai/sarthak.db"  # local
    # url      = "libsql://<db>.turso.io"              # Turso cloud
    auth_token = ""  # Turso auth token (leave empty for local)
"""
from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import structlog

from sarthak.storage.sql_loader import load_schema, load_queries

log = structlog.get_logger(__name__)

_SCHEMA = load_schema("sqlite", "schema_libsql")
# LibSQL uses the same ? placeholder style as SQLite — reuse queries
_Q = load_queries("sqlite", "queries_activity")


class LibSQLActivityRepo:
    """
    ActivityRepository backed by LibSQL (Turso).

    Local mode uses the embedded libsql driver (same perf as SQLite).
    Remote mode syncs to Turso via WebSocket with automatic reconnect.
    """

    def __init__(self, url: str, auth_token: str = "") -> None:
        self._url = url
        self._auth_token = auth_token
        self._client: Any = None
        self._initialized = False
        self._init_lock: Any = None  # asyncio.Lock created lazily

    async def _get_client(self) -> Any:
        if self._client is not None and self._initialized:
            return self._client
        import asyncio
        if self._init_lock is None:
            self._init_lock = asyncio.Lock()
        async with self._init_lock:
            if self._client is not None and self._initialized:
                return self._client
            try:
                import libsql_client as libsql  # type: ignore
            except ImportError:
                raise ImportError(
                    "libsql-client not installed. Run: pip install libsql-client"
                )
            self._client = libsql.create_client(
                url=self._url,
                auth_token=self._auth_token or None,
            )
            # Apply schema — execute each statement individually
            for stmt in _SCHEMA.split(";"):
                stmt = stmt.strip()
                if stmt:
                    await self._client.execute(stmt)
            self._initialized = True
            log.info("libsql_schema_applied", url=self._url)
        return self._client

    def _cutoff(self, days: int) -> str:
        return (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()

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
        client = await self._get_client()
        rs = await client.execute(
            _Q["insert_activity"],
            [activity_type, space_dir, concept_id, concept_title,
             session_id, content_text, media_path,
             json.dumps(metadata or {})],
        )
        return rs.last_insert_rowid or 0

    async def query(
        self,
        *,
        space_dir: str = "",
        activity_type: str | None = None,
        concept_title: str = "",
        days: int = 30,
        limit: int = 200,
    ) -> list[dict]:
        client = await self._get_client()
        cutoff = self._cutoff(days)
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
        rs = await client.execute(
            f"SELECT * FROM user_activity WHERE {where} ORDER BY ts DESC LIMIT ?",
            params,
        )
        return [dict(zip(rs.columns, row)) for row in rs.rows]

    async def summary(self, space_dir: str, days: int = 7) -> dict:
        client = await self._get_client()
        rs = await client.execute(_Q["summary"], [space_dir, self._cutoff(days)])
        return {row[0]: row[1] for row in rs.rows}

    async def failed_code_concepts(
        self, space_dir: str, threshold: int = 3, days: int = 30
    ) -> list[str]:
        client = await self._get_client()
        rs = await client.execute(
            _Q["failed_code_concepts"], [space_dir, self._cutoff(days), threshold]
        )
        return [row[0] for row in rs.rows]

    async def concepts_touched(self, space_dir: str, days: int = 14) -> list[str]:
        client = await self._get_client()
        rs = await client.execute(
            _Q["concepts_touched"], [space_dir, self._cutoff(days)]
        )
        return [row[0] for row in rs.rows]

    async def recent_media_notes(self, space_dir: str, days: int = 14) -> list[dict]:
        client = await self._get_client()
        rs = await client.execute(
            _Q["recent_media_notes"], [space_dir, self._cutoff(days)]
        )
        return [dict(zip(rs.columns, row)) for row in rs.rows]
