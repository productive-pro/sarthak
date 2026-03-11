-- sqlite-vec schema for RAG vector store
-- Applied by SqliteVecRepo on connection init.
-- The vec0 virtual table is created lazily on first upsert (dimension unknown until then).

PRAGMA journal_mode=WAL;
PRAGMA synchronous=NORMAL;

-- Chunk metadata and text (source of truth for text content)
CREATE TABLE IF NOT EXISTS chunks (
    id       TEXT PRIMARY KEY,
    source   TEXT NOT NULL,
    chunk    INTEGER NOT NULL DEFAULT 0,
    line     INTEGER NOT NULL DEFAULT 1,
    text     TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS chunks_source ON chunks (source);

-- FTS5 virtual table for BM25 full-text search
-- Mirrors chunks content; kept in sync via triggers below.
CREATE VIRTUAL TABLE IF NOT EXISTS chunks_fts USING fts5(
    id UNINDEXED,
    text,
    content=chunks,
    content_rowid=rowid
);

-- Triggers: keep FTS5 in sync with chunks DML
CREATE TRIGGER IF NOT EXISTS chunks_ai AFTER INSERT ON chunks BEGIN
    INSERT INTO chunks_fts(rowid, id, text) VALUES (new.rowid, new.id, new.text);
END;

CREATE TRIGGER IF NOT EXISTS chunks_ad AFTER DELETE ON chunks BEGIN
    INSERT INTO chunks_fts(chunks_fts, rowid, id, text)
        VALUES ('delete', old.rowid, old.id, old.text);
END;

CREATE TRIGGER IF NOT EXISTS chunks_au AFTER UPDATE ON chunks BEGIN
    INSERT INTO chunks_fts(chunks_fts, rowid, id, text)
        VALUES ('delete', old.rowid, old.id, old.text);
    INSERT INTO chunks_fts(rowid, id, text) VALUES (new.rowid, new.id, new.text);
END;

-- NOTE: vec0 virtual table created lazily by SqliteVecRepo._ensure_vec_table(dim)
-- once the embedding dimension is known at first upsert.
-- Pattern: CREATE VIRTUAL TABLE vecs_{dim} USING vec0(id TEXT PRIMARY KEY, embedding float[{dim}])
