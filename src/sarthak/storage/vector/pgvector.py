"""
PGVectorRepo — PostgreSQL pgvector EmbeddingRepository.

Schema:  storage/sql/vector/schema_pgvector.sql
Requires: pip install asyncpg pgvector
Config:
    [storage.postgres]
    url = "postgresql://user:pass@localhost:5432/sarthak"

    [storage.pgvector]
    table_prefix = "sarthak"   # optional, avoids collisions in shared PG instance

Reuses the Postgres connection pool from PostgresActivityRepo when possible.
Each space gets its own chunks table named: <prefix>_<space_slug>_chunks
"""
from __future__ import annotations

import asyncio
import hashlib
import json
from pathlib import Path
from typing import Any

import structlog

from sarthak.storage.sql_loader import load_schema

log = structlog.get_logger(__name__)

_SCHEMA_TPL = load_schema("vector", "schema_pgvector")

# Global pool cache: url → asyncpg Pool
_pools: dict[str, Any] = {}
_pool_lock = asyncio.Lock()


def _space_table(prefix: str, space_dir: Path) -> str:
    """Stable table name from space path — max 63 chars (PG limit)."""
    slug = space_dir.name.lower().replace(" ", "_")[:24]
    h = hashlib.sha1(str(space_dir.resolve()).encode()).hexdigest()[:8]
    return f"{prefix}_{slug}_{h}_chunks"


async def _get_pool(url: str) -> Any:
    async with _pool_lock:
        if url not in _pools:
            import asyncpg  # type: ignore
            _pools[url] = await asyncpg.create_pool(
                dsn=url, min_size=1, max_size=5, command_timeout=30
            )
            log.info("pgvector_pool_created", url=url)
    return _pools[url]


class PGVectorRepo:
    """EmbeddingRepository backed by PostgreSQL + pgvector."""

    def __init__(
        self,
        space_dir: Path | str,
        url: str,
        table_prefix: str = "sarthak",
    ) -> None:
        self._space_dir = Path(space_dir)
        self._url = url
        self._table = _space_table(table_prefix, self._space_dir)
        self._initialized = False
        self._init_lock = asyncio.Lock()

    async def _pool(self) -> Any:
        return await _get_pool(self._url)

    async def _init_table(self, conn: Any, dim: int) -> None:
        if self._initialized:
            return
        async with self._init_lock:
            if self._initialized:   # double-checked
                return
            # Enable extension + create table with correct vector dimension
            await conn.execute("CREATE EXTENSION IF NOT EXISTS vector")
            await conn.execute(f"""
                CREATE TABLE IF NOT EXISTS {self._table} (
                    id       TEXT PRIMARY KEY,
                    source   TEXT NOT NULL,
                    chunk    INTEGER NOT NULL DEFAULT 0,
                    line     INTEGER NOT NULL DEFAULT 1,
                    text     TEXT NOT NULL,
                    embedding vector({dim})
                )
            """)
            await conn.execute(
                f"CREATE INDEX IF NOT EXISTS {self._table}_source "
                f"ON {self._table} (source)"
            )
            await conn.execute(
                f"CREATE INDEX IF NOT EXISTS {self._table}_fts "
                f"ON {self._table} USING GIN (to_tsvector('english', text))"
            )
            self._initialized = True
            log.info("pgvector_table_ready", table=self._table, dim=dim)

    async def upsert(self, chunks: list[dict], embeddings: list[list[float]]) -> None:
        if not chunks:
            return
        pool = await self._pool()
        dim = len(embeddings[0])
        async with pool.acquire() as conn:
            await self._init_table(conn, dim)
            await conn.executemany(
                f"""
                INSERT INTO {self._table} (id, source, chunk, line, text, embedding)
                VALUES ($1, $2, $3, $4, $5, $6::vector)
                ON CONFLICT (id) DO UPDATE SET
                    source=EXCLUDED.source, chunk=EXCLUDED.chunk,
                    line=EXCLUDED.line, text=EXCLUDED.text,
                    embedding=EXCLUDED.embedding
                """,
                [
                    (c["id"], c["source"], c.get("chunk", 0), c.get("line", 1),
                     c["text"], json.dumps(e))
                    for c, e in zip(chunks, embeddings)
                ],
            )
        log.debug("pgvector_upserted", table=self._table, count=len(chunks))

    async def delete_source(self, source: str) -> None:
        pool = await self._pool()
        async with pool.acquire() as conn:
            await conn.execute(
                f"DELETE FROM {self._table} WHERE source = $1", source
            )

    async def search(self, query_vec: list[float], top_k: int = 5) -> list[dict]:
        pool = await self._pool()
        vec_str = json.dumps(query_vec)
        async with pool.acquire() as conn:
            rows = await conn.fetch(
                f"""
                SELECT id, source, chunk, line, text,
                       embedding <=> $1::vector AS distance
                FROM {self._table}
                ORDER BY distance
                LIMIT $2
                """,
                vec_str, top_k,
            )
        return [dict(r) for r in rows]

    async def fts_search(self, query: str, top_k: int = 5) -> list[tuple[str, float]]:
        pool = await self._pool()
        async with pool.acquire() as conn:
            rows = await conn.fetch(
                f"""
                SELECT id, ts_rank(to_tsvector('english', text),
                                   plainto_tsquery('english', $1)) AS score
                FROM {self._table}
                WHERE to_tsvector('english', text) @@ plainto_tsquery('english', $1)
                ORDER BY score DESC
                LIMIT $2
                """,
                query, top_k,
            )
        return [(r["id"], float(r["score"])) for r in rows]

    def status(self) -> dict:
        return {"enabled": True, "backend": "pgvector", "table": self._table}
