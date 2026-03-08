"""
Sarthak AI — Global SQLite database.

Single file at ~/.sarthak_ai/sarthak.db.
Tables: chat_history, alerts, daily_summaries, ai_model_log, user_activity

All helpers are async via aiosqlite.
The DB path is resolved from the environment/config.
"""
from __future__ import annotations

from pathlib import Path
from contextlib import asynccontextmanager
from typing import AsyncIterator

import aiosqlite

_SCHEMA = """
PRAGMA journal_mode=WAL;
PRAGMA foreign_keys=ON;

CREATE TABLE IF NOT EXISTS chat_history (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id  TEXT    NOT NULL,
    ts          TEXT    NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')),
    role        TEXT    NOT NULL CHECK(role IN ('user','assistant')),
    content     TEXT    NOT NULL
);
CREATE INDEX IF NOT EXISTS chat_history_session_ts
    ON chat_history (session_id, ts DESC);

CREATE TABLE IF NOT EXISTS alerts (
    id      INTEGER PRIMARY KEY AUTOINCREMENT,
    ts      TEXT    NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')),
    level   TEXT    NOT NULL,
    source  TEXT    NOT NULL,
    message TEXT    NOT NULL,
    details TEXT    NOT NULL DEFAULT '{}',
    read    INTEGER NOT NULL DEFAULT 0
);
CREATE INDEX IF NOT EXISTS alerts_ts ON alerts (ts DESC);

CREATE TABLE IF NOT EXISTS daily_summaries (
    date            TEXT PRIMARY KEY,
    summary         TEXT NOT NULL,
    top_apps        TEXT NOT NULL DEFAULT '[]',
    productive_mins INTEGER NOT NULL DEFAULT 0,
    idle_mins       INTEGER NOT NULL DEFAULT 0,
    model_used      TEXT NOT NULL DEFAULT '',
    generated_at    TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now'))
);

CREATE TABLE IF NOT EXISTS saved_tips (
    id   INTEGER PRIMARY KEY AUTOINCREMENT,
    ts   TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')),
    tip  TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS user_activity (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    ts           TEXT    NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')),
    space_dir    TEXT    NOT NULL DEFAULT '',
    activity_type TEXT   NOT NULL,  -- 'audio_note'|'video_note'|'code_run'|'chat'|'file_upload'|'practice_test'|'quicktest'|'note'
    concept_id   TEXT    NOT NULL DEFAULT '',
    concept_title TEXT   NOT NULL DEFAULT '',
    session_id   TEXT    NOT NULL DEFAULT '',
    content_text TEXT    NOT NULL DEFAULT '',  -- transcript / code / message / note body
    media_path   TEXT    NOT NULL DEFAULT '',  -- path to audio/video blob on disk
    metadata     TEXT    NOT NULL DEFAULT '{}' -- JSON: duration_s, score, language, etc.
);
CREATE INDEX IF NOT EXISTS user_activity_space_ts   ON user_activity (space_dir, ts DESC);
CREATE INDEX IF NOT EXISTS user_activity_type_ts    ON user_activity (activity_type, ts DESC);
CREATE INDEX IF NOT EXISTS user_activity_concept    ON user_activity (concept_title, ts DESC);

CREATE TABLE IF NOT EXISTS ai_model_log (
    id                 INTEGER PRIMARY KEY AUTOINCREMENT,
    ts                 TEXT    NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')),
    agent              TEXT    NOT NULL DEFAULT '',
    requested_provider TEXT    NOT NULL DEFAULT '',
    requested_model    TEXT    NOT NULL DEFAULT '',
    actual_provider    TEXT    NOT NULL DEFAULT '',
    actual_model       TEXT    NOT NULL DEFAULT '',
    fallback_used      INTEGER NOT NULL DEFAULT 0,
    fallback_slot      INTEGER,
    prompt_tokens      INTEGER NOT NULL DEFAULT 0,
    completion_tokens  INTEGER NOT NULL DEFAULT 0,
    latency_ms         INTEGER NOT NULL DEFAULT 0,
    error              TEXT,
    session_id         TEXT
);
CREATE INDEX IF NOT EXISTS ai_model_log_ts    ON ai_model_log (ts DESC);
CREATE INDEX IF NOT EXISTS ai_model_log_agent ON ai_model_log (agent, ts DESC);
"""

_INIT_DONE = False


def _db_path() -> Path:
    import os
    env = os.environ.get("SARTHAK_DB", "").strip()
    if env:
        return Path(env)
    base = Path.home() / ".sarthak_ai"
    base.mkdir(parents=True, exist_ok=True)
    return base / "sarthak.db"


async def init_db() -> None:
    """Create tables if they don't exist. Idempotent."""
    global _INIT_DONE
    if _INIT_DONE:
        return
    async with aiosqlite.connect(_db_path()) as db:
        await db.executescript(_SCHEMA)
        await db.commit()
    _INIT_DONE = True  # set only after commit to avoid racing callers


async def _connect() -> aiosqlite.Connection:
    """Open a connection, ensuring schema exists first."""
    await init_db()
    conn = await aiosqlite.connect(_db_path())
    conn.row_factory = aiosqlite.Row
    return conn


@asynccontextmanager
async def connect() -> AsyncIterator[aiosqlite.Connection]:
    """Async context manager for a DB connection."""
    conn = await _connect()
    try:
        yield conn
    finally:
        await conn.close()
