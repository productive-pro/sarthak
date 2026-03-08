"""
Sarthak Spaces — SQLite persistence for Roadmap System.

One DB per space: .spaces/<n>/sarthak.db
Tables: roadmap (JSON blob), notes, quicktests, files
Audio/video blobs: .spaces/<n>/media/<id>.<ext> (path stored in DB)
"""
from __future__ import annotations

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
CREATE INDEX IF NOT EXISTS qt_concept    ON quicktests(concept_id);
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


# Track which DB paths have been fully initialised in this process.
_INIT_DONE: set[Path] = set()


class RoadmapDB:
    """Async SQLite wrapper. One instance per space directory."""

    def __init__(self, space_dir: Path) -> None:
        self._path = _db_path(space_dir)
        self._space_dir = space_dir

    async def init(self) -> None:
        if self._path in _INIT_DONE:
            return
        async with aiosqlite.connect(self._path) as db:
            await db.executescript(_SCHEMA)
            await db.commit()
        # Safe migrations
        for stmt in [
            "ALTER TABLE notes ADD COLUMN type TEXT NOT NULL DEFAULT 'note'",
        ]:
            try:
                async with aiosqlite.connect(self._path) as db:
                    await db.execute(stmt)
                    await db.commit()
            except aiosqlite.OperationalError:
                pass
        # Migrate digest_cache from old id=1 single-row schema
        async with aiosqlite.connect(self._path) as db:
            async with db.execute("PRAGMA table_info(digest_cache)") as cur:
                cols = {row[1] async for row in cur}
        if "id" in cols:
            async with aiosqlite.connect(self._path) as db:
                await db.executescript("""
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
                await db.commit()
        _INIT_DONE.add(self._path)

    # ── Digest cache ──────────────────────────────────────────────────────────

    async def load_digest(self, date: str) -> str | None:
        async with aiosqlite.connect(self._path) as db:
            async with db.execute(
                "SELECT body FROM digest_cache WHERE space=? AND date=?",
                (str(self._space_dir.name), date),
            ) as cur:
                row = await cur.fetchone()
        return row[0] if row else None

    async def save_digest(self, date: str, body: str) -> None:
        async with aiosqlite.connect(self._path) as db:
            await db.execute(
                "INSERT INTO digest_cache(space,date,body) VALUES(?,?,?) "
                "ON CONFLICT(space,date) DO UPDATE SET body=excluded.body",
                (str(self._space_dir.name), date, body),
            )
            await db.commit()

    # ── Roadmap blob ──────────────────────────────────────────────────────────

    async def load_roadmap(self) -> Roadmap | None:
        async with aiosqlite.connect(self._path) as db:
            async with db.execute("SELECT blob FROM roadmap WHERE id=1") as cur:
                row = await cur.fetchone()
        if row is None:
            return None
        return Roadmap.model_validate_json(row[0]).sorted_by_order()

    async def save_roadmap(self, roadmap: Roadmap) -> None:
        blob = roadmap.model_dump_json()
        async with aiosqlite.connect(self._path) as db:
            await db.execute(
                "INSERT INTO roadmap(id,blob,updated) VALUES(1,?,?) "
                "ON CONFLICT(id) DO UPDATE SET blob=excluded.blob, updated=excluded.updated",
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
        async with aiosqlite.connect(self._path) as db:
            await db.execute(
                "INSERT INTO notes(id,chapter_id,topic_id,concept_id,title,body_md,type,audio_path,video_path,created_at) "
                "VALUES(?,?,?,?,?,?,?,?,?,?)",
                (note.id, note.chapter_id, note.topic_id, note.concept_id,
                 note.title, note.body_md, note.type, note.audio_path, note.video_path, note.created_at),
            )
            await db.commit()
        return note

    async def update_note(
        self,
        note_id: str,
        title: str | None = None,
        body_md: str | None = None,
    ) -> NoteRow | None:
        """Update a note's title and/or body_md. None values leave the column unchanged."""
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
        async with aiosqlite.connect(self._path) as db:
            await db.execute(
                f"UPDATE notes SET {', '.join(sets)} WHERE id=?",
                params,
            )
            await db.commit()
        return await self.get_note(note_id)

    async def delete_note(self, note_id: str) -> None:
        async with aiosqlite.connect(self._path) as db:
            await db.execute("DELETE FROM notes WHERE id=?", (note_id,))
            await db.commit()

    async def list_notes(
        self,
        concept_id: str = "",
        note_type: str = "",
    ) -> list[NoteRow]:
        """List notes filtered by type. Pass note_type='' (default) to get all types."""
        async with aiosqlite.connect(self._path) as db:
            db.row_factory = aiosqlite.Row
            if note_type and concept_id:
                async with db.execute(
                    "SELECT * FROM notes WHERE concept_id=? AND type=? ORDER BY created_at DESC",
                    (concept_id, note_type),
                ) as cur:
                    rows = await cur.fetchall()
            elif note_type:
                async with db.execute(
                    "SELECT * FROM notes WHERE type=? ORDER BY created_at DESC",
                    (note_type,),
                ) as cur:
                    rows = await cur.fetchall()
            elif concept_id:
                async with db.execute(
                    "SELECT * FROM notes WHERE concept_id=? ORDER BY created_at DESC",
                    (concept_id,),
                ) as cur:
                    rows = await cur.fetchall()
            else:
                async with db.execute(
                    "SELECT * FROM notes ORDER BY created_at DESC"
                ) as cur:
                    rows = await cur.fetchall()
        return [NoteRow(**dict(r)) for r in rows]

    async def list_notes_by_type(self, note_type: str, concept_id: str = "") -> list[NoteRow]:
        """List notes of a specific type (audio/video), optionally filtered by concept."""
        async with aiosqlite.connect(self._path) as db:
            db.row_factory = aiosqlite.Row
            if concept_id:
                async with db.execute(
                    "SELECT * FROM notes WHERE type=? AND concept_id=? ORDER BY created_at DESC",
                    (note_type, concept_id),
                ) as cur:
                    rows = await cur.fetchall()
            else:
                async with db.execute(
                    "SELECT * FROM notes WHERE type=? ORDER BY created_at DESC",
                    (note_type,),
                ) as cur:
                    rows = await cur.fetchall()
        return [NoteRow(**dict(r)) for r in rows]

    async def get_note(self, note_id: str) -> NoteRow | None:
        async with aiosqlite.connect(self._path) as db:
            db.row_factory = aiosqlite.Row
            async with db.execute("SELECT * FROM notes WHERE id=?", (note_id,)) as cur:
                row = await cur.fetchone()
        if not row:
            return None
        return NoteRow(**dict(row))

    async def list_all_media_notes(self, concept_id: str = "") -> list[NoteRow]:
        """List all audio + video notes in one query."""
        async with aiosqlite.connect(self._path) as db:
            db.row_factory = aiosqlite.Row
            if concept_id:
                async with db.execute(
                    "SELECT * FROM notes WHERE type IN ('audio','video') AND concept_id=? ORDER BY created_at DESC",
                    (concept_id,),
                ) as cur:
                    rows = await cur.fetchall()
            else:
                async with db.execute(
                    "SELECT * FROM notes WHERE type IN ('audio','video') ORDER BY created_at DESC"
                ) as cur:
                    rows = await cur.fetchall()
        return [NoteRow(**dict(r)) for r in rows]

    # ── QuickTests ─────────────────────────────────────────────────────────────

    async def create_quicktest(self, qt: QuickTestRow) -> QuickTestRow:
        qt.created_at = qt.created_at or _now()
        async with aiosqlite.connect(self._path) as db:
            await db.execute(
                "INSERT INTO quicktests(id,chapter_id,topic_id,concept_id,prompt,response_md,input_mode,created_at) "
                "VALUES(?,?,?,?,?,?,?,?)",
                (qt.id, qt.chapter_id, qt.topic_id, qt.concept_id,
                 qt.prompt, qt.response_md, qt.input_mode, qt.created_at),
            )
            await db.commit()
        return qt

    async def list_quicktests(self, concept_id: str = "") -> list[QuickTestRow]:
        async with aiosqlite.connect(self._path) as db:
            db.row_factory = aiosqlite.Row
            if concept_id:
                async with db.execute(
                    "SELECT * FROM quicktests WHERE concept_id=? ORDER BY created_at DESC",
                    (concept_id,),
                ) as cur:
                    rows = await cur.fetchall()
            else:
                async with db.execute(
                    "SELECT * FROM quicktests ORDER BY created_at DESC"
                ) as cur:
                    rows = await cur.fetchall()
        return [QuickTestRow(**dict(r)) for r in rows]

    # ── Files ─────────────────────────────────────────────────────────────────

    async def upsert_file(self, fl: FileLink) -> FileLink:
        linked_json = json.dumps([lt.model_dump() for lt in fl.linked_to])
        async with aiosqlite.connect(self._path) as db:
            await db.execute(
                "INSERT INTO files(id,path,linked_to) VALUES(?,?,?) "
                "ON CONFLICT(path) DO UPDATE SET linked_to=excluded.linked_to, id=files.id",
                (fl.id, fl.path, linked_json),
            )
            await db.commit()
        return fl

    async def list_files(self) -> list[FileLink]:
        async with aiosqlite.connect(self._path) as db:
            db.row_factory = aiosqlite.Row
            async with db.execute("SELECT * FROM files ORDER BY path") as cur:
                rows = await cur.fetchall()
        result = []
        for r in rows:
            lt = [LinkedTarget(**x) for x in json.loads(r["linked_to"])]
            result.append(FileLink(id=r["id"], path=r["path"], linked_to=lt))
        return result

    async def index_workspace_files(self) -> int:
        space_dir = self._space_dir
        count = 0
        skip_dirs = {".spaces", ".git", "__pycache__", "node_modules", ".venv"}
        for p in space_dir.rglob("*"):
            if p.is_dir():
                continue
            if any(part in skip_dirs for part in p.parts[len(space_dir.parts):]):
                continue
            rel = str(p.relative_to(space_dir))
            await self.upsert_file(FileLink(path=rel))
            count += 1
        return count

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
