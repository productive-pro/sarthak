-- DuckDB user_activity schema
-- Applied by DuckDBActivityRepo on first connection.
-- Uses VARCHAR (DuckDB TEXT equivalent) and JSON type.

CREATE TABLE IF NOT EXISTS user_activity (
    id            BIGINT PRIMARY KEY,
    ts            TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    activity_type VARCHAR NOT NULL,
    space_dir     VARCHAR NOT NULL DEFAULT '',
    concept_id    VARCHAR NOT NULL DEFAULT '',
    concept_title VARCHAR NOT NULL DEFAULT '',
    session_id    VARCHAR NOT NULL DEFAULT '',
    content_text  VARCHAR NOT NULL DEFAULT '',
    media_path    VARCHAR NOT NULL DEFAULT '',
    metadata      JSON NOT NULL DEFAULT '{}'
);

CREATE SEQUENCE IF NOT EXISTS user_activity_id_seq;

CREATE INDEX IF NOT EXISTS ua_space_ts ON user_activity (space_dir, ts DESC);
CREATE INDEX IF NOT EXISTS ua_type     ON user_activity (space_dir, activity_type);
