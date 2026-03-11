-- PGVector schema for RAG vector store
-- Applied by PGVectorRepo on pool init.
-- Requires: CREATE EXTENSION IF NOT EXISTS vector;

CREATE EXTENSION IF NOT EXISTS vector;

CREATE TABLE IF NOT EXISTS chunks (
    id       TEXT PRIMARY KEY,
    source   TEXT NOT NULL,
    chunk    INTEGER NOT NULL DEFAULT 0,
    line     INTEGER NOT NULL DEFAULT 1,
    text     TEXT NOT NULL,
    embedding vector  -- dimension set on first insert; ALTER TABLE adds column
);

CREATE INDEX IF NOT EXISTS chunks_source ON chunks (source);

-- Full-text search using PostgreSQL tsvector
ALTER TABLE chunks ADD COLUMN IF NOT EXISTS ts_text TSVECTOR
    GENERATED ALWAYS AS (to_tsvector('english', text)) STORED;

CREATE INDEX IF NOT EXISTS chunks_fts ON chunks USING GIN (ts_text);

-- IVFFlat index created after first batch insert (requires rows to exist)
-- Run manually after initial indexing:
--   CREATE INDEX ON chunks USING ivfflat (embedding vector_cosine_ops) WITH (lists = 100);
