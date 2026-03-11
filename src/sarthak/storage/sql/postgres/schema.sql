-- PostgreSQL user_activity schema
-- Applied by PostgresActivityRepo on pool init.
-- Uses JSONB for metadata (superior indexing vs TEXT).

CREATE TABLE IF NOT EXISTS user_activity (
    id             BIGSERIAL PRIMARY KEY,
    ts             TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    activity_type  TEXT NOT NULL,
    space_dir      TEXT NOT NULL DEFAULT '',
    concept_id     TEXT NOT NULL DEFAULT '',
    concept_title  TEXT NOT NULL DEFAULT '',
    session_id     TEXT NOT NULL DEFAULT '',
    content_text   TEXT NOT NULL DEFAULT '',
    media_path     TEXT NOT NULL DEFAULT '',
    metadata       JSONB NOT NULL DEFAULT '{}'::jsonb
);

CREATE INDEX IF NOT EXISTS ua_ts        ON user_activity (ts DESC);
CREATE INDEX IF NOT EXISTS ua_space_ts  ON user_activity (space_dir, ts DESC);
CREATE INDEX IF NOT EXISTS ua_concept   ON user_activity (space_dir, concept_title);
CREATE INDEX IF NOT EXISTS ua_type      ON user_activity (space_dir, activity_type, ts DESC);
-- GIN index on metadata JSONB for fast key lookups
CREATE INDEX IF NOT EXISTS ua_metadata  ON user_activity USING GIN (metadata);

CREATE TABLE IF NOT EXISTS chat_history (
    id         BIGSERIAL PRIMARY KEY,
    session_id TEXT NOT NULL,
    ts         TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    role       TEXT NOT NULL CHECK(role IN ('user','assistant')),
    content    TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS ch_session_ts ON chat_history (session_id, ts ASC);
