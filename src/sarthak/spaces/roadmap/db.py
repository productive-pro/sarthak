"""
Sarthak Spaces — SQLite persistence for Roadmap System.

One DB per space: .spaces/<n>/sarthak.db
Tables: roadmap (JSON blob), notes, quicktests, files
Audio/video blobs: .spaces/<n>/media/<id>.<ext> (path stored in DB)
"""

from __future__ import annotations

import asyncio
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import aiosqlite

from .models import (
    FileLink,
    LinkedTarget,
    NoteRow,
    QuickTestRow,
    Roadmap,
)

_SCHEMA = """
PRAGMA journal_mode=WAL;
PRAGMA synchronous=NORMAL;
PRAGMA foreign_keys=ON;

CREATE TABLE IF NOT EXISTS roadmap (
    id      INTEGER PRIMARY KEY CHECK (id = 1),
    blob    TEXT    NOT NULL,
    updated TEXT    NOT NULL
);

CREATE TABLE IF NOT EXISTS notes (
    id          TEXT PRIMARY KEY,
    chapter_id  TEXT NOT NULL DEFAULT '',
    topic_id    TEXT NOT NULL DEFAULT '',
    concept_id  TEXT NOT NULL DEFAULT '',
    title       TEXT NOT NULL DEFAULT '',
    body_md     TEXT NOT NULL DEFAULT '',
    type        TEXT NOT NULL DEFAULT 'note',
    audio_path  TEXT,
    video_path  TEXT,
    created_at  TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS quicktests (
    id          TEXT PRIMARY KEY,
    chapter_id  TEXT NOT NULL DEFAULT '',
    topic_id    TEXT NOT NULL DEFAULT '',
    concept_id  TEXT NOT NULL DEFAULT '',
    prompt      TEXT NOT NULL DEFAULT '',
    response_md TEXT NOT NULL DEFAULT '',
    input_mode  TEXT NOT NULL DEFAULT 'user',
    created_at  TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS files (
    id         TEXT PRIMARY KEY,
    path       TEXT NOT NULL UNIQUE,
    linked_to  TEXT NOT NULL DEFAULT '[]'
);

CREATE TABLE IF NOT EXISTS digest_cache (
    space   TEXT NOT NULL DEFAULT '',
    date    TEXT NOT NULL,
    body    TEXT NOT NULL,
    PRIMARY KEY (space, date)
);

CREATE INDEX IF NOT EXISTS notes_concept ON notes(concept_id);
CREATE INDEX IF NOT EXISTS notes_type    ON notes(type);
CREATE INDEX IF NOT EXISTS notes_concept_created ON notes(concept_id, created_at DESC);
CREATE INDEX IF NOT EXISTS notes_type_created    ON notes(type, created_at DESC);
CREATE INDEX IF NOT EXISTS qt_concept    ON quicktests(concept_id);
CREATE INDEX IF NOT EXISTS qt_concept_created
    ON quicktests(concept_id, created_at DESC);
"""


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _db_path(space_dir: Path) -> Path:
    d = space_dir / ".spaces"
    d.mkdir(exist_ok=True)
    return d / "sarthak.db"


def _media_dir(space_dir: Path) -> Path:
    d = space_dir / ".spaces" / "media"
    d.mkdir(parents=True, exist_ok=True)
    return d


async def _open_conn(db_path: str) -> aiosqlite.Connection:
    conn = await aiosqlite.connect(db_path)
    conn.row_factory = aiosqlite.Row
    await conn.execute("PRAGMA journal_mode=WAL")
    await conn.execute("PRAGMA synchronous=NORMAL")
    await conn.execute("PRAGMA foreign_keys=ON")
    await conn.execute("PRAGMA cache_size=-8000")
    return conn


# Track which DB paths have been fully initialised in this process.
# Keys are normalised (resolved) path strings.
_INIT_DONE: set[str] = set()
# Per-DB connection pool: normalised path → (conn, asyncio.Lock)
_CONN_POOL: dict[str, tuple[aiosqlite.Connection, asyncio.Lock]] = {}
_POOL_LOCK: asyncio.Lock | None = None  # lazy — created on first use inside event loop


def _get_pool_lock() -> asyncio.Lock:
    """Return the global pool lock, creating it lazily inside the running event loop."""
    global _POOL_LOCK
    if _POOL_LOCK is None:
        _POOL_LOCK = asyncio.Lock()
    return _POOL_LOCK


class RoadmapDB:
    """Async SQLite wrapper. One persistent connection per space directory."""

    def __init__(self, space_dir: Path) -> None:
        self._path = _db_path(space_dir)
        self._key = str(self._path.resolve())
        self._space_dir = space_dir
        self._init_lock = asyncio.Lock()

    async def _ensure_conn(self) -> tuple[aiosqlite.Connection, asyncio.Lock]:
        """Create connection + write lock if missing, without running init()."""
        async with _get_pool_lock():
            if self._key not in _CONN_POOL:
                conn = await _open_conn(self._key)
                _CONN_POOL[self._key] = (conn, asyncio.Lock())
        return _CONN_POOL[self._key]

    async def _conn(self) -> aiosqlite.Connection:
        """Return the persistent, initialised connection for this space DB."""
        conn, _ = await self._ensure_conn()
        # Auto-init: ensure schema is applied before any read
        await self.init()
        return conn

    async def _wconn(self) -> tuple[aiosqlite.Connection, asyncio.Lock]:
        """Return (conn, write-lock) for write operations. Auto-inits schema."""
        conn, lock = await self._ensure_conn()
        await self.init()
        return conn, lock

    async def init(self) -> None:
        if self._key in _INIT_DONE:
            return
        async with self._init_lock:
            if self._key in _INIT_DONE:
                return
            conn, lock = await self._ensure_conn()
            async with lock:
                if self._key in _INIT_DONE:
                    return
                await conn.executescript(_SCHEMA)
                await conn.commit()
                # Safe migrations
                for stmt in [
                    "ALTER TABLE notes ADD COLUMN type TEXT NOT NULL DEFAULT 'note'",
                ]:
                    try:
                        await conn.execute(stmt)
                        await conn.commit()
                    except aiosqlite.OperationalError:
                        pass
                # Migrate digest_cache from old id=1 single-row schema
                async with conn.execute("PRAGMA table_info(digest_cache)") as cur:
                    cols = {row[1] async for row in cur}
                if "id" in cols:
                    await conn.executescript("""
                        CREATE TABLE IF NOT EXISTS digest_cache_new (
                            space TEXT NOT NULL DEFAULT '',
                            date  TEXT NOT NULL,
                            body  TEXT NOT NULL,
                            PRIMARY KEY (space, date)
                        );
                        INSERT OR IGNORE INTO digest_cache_new(space, date, body)
                            SELECT space, date, body FROM digest_cache;
                        DROP TABLE digest_cache;
                        ALTER TABLE digest_cache_new RENAME TO digest_cache;
                    """)
                    await conn.commit()
                _INIT_DONE.add(self._key)

    def _space_key(self) -> str:
        """Stable, collision-free key for this space in digest_cache."""
        return str(self._space_dir.resolve())

    # ── Digest cache ──────────────────────────────────────────────────────────

    async def load_digest(self, date: str) -> str | None:
        db = await self._conn()
        async with db.execute(
            "SELECT body FROM digest_cache WHERE space=? AND date=?",
            (self._space_key(), date),
        ) as cur:
            row = await cur.fetchone()
        return row[0] if row else None

    async def save_digest(self, date: str, body: str) -> None:
        db, lock = await self._wconn()
        async with lock:
            await db.execute(
                "INSERT INTO digest_cache(space,date,body) VALUES(?,?,?) "
                "ON CONFLICT(space,date) DO UPDATE SET body=excluded.body",
                (self._space_key(), date, body),
            )
            await db.commit()

    # ── Roadmap blob ──────────────────────────────────────────────────────────

    async def load_roadmap(self) -> Roadmap | None:
        db = await self._conn()
        async with db.execute("SELECT blob FROM roadmap WHERE id=1") as cur:
            row = await cur.fetchone()
        if row is None:
            return None
        return Roadmap.model_validate_json(row[0]).sorted_by_order()

    async def save_roadmap(self, roadmap: Roadmap) -> None:
        blob = roadmap.model_dump_json()
        db, lock = await self._wconn()
        async with lock:
            await db.execute(
                "INSERT INTO roadmap(id,blob,updated) VALUES(1,?,?) "
                "ON CONFLICT(id) DO UPDATE SET "
                "blob=excluded.blob, updated=excluded.updated",
                (blob, _now()),
            )
            await db.commit()

    async def patch_roadmap(self, patch: dict[str, Any]) -> Roadmap:
        roadmap = await self.load_roadmap()
        if roadmap is None:
            raise ValueError("Roadmap not initialized")
        current = roadmap.to_dict()
        _deep_merge(current, patch)
        updated = Roadmap.model_validate(current).sorted_by_order()
        await self.save_roadmap(updated)
        return updated

    # ── Notes ─────────────────────────────────────────────────────────────────

    async def create_note(self, note: NoteRow) -> NoteRow:
        note.created_at = note.created_at or _now()
        db, lock = await self._wconn()
        async with lock:
            await db.execute(
                "INSERT INTO notes("
                "id,chapter_id,topic_id,concept_id,title,"
                "body_md,type,audio_path,video_path,created_at"
                ") "
                "VALUES(?,?,?,?,?,?,?,?,?,?)",
                (
                    note.id,
                    note.chapter_id,
                    note.topic_id,
                    note.concept_id,
                    note.title,
                    note.body_md,
                    note.type,
                    note.audio_path,
                    note.video_path,
                    note.created_at,
                ),
            )
            await db.commit()
        return note

    async def update_note(
        self,
        note_id: str,
        title: str | None = None,
        body_md: str | None = None,
    ) -> NoteRow | None:
        """Update a note's title and/or body without overwriting omitted fields."""
        sets: list[str] = []
        params: list[object] = []
        if title is not None:
            sets.append("title=?")
            params.append(title)
        if body_md is not None:
            sets.append("body_md=?")
            params.append(body_md)
        if not sets:
            return await self.get_note(note_id)
        params.append(note_id)
        db, lock = await self._wconn()
        async with lock:
            await db.execute(
                f"UPDATE notes SET {', '.join(sets)} WHERE id=?",
                params,
            )
            await db.commit()
        return await self.get_note(note_id)

    async def delete_note(self, note_id: str) -> None:
        db, lock = await self._wconn()
        async with lock:
            await db.execute("DELETE FROM notes WHERE id=?", (note_id,))
            await db.commit()

    async def list_notes(
        self,
        concept_id: str = "",
        note_type: str = "",
    ) -> list[NoteRow]:
        db = await self._conn()
        clauses, params = [], []
        if concept_id:
            clauses.append("concept_id=?")
            params.append(concept_id)
        if note_type:
            clauses.append("type=?")
            params.append(note_type)
        where = ("WHERE " + " AND ".join(clauses)) if clauses else ""
        async with db.execute(
            f"SELECT * FROM notes {where} ORDER BY created_at DESC", params
        ) as cur:
            rows = await cur.fetchall()
        return [NoteRow(**dict(r)) for r in rows]

    async def get_note(self, note_id: str) -> NoteRow | None:
        db = await self._conn()
        async with db.execute("SELECT * FROM notes WHERE id=?", (note_id,)) as cur:
            row = await cur.fetchone()
        return NoteRow(**dict(row)) if row else None

    async def list_all_media_notes(self, concept_id: str = "") -> list[NoteRow]:
        db = await self._conn()
        sql = "SELECT * FROM notes WHERE type IN ('audio','video')"
        params: list = []
        if concept_id:
            sql += " AND concept_id=?"
            params.append(concept_id)
        sql += " ORDER BY created_at DESC"
        async with db.execute(sql, params) as cur:
            rows = await cur.fetchall()
        return [NoteRow(**dict(r)) for r in rows]

    # ── QuickTests ─────────────────────────────────────────────────────────────

    async def create_quicktest(self, qt: QuickTestRow) -> QuickTestRow:
        qt.created_at = qt.created_at or _now()
        db, lock = await self._wconn()
        async with lock:
            await db.execute(
                "INSERT INTO quicktests("
                "id,chapter_id,topic_id,concept_id,prompt,"
                "response_md,input_mode,created_at"
                ") "
                "VALUES(?,?,?,?,?,?,?,?)",
                (
                    qt.id,
                    qt.chapter_id,
                    qt.topic_id,
                    qt.concept_id,
                    qt.prompt,
                    qt.response_md,
                    qt.input_mode,
                    qt.created_at,
                ),
            )
            await db.commit()
        return qt

    async def list_quicktests(self, concept_id: str = "") -> list[QuickTestRow]:
        db = await self._conn()
        sql = "SELECT * FROM quicktests"
        params: list = []
        if concept_id:
            sql += " WHERE concept_id=?"
            params.append(concept_id)
        sql += " ORDER BY created_at DESC"
        async with db.execute(sql, params) as cur:
            rows = await cur.fetchall()
        return [QuickTestRow(**dict(r)) for r in rows]

    # ── Files ─────────────────────────────────────────────────────────────────

    async def upsert_file(self, fl: FileLink) -> FileLink:
        linked_json = json.dumps([lt.model_dump() for lt in fl.linked_to])
        db, lock = await self._wconn()
        async with lock:
            await db.execute(
                "INSERT INTO files(id,path,linked_to) VALUES(?,?,?) "
                "ON CONFLICT(path) DO UPDATE SET "
                "linked_to=excluded.linked_to, id=files.id",
                (fl.id, fl.path, linked_json),
            )
            await db.commit()
        return fl

    async def list_files(self) -> list[FileLink]:
        db = await self._conn()
        async with db.execute("SELECT * FROM files ORDER BY path") as cur:
            rows = await cur.fetchall()
        result = []
        for r in rows:
            lt = [LinkedTarget(**x) for x in json.loads(r["linked_to"])]
            result.append(FileLink(id=r["id"], path=r["path"], linked_to=lt))
        return result

    async def index_workspace_files(self) -> int:
        space_dir = self._space_dir
        rows: list[tuple[str, str, str]] = []
        skip_dirs = {".spaces", ".git", "__pycache__", "node_modules", ".venv"}
        for p in space_dir.rglob("*"):
            if p.is_dir():
                continue
            if any(part in skip_dirs for part in p.parts[len(space_dir.parts) :]):
                continue
            rel = str(p.relative_to(space_dir))
            file_link = FileLink(path=rel)
            rows.append((file_link.id, file_link.path, "[]"))
        if not rows:
            return 0
        db, lock = await self._wconn()
        async with lock:
            await db.executemany(
                "INSERT INTO files(id,path,linked_to) VALUES(?,?,?) "
                "ON CONFLICT(path) DO UPDATE SET "
                "linked_to=excluded.linked_to, id=files.id",
                rows,
            )
            await db.commit()
        return len(rows)

    # ── Audio/video paths ──────────────────────────────────────────────────────

    def audio_path(self, note_id: str) -> Path:
        """Legacy: kept for transcription endpoint compatibility."""
        return _media_dir(self._space_dir) / f"{note_id}.webm"

    def video_path(self, note_id: str) -> Path:
        return _media_dir(self._space_dir) / f"{note_id}_video.webm"


# ── Helpers ───────────────────────────────────────────────────────────────────


def _deep_merge(target: dict, patch: dict) -> None:
    """RFC 7396 JSON Merge Patch — mutates target in place."""
    for k, v in patch.items():
        if v is None:
            target.pop(k, None)
        elif isinstance(v, dict) and isinstance(target.get(k), dict):
            _deep_merge(target[k], v)
        else:
            target[k] = v
