"""
PostgreSQL ActivityRepository implementation.

Schema:  storage/sql/postgres/schema.sql
Queries: storage/sql/postgres/queries.sql

Requires: pip install asyncpg
Config:
    [storage.postgres]
    url       = "postgresql://user:pass@localhost:5432/sarthak"
    pool_size = 5
"""
from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from typing import Any

import structlog

from sarthak.storage.sql_loader import load_schema, load_queries

log = structlog.get_logger(__name__)

_SCHEMA = load_schema("postgres", "schema")
_Q = load_queries("postgres", "queries")


class PostgresActivityRepo:
    """ActivityRepository backed by PostgreSQL via asyncpg."""

    def __init__(self, url: str, pool_size: int = 5) -> None:
        import asyncio
        self._url = url
        self._pool_size = pool_size
        self._pool: Any = None
        self._init_lock: asyncio.Lock = asyncio.Lock()

    async def _get_pool(self) -> Any:
        if self._pool is not None:
            return self._pool
        async with self._init_lock:
            if self._pool is None:
                import asyncpg  # type: ignore
                self._pool = await asyncpg.create_pool(
                    dsn=self._url,
                    min_size=1,
                    max_size=self._pool_size,
                    command_timeout=30,
                )
                async with self._pool.acquire() as conn:
                    await conn.execute(_SCHEMA)
                log.info("postgres_pool_created", url=self._url, pool_size=self._pool_size)
        return self._pool

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
        pool = await self._get_pool()
        async with pool.acquire() as conn:
            row = await conn.fetchrow(
                _Q["insert_activity"],
                activity_type, space_dir, concept_id, concept_title,
                session_id, content_text, media_path,
                json.dumps(metadata or {}),
            )
        return row["id"]

    async def query(
        self,
        *,
        space_dir: str = "",
        activity_type: str | None = None,
        concept_title: str = "",
        days: int = 30,
        limit: int = 200,
    ) -> list[dict]:
        pool = await self._get_pool()
        cutoff = self._cutoff(days)
        clauses = ["ts >= $1"]
        params: list[Any] = [cutoff]
        n = 2
        if space_dir:
            clauses.append(f"space_dir = ${n}"); params.append(space_dir); n += 1
        if activity_type:
            clauses.append(f"activity_type = ${n}"); params.append(activity_type); n += 1
        if concept_title:
            clauses.append(f"concept_title = ${n}"); params.append(concept_title); n += 1
        params.append(limit)
        where = " AND ".join(clauses)
        async with pool.acquire() as conn:
            rows = await conn.fetch(
                f"SELECT * FROM user_activity WHERE {where} ORDER BY ts DESC LIMIT ${n}",
                *params,
            )
        return [dict(r) for r in rows]

    async def summary(self, space_dir: str, days: int = 7) -> dict:
        pool = await self._get_pool()
        async with pool.acquire() as conn:
            rows = await conn.fetch(_Q["summary"], space_dir, self._cutoff(days))
        return {r["activity_type"]: r["cnt"] for r in rows}

    async def failed_code_concepts(
        self, space_dir: str, threshold: int = 3, days: int = 30
    ) -> list[str]:
        pool = await self._get_pool()
        async with pool.acquire() as conn:
            rows = await conn.fetch(
                _Q["failed_code_concepts"], space_dir, self._cutoff(days), threshold
            )
        return [r["concept_title"] for r in rows]

    async def concepts_touched(self, space_dir: str, days: int = 14) -> list[str]:
        pool = await self._get_pool()
        async with pool.acquire() as conn:
            rows = await conn.fetch(
                _Q["concepts_touched"], space_dir, self._cutoff(days)
            )
        return [r["concept_title"] for r in rows]

    async def recent_media_notes(self, space_dir: str, days: int = 14) -> list[dict]:
        pool = await self._get_pool()
        async with pool.acquire() as conn:
            rows = await conn.fetch(
                _Q["recent_media_notes"], space_dir, self._cutoff(days)
            )
        return [dict(r) for r in rows]
