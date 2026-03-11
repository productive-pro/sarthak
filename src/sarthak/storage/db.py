"""
Sarthak AI — Global SQLite database.

Single file at ~/.sarthak_ai/sarthak.db.
Schema is the single source of truth in:
  storage/sql/sqlite/schema_global.sql  — chat, alerts, summaries, ai_model_log
  storage/sql/sqlite/schema_activity.sql — user_activity (applied by SQLiteActivityRepo)

All helpers are async via aiosqlite.
"""
from __future__ import annotations

import asyncio
from pathlib import Path
from contextlib import asynccontextmanager
from typing import AsyncIterator

import aiosqlite

from sarthak.storage.sql_loader import load_schema

_GLOBAL_CONN: aiosqlite.Connection | None = None
_GLOBAL_CONN_LOCK = asyncio.Lock()
_INIT_DONE = False


def _db_path() -> Path:
    import os
    env = os.environ.get("SARTHAK_DB", "").strip()
    if env:
        return Path(env)
    base = Path.home() / ".sarthak_ai"
    base.mkdir(parents=True, exist_ok=True)
    return base / "sarthak.db"


async def _open_conn() -> aiosqlite.Connection:
    """Open and configure a new aiosqlite connection (no lock required)."""
    conn = await aiosqlite.connect(str(_db_path()))
    conn.row_factory = aiosqlite.Row
    await conn.execute("PRAGMA journal_mode=WAL")
    await conn.execute("PRAGMA synchronous=NORMAL")
    await conn.execute("PRAGMA foreign_keys=ON")
    await conn.execute("PRAGMA cache_size=-8000")  # 8MB page cache
    return conn


async def _get_global_conn() -> aiosqlite.Connection:
    """Return the long-lived global DB connection, creating it if needed."""
    global _GLOBAL_CONN
    if _GLOBAL_CONN is not None:
        return _GLOBAL_CONN
    async with _GLOBAL_CONN_LOCK:
        if _GLOBAL_CONN is None:
            _GLOBAL_CONN = await _open_conn()
    return _GLOBAL_CONN


async def init_db() -> None:
    """Create global tables if they don't exist. Idempotent."""
    global _INIT_DONE, _GLOBAL_CONN
    if _INIT_DONE:
        return
    async with _GLOBAL_CONN_LOCK:
        if _INIT_DONE:
            return
        # Open connection directly (without re-acquiring the lock via _get_global_conn)
        if _GLOBAL_CONN is None:
            _GLOBAL_CONN = await _open_conn()
        schema = load_schema("sqlite", "schema_global")
        await _GLOBAL_CONN.executescript(schema)
        await _GLOBAL_CONN.commit()
        _INIT_DONE = True


@asynccontextmanager
async def connect() -> AsyncIterator[aiosqlite.Connection]:
    """Async context manager yielding the global DB connection.

    Uses a persistent connection (not a new one per call) for efficiency.
    Callers are responsible for their own write serialization if needed.
    """
    await init_db()
    yield await _get_global_conn()


async def close_db() -> None:
    """Gracefully close the global connection (call at process shutdown)."""
    global _GLOBAL_CONN, _INIT_DONE
    async with _GLOBAL_CONN_LOCK:
        if _GLOBAL_CONN is not None:
            try:
                await _GLOBAL_CONN.close()
            except Exception:
                pass
            _GLOBAL_CONN = None
            _INIT_DONE = False
