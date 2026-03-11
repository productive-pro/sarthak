-- LibSQL / Turso schema for user_activity
-- Wire-compatible with SQLite; identical DDL.
-- Applied by LibSQLActivityRepo on first connection.

PRAGMA journal_mode=WAL;

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
CREATE INDEX IF NOT EXISTS ua_type      ON user_activity (space_dir, activity_type, ts DESC);

CREATE TABLE IF NOT EXISTS chat_history (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id  TEXT    NOT NULL,
    ts          TEXT    NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')),
    role        TEXT    NOT NULL CHECK(role IN ('user','assistant')),
    content     TEXT    NOT NULL
);
CREATE INDEX IF NOT EXISTS ch_session_ts ON chat_history (session_id, ts ASC);
