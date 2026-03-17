"""
SqliteVecRepo — sqlite-vec + FTS5 EmbeddingRepository.

Schema:  storage/sql/vector/schema_sqlite_vec.sql
All SQL is loaded from the .sql file — no inline DDL here.

Storage layout per space:
    <space_dir>/.spaces/rag/sarthak.vec

Design:
  - One shared aiosqlite connection per space_dir (long-lived pool).
  - Per-space asyncio.Lock serialises all writes.
  - vec0 virtual table created lazily on first upsert (dimension unknown until then).
  - FTS5 kept in sync via triggers defined in the schema SQL file.
"""
from __future__ import annotations

import asyncio
import struct
from pathlib import Path
from typing import Any

import structlog

from sarthak.storage.sql_loader import load_schema

log = structlog.get_logger(__name__)

_SCHEMA = load_schema("vector", "schema_sqlite_vec")

# Per-space connection pool: resolved_path → (conn, asyncio.Lock, vec_loaded)
_conn_pool: dict[str, tuple[Any, asyncio.Lock, list[bool]]] = {}
_pool_lock = asyncio.Lock()


def _db_path(space_dir: Path) -> Path:
    d = space_dir / ".spaces" / "rag"
    d.mkdir(parents=True, exist_ok=True)
    return d / "sarthak.vec"


def _encode_f32(vec: list[float]) -> bytes:
    return struct.pack(f"{len(vec)}f", *vec)


def _vec_table(dim: int) -> str:
    return f"vecs_{dim}"


async def _load_sqlite_vec_async(conn: Any) -> None:
    """Load sqlite-vec extension inside aiosqlite's worker thread via execute()."""
    try:
        import sqlite_vec  # type: ignore

        def _do_load(raw_conn: Any) -> None:
            raw_conn.enable_load_extension(True)
            sqlite_vec.load(raw_conn)
            raw_conn.enable_load_extension(False)

        # aiosqlite._execute runs the callable inside its own thread where the
        # raw connection lives — this is the only safe way to load extensions.
        await conn._execute(_do_load, conn._conn)
    except Exception as exc:
        log.warning("sqlite_vec_load_failed", error=str(exc),
                    hint="pip install sqlite-vec")


async def _migrate_legacy_vec_table(conn: Any) -> None:
    """Rename legacy 'vec_chunks' table to 'vecs_2560' if it exists and new name doesn't."""
    async with conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name='vec_chunks'"
    ) as cur:
        has_legacy = await cur.fetchone()
    if not has_legacy:
        return

    # Determine the dimension from the legacy table schema
    async with conn.execute(
        "SELECT sql FROM sqlite_master WHERE name='vec_chunks'"
    ) as cur:
        row = await cur.fetchone()
    if not row:
        return

    # Extract dimension from: vec0(id TEXT PRIMARY KEY, embedding float[2560])
    import re
    m = re.search(r"float\[(\d+)\]", row[0])
    if not m:
        return
    dim = int(m.group(1))
    new_name = _vec_table(dim)

    async with conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name=?", (new_name,)
    ) as cur:
        has_new = await cur.fetchone()
    if has_new:
        return  # already migrated

    # sqlite-vec virtual tables cannot be renamed with ALTER TABLE — must drop & recreate.
    # We copy ids+embeddings via a temp table, then recreate under the new name.
    # This requires the vec0 extension to be loaded first.
    log.info("sqlite_vec_migrating_legacy_table", from_table="vec_chunks", to_table=new_name, dim=dim)
    # Extension must already be loaded by caller (_ensure_vec_table handles this)
    # For migration we just record the rename in sqlite_master by re-creating.
    # Since vec0 virtual tables store data in shadow tables, we collect all rows first.
    try:
        async with conn.execute(f"SELECT id, embedding FROM vec_chunks") as cur:
            rows = await cur.fetchall()
    except Exception as exc:
        log.warning("sqlite_vec_migration_read_failed", error=str(exc))
        return

    # Create new table and copy data
    await conn.execute(
        f"CREATE VIRTUAL TABLE IF NOT EXISTS {new_name} "
        f"USING vec0(id TEXT PRIMARY KEY, embedding float[{dim}])"
    )
    if rows:
        await conn.executemany(
            f"INSERT OR REPLACE INTO {new_name} (id, embedding) VALUES (?, ?)",
            [(r[0], r[1]) for r in rows],
        )
    await conn.commit()
    log.info("sqlite_vec_migration_done", table=new_name, rows=len(rows))


async def _get_conn(space_dir: Path) -> tuple[Any, asyncio.Lock, list[bool]]:
    key = str(space_dir.resolve())
    async with _pool_lock:
        if key not in _conn_pool:
            import aiosqlite
            conn = await aiosqlite.connect(str(_db_path(space_dir)))
            conn.row_factory = aiosqlite.Row
            await conn.executescript(_SCHEMA)
            await conn.commit()
            vec_loaded = [False]  # mutable flag shared across calls
            _conn_pool[key] = (conn, asyncio.Lock(), vec_loaded)
            log.debug("sqlite_vec_conn_opened", space=key)
    return _conn_pool[key]


async def _ensure_vec_table(conn: Any, vec_loaded: list[bool], dim: int) -> str:
    table = _vec_table(dim)
    if not vec_loaded[0]:
        await _load_sqlite_vec_async(conn)
        vec_loaded[0] = True
        # Migrate legacy 'vec_chunks' table now that the extension is loaded
        await _migrate_legacy_vec_table(conn)
    async with conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name=?", (table,)
    ) as cur:
        if not await cur.fetchone():
            await conn.execute(
                f"CREATE VIRTUAL TABLE IF NOT EXISTS {table} "
                f"USING vec0(id TEXT PRIMARY KEY, embedding float[{dim}])"
            )
            await conn.commit()
            log.debug("sqlite_vec_table_created", table=table, dim=dim)
    return table


class SqliteVecRepo:
    """EmbeddingRepository backed by sqlite-vec + FTS5."""

    def __init__(self, space_dir: Path | str) -> None:
        self._space_dir = Path(space_dir)

    async def _cl(self) -> tuple[Any, asyncio.Lock, list[bool]]:
        return await _get_conn(self._space_dir)

    async def upsert(self, chunks: list[dict], embeddings: list[list[float]]) -> None:
        if not chunks or not embeddings:
            return
        if len(chunks) != len(embeddings):
            raise ValueError("chunks and embeddings must have the same length")
        conn, lock, vec_loaded = await self._cl()
        dim = len(embeddings[0])
        table = await _ensure_vec_table(conn, vec_loaded, dim)
        async with lock:
            await conn.executemany(
                "INSERT OR REPLACE INTO chunks (id, source, chunk, line, text) "
                "VALUES (:id, :source, :chunk, :line, :text)",
                chunks,
            )
            await conn.executemany(f"DELETE FROM {table} WHERE id = ?", [(c["id"],) for c in chunks])
            await conn.executemany(
                f"INSERT INTO {table} (id, embedding) VALUES (?, ?)",
                [(c["id"], _encode_f32(e)) for c, e in zip(chunks, embeddings)],
            )
            await conn.commit()
        log.debug("sqlite_vec_upserted", space=str(self._space_dir), count=len(chunks))

    async def delete_source(self, source: str) -> None:
        conn, lock, _ = await self._cl()
        async with lock:
            async with conn.execute(
                "SELECT id FROM chunks WHERE source=?", (source,)
            ) as cur:
                ids = [r["id"] for r in await cur.fetchall()]
            if not ids:
                return
            await conn.execute("DELETE FROM chunks WHERE source=?", (source,))
            async with conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name LIKE 'vecs_%'"
            ) as cur:
                tables = [r["name"] for r in await cur.fetchall()]
            for t in tables:
                ph = ",".join("?" * len(ids))
                await conn.execute(f"DELETE FROM {t} WHERE id IN ({ph})", ids)
            await conn.commit()

    async def search(self, query_vec: list[float], top_k: int = 5) -> list[dict]:
        conn, _, vec_loaded = await self._cl()
        dim = len(query_vec)
        # Load extension + migrate legacy table if not done yet
        table = await _ensure_vec_table(conn, vec_loaded, dim)
        async with conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name=?", (table,)
        ) as cur:
            if not await cur.fetchone():
                return []
        q_blob = _encode_f32(query_vec)
        async with conn.execute(
            f"""
            SELECT v.id, v.distance, c.source, c.line, c.chunk, c.text
            FROM {table} v
            JOIN chunks c ON c.id = v.id
            WHERE v.embedding MATCH ? AND k = ?
            ORDER BY v.distance
            """,
            (q_blob, top_k),
        ) as cur:
            rows = await cur.fetchall()
        return [dict(r) for r in rows]

    async def fts_search(self, query: str, top_k: int = 5) -> list[tuple[str, float]]:
        conn, _, _ = await self._cl()
        import re
        safe = re.sub(r'[^\w\s]', ' ', query)
        try:
            # SQLite FTS5 bm25() returns negative values (lower = more relevant).
            # Negate so callers receive positive scores where higher = better.
            async with conn.execute(
                "SELECT id, -bm25(chunks_fts) AS score FROM chunks_fts "
                "WHERE chunks_fts MATCH ? ORDER BY score DESC LIMIT ?",
                (safe, top_k),
            ) as cur:
                rows = await cur.fetchall()
            return [(r["id"], r["score"]) for r in rows]
        except Exception as exc:
            log.debug("sqlite_vec_fts_failed", error=str(exc))
            return []

    def status(self) -> dict:
        db_file = _db_path(self._space_dir)
        if not db_file.exists():
            return {"enabled": False, "indexed_chunks": 0,
                    "db_path": str(db_file), "db_size_kb": 0}
        size_kb = db_file.stat().st_size // 1024
        try:
            import sqlite3
            with sqlite3.connect(str(db_file)) as raw:
                count = raw.execute("SELECT COUNT(*) FROM chunks").fetchone()[0]
        except Exception:
            count = 0
        return {"enabled": True, "indexed_chunks": count,
                "db_path": str(db_file), "db_size_kb": size_kb}
