-- Sarthak AI — Global SQLite schema
-- File: ~/.sarthak_ai/sarthak.db
-- Tables: chat_history, alerts, daily_summaries, saved_tips, ai_model_log
-- user_activity is in schema_activity.sql (applied by SQLiteActivityRepo)

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

-- Space memory distillation log (weekly digest events per space)
CREATE TABLE IF NOT EXISTS space_memory_log (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    ts         TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')),
    space_dir  TEXT NOT NULL,
    event      TEXT NOT NULL,  -- 'distill' | 'heartbeat' | 'init'
    detail     TEXT NOT NULL DEFAULT ''
);
CREATE INDEX IF NOT EXISTS sml_space_ts ON space_memory_log (space_dir, ts DESC);
