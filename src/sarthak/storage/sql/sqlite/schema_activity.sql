-- SQLite user_activity table schema
-- Applied by SQLiteActivityRepo on first connection.
-- This is the canonical definition — do not duplicate in db.py.

PRAGMA journal_mode=WAL;
PRAGMA synchronous=NORMAL;

CREATE TABLE IF NOT EXISTS user_activity (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    ts            TEXT    NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')),
    activity_type TEXT    NOT NULL,
    space_dir     TEXT    NOT NULL DEFAULT '',
    concept_id    TEXT    NOT NULL DEFAULT '',
    concept_title TEXT    NOT NULL DEFAULT '',
    session_id    TEXT    NOT NULL DEFAULT '',
    content_text  TEXT    NOT NULL DEFAULT '',
    media_path    TEXT    NOT NULL DEFAULT '',
    metadata      TEXT    NOT NULL DEFAULT '{}'
);

CREATE INDEX IF NOT EXISTS ua_ts        ON user_activity (ts DESC);
CREATE INDEX IF NOT EXISTS ua_space_ts  ON user_activity (space_dir, ts DESC);
CREATE INDEX IF NOT EXISTS ua_concept   ON user_activity (space_dir, concept_title);
CREATE INDEX IF NOT EXISTS ua_concept_ts ON user_activity (space_dir, concept_title, ts DESC);
CREATE INDEX IF NOT EXISTS ua_type      ON user_activity (space_dir, activity_type, ts DESC);

-- Safe migration: add session_id index if missing (helps chat/session lookups)
CREATE INDEX IF NOT EXISTS ua_session   ON user_activity (session_id, ts DESC);
