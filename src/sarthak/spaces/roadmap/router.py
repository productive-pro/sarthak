"""
Sarthak Spaces — Roadmap FastAPI Router.

Mount with: app.include_router(roadmap_router, prefix="/api/spaces")

All state stored in .spaces/sarthak.db (one DB per space directory).
Space dir is resolved as: base_spaces_dir / space_name
"""
from __future__ import annotations

import json
import re as _re
import shutil
import uuid
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Body, File, HTTPException, Query, UploadFile
from pydantic import BaseModel
_BaseModel = BaseModel
from fastapi.responses import FileResponse, StreamingResponse

from sarthak.spaces import rag as rag_mod
from sarthak.spaces.notes import (
    document_to_note,
    file_to_note,
    remove_frontend_note,
    sync_frontend_note,
)
from sarthak.spaces.roadmap.quicktest import create_quicktest as create_quicktest_record

from sarthak.core.logging import get_logger
from sarthak.storage.activity_store import record as _record_activity

from .db import RoadmapDB
from .models import (
    FileLink,
    LinkedTarget,
    NoteRow,
    Roadmap,
)
from .recommend import recommend_next
from .stt import is_stt_available, invalidate_stt_cache, stt_provider_name, transcribe, transcribe_vtt  # noqa: F401
from .media_analysis import (
    analyze_transcript, teach_it_back,
    search_transcripts, transcript_to_flashcards, speaking_stats, vtt_to_plain,
)

log = get_logger(__name__)
roadmap_router = APIRouter(tags=["roadmap"])

# Base directory for spaces; can be overridden by caller
_BASE: Path = Path.home() / "sarthak_spaces"


def _set_base(path: Path) -> None:
    global _BASE
    _BASE = path


def _space_dir(space: str) -> Path:
    """Resolve a space name or encoded directory path to its Path.

    The ``space`` parameter from the URL can be:
    1. A URL-encoded *absolute path* (e.g. ``%2Fhome%2Farcher%2Fprojects%2Fmyapp``).
    2. A bare space *name* looked up from the global registry.
    3. A subdirectory name under ``_BASE`` (legacy default behaviour).
    """
    import urllib.parse

    # 1. Try decoding as an absolute path first
    decoded = urllib.parse.unquote(space)
    candidate = Path(decoded)
    if candidate.is_absolute() and candidate.exists():
        return candidate

    # 2. Look up by name in the global registry
    from sarthak.spaces.store import list_spaces
    for s in list_spaces():
        if (s.get("name") == space or
                s.get("name") == decoded or
                Path(s.get("directory", "")).name == space):
            sp = Path(s["directory"])
            if sp.exists():
                return sp

    # 3. Legacy: treat as subdirectory of _BASE
    d = _BASE / space
    if d.exists():
        return d

    raise HTTPException(
        status_code=404,
        detail=f"Space '{space}' not found — checked registry and {_BASE / space}",
    )


async def _db(space: str) -> RoadmapDB:
    """Open and initialise a RoadmapDB for *space*.

    NOTE: RoadmapDB.init() is idempotent (CREATE TABLE IF NOT EXISTS). The
    underlying connection pool (in db.py) is process-level, so connections are
    reused across calls — only the RoadmapDB wrapper object is created fresh.
    """
    db = RoadmapDB(_space_dir(space))
    await db.init()
    return db


# ── Roadmap ───────────────────────────────────────────────────────────────────

def _sync_curriculum_to_roadmap_json(space_dir: Path, roadmap: Roadmap) -> None:
    """Mirror curriculum chapters into .spaces/roadmap.json under the 'curriculum' key."""
    from datetime import datetime, timezone
    rj_path = space_dir / ".spaces" / "roadmap.json"
    rj_path.parent.mkdir(parents=True, exist_ok=True)
    data: dict[str, Any] = {}
    if rj_path.exists():
        try:
            data = json.loads(rj_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            data = {}
    data["curriculum"] = {
        "version": roadmap.version,
        "space": roadmap.space,
        "chapters": [
            {
                "id": ch.id,
                "title": ch.title,
                "description": ch.description,
                "order": ch.order,
                "status": ch.status.value if hasattr(ch.status, "value") else ch.status,
                "progress_pct": ch.progress_pct,
                "topics": [
                    {
                        "id": tp.id,
                        "title": tp.title,
                        "order": tp.order,
                        "status": tp.status.value if hasattr(tp.status, "value") else tp.status,
                        "concepts": [
                            {
                                "id": cn.id,
                                "title": cn.title,
                                "description": cn.description,
                                "order": cn.order,
                                "status": cn.status.value if hasattr(cn.status, "value") else cn.status,
                                "tags": cn.tags,
                                "related_concepts": cn.related_concepts,
                            }
                            for cn in tp.concepts
                        ],
                    }
                    for tp in ch.topics
                ],
            }
            for ch in roadmap.chapters
        ],
    }
    data["last_updated"] = datetime.now(timezone.utc).isoformat()
    rj_path.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")


@roadmap_router.get("/{space}/roadmap")
async def get_roadmap(space: str) -> dict[str, Any]:
    db = await _db(space)
    roadmap = await db.load_roadmap()
    if roadmap is None:
        raise HTTPException(status_code=404, detail="Roadmap not initialized")
    updated = roadmap.compute_all_progress()
    return updated.to_dict()


@roadmap_router.patch("/{space}/roadmap")
async def patch_roadmap(space: str, patch: dict[str, Any] = Body(...)) -> dict[str, Any]:
    db = await _db(space)
    updated = await db.patch_roadmap(patch)
    result = updated.compute_all_progress()
    _sync_curriculum_to_roadmap_json(_space_dir(space), result)
    return result.to_dict()


@roadmap_router.post("/{space}/roadmap/generate-children")
async def generate_children(space: str, body: dict[str, Any] = Body(...)) -> dict[str, Any]:
    """Generate child items for a Chapter (Topics) or Topic (Concepts) using the LLM."""
    from sarthak.features.ai.agents._base import resolve_provider_model, build_pydantic_model
    from pydantic_ai import Agent

    parent_type = body.get("parent_type", "chapter")
    parent_title = body.get("parent_title", "")
    if not parent_title:
        raise HTTPException(400, "parent_title is required")
    instruction = (body.get("instruction") or "").strip()

    p, m = resolve_provider_model(None, None)
    agent = Agent(build_pydantic_model(p, m), output_type=list[str], retries=2)
    
    if parent_type == "chapter":
        prompt = f"Given the course chapter '{parent_title}', generate a list of 3 to 5 logical sub-topics to cover in this chapter. Return ONLY a JSON list of strings."
    else:
        prompt = f"Given the topic '{parent_title}', generate a list of 3 to 5 highly specific learning concepts to master. Return ONLY a JSON list of strings."
    if instruction:
        prompt = f"{prompt}\nAdditional instructions: {instruction}"

    res = await agent.run(prompt)
    return {"children": res.output}


# ── Notes ─────────────────────────────────────────────────────────────────────

@roadmap_router.post("/{space}/notes")
async def create_note(space: str, body: dict[str, Any] = Body(...)) -> dict[str, Any]:
    db  = await _db(space)
    note = NoteRow(
        chapter_id=body.get("chapter_id", ""),
        topic_id=body.get("topic_id", ""),
        concept_id=body.get("concept_id", ""),
        title=body.get("title", ""),
        body_md=body.get("body_md", ""),
        type=body.get("type", "note"),
        audio_path=body.get("audio_path"),
    )
    note = await db.create_note(note)

    # Link note ID into roadmap concept.notes (only for regular notes)
    if note.concept_id and note.type == "note":
        roadmap = await db.load_roadmap()
        if roadmap:
            cn = roadmap.get_concept(note.concept_id)
            if cn and note.id not in cn.notes:
                cn.notes.append(note.id)
                await db.save_roadmap(roadmap)

    await _sync_frontend_note(space, db, note)

    # Record to global activity store
    if note.body_md.strip():
        try:
            await _record_activity(
                activity_type="note",
                space_dir=str(_space_dir(space)),
                concept_id=note.concept_id,
                content_text=note.body_md[:4096],
                metadata={"title": note.title},
                db=db,
            )
        except Exception:
            pass

    return note.model_dump()


@roadmap_router.get("/{space}/notes")
async def list_notes(
    space: str,
    concept_id: str = Query(default=""),
    type: str = Query(default=""),
) -> list[dict[str, Any]]:
    db = await _db(space)
    rows = await db.list_notes(concept_id=concept_id, note_type=type or "note")
    return [r.model_dump() for r in rows]


def _uploads_dir(space: str) -> Path:
    """Return (and create) the uploads directory for a space."""
    d = _space_dir(space) / ".spaces" / "uploads"
    d.mkdir(parents=True, exist_ok=True)
    return d


@roadmap_router.post("/{space}/notes/import")
async def import_note_document(
    space: str,
    file: UploadFile = File(...),
    concept_id: str = Query(default=""),
    title: str = Query(default=""),
    ocr_mode: str = Query(default="vision"),
) -> dict[str, Any]:
    """Upload a document/image and convert it to Markdown for concept notes."""
    if not file.filename:
        raise HTTPException(status_code=400, detail="File is required")
    MAX_UPLOAD_BYTES = 50 * 1024 * 1024

    db = await _db(space)
    roadmap = await db.load_roadmap()
    concept_title = title.strip()
    if not concept_title and roadmap and concept_id:
        cn = roadmap.get_concept(concept_id)
        if cn:
            concept_title = cn.title
    if not concept_title:
        concept_title = Path(file.filename).stem

    dest = _uploads_dir(space) / f"import_{uuid.uuid4().hex}{Path(file.filename).suffix}"
    data = await file.read()
    if len(data) > MAX_UPLOAD_BYTES:
        raise HTTPException(status_code=413, detail="File exceeds 50MB limit")
    dest.write_bytes(data)

    try:
        if ocr_mode == "text_llm":
            md = await document_to_note(dest, concept_title)
        else:
            md = await file_to_note(dest, concept_title)
    finally:
        try:
            dest.unlink()
        except Exception:
            pass

    return {"markdown": md, "concept_title": concept_title, "filename": file.filename}


@roadmap_router.put("/{space}/notes/{note_id}")
async def update_note(
    space: str, note_id: str, body: dict[str, Any] = Body(...)
) -> dict[str, Any]:
    db = await _db(space)
    note = await db.update_note(
        note_id,
        title=body.get("title", ""),
        body_md=body.get("body_md", ""),
    )
    if note is None:
        raise HTTPException(status_code=404, detail="Note not found")
    await _sync_frontend_note(space, db, note)
    return note.model_dump()


@roadmap_router.delete("/{space}/notes/{note_id}")
async def delete_note(space: str, note_id: str) -> dict[str, Any]:
    db = await _db(space)
    await db.delete_note(note_id)
    remove_frontend_note(_space_dir(space), note_id)
    return {"ok": True}


# ── Media files (.spaces/media/) ──────────────────────────────────────────────

def _media_dir(space: str) -> Path:
    """Return (and create) the media directory for a space."""
    d = _space_dir(space) / ".spaces" / "media"
    d.mkdir(parents=True, exist_ok=True)
    return d


@roadmap_router.post("/{space}/media")
async def upload_media(
    space: str,
    file: UploadFile = File(...),
    concept_id: str = Query(default=""),
    chapter_id: str = Query(default=""),
    topic_id:   str = Query(default=""),
    label:      str = Query(default=""),
) -> dict[str, Any]:
    """Save a recorded audio/video blob to .spaces/media/ and index it as a note."""
    media_dir = _media_dir(space)
    ext  = Path(file.filename or "recording.webm").suffix or ".webm"
    mid  = str(uuid.uuid4())
    fname = f"{mid}{ext}"
    dest  = media_dir / fname
    dest.write_bytes(await file.read())
    rel_path = str(dest)

    # Determine type from content-type or filename
    ct = (file.content_type or "").lower()
    fname = (file.filename or "").lower()
    is_video = "video" in ct or fname.startswith("recording_video")
    note_type = "video" if is_video else "audio"

    db = await _db(space)
    note = NoteRow(
        chapter_id=chapter_id,
        topic_id=topic_id,
        concept_id=concept_id,
        title=label or ("Video note" if is_video else "Audio note"),
        body_md="",
        type=note_type,
        audio_path=None if is_video else rel_path,
        video_path=rel_path if is_video else None,
    )
    note = await db.create_note(note)

    # Record to global user_activity store for analytics / digest
    try:
        await _record_activity(
            activity_type=note_type + "_note",  # type: ignore[arg-type]
            space_dir=str(_space_dir(space)),
            concept_id=concept_id,
            media_path=rel_path,
            metadata={"label": label, "is_video": is_video},
            db=db,
        )
    except Exception:
        pass

    return {"id": note.id, "path": rel_path, "type": note_type, "concept_id": concept_id}


@roadmap_router.get("/{space}/media")
async def list_media(
    space: str,
    concept_id: str = Query(default=""),
) -> list[dict[str, Any]]:
    """List all media notes (audio + video) for a space, optionally filtered by concept."""
    db = await _db(space)
    rows = await db.list_all_media_notes(concept_id=concept_id)
    return [r.model_dump() for r in rows]


@roadmap_router.get("/{space}/media/search")
async def search_media(space: str, q: str = Query(...)) -> dict[str, Any]:
    """Full-text search across all media note transcripts."""
    db   = await _db(space)
    all_notes = [r.model_dump() for r in await db.list_all_media_notes()]
    hits = search_transcripts(all_notes, q)
    return {"results": hits, "count": len(hits)}


@roadmap_router.get("/{space}/media/{note_id}/file")
async def serve_media_file(space: str, note_id: str):
    """Stream the actual media file."""
    db = await _db(space)
    note = await db.get_note(note_id)
    if not note:
        raise HTTPException(404, "Note not found")
    path_str = note.video_path or note.audio_path
    if not path_str:
        raise HTTPException(404, "No media file attached")
    p = Path(path_str)
    if not p.exists():
        raise HTTPException(404, "Media file missing from disk")
    media_type = "video/webm" if note.type == "video" else "audio/webm"
    return FileResponse(str(p), media_type=media_type)


@roadmap_router.patch("/{space}/media/{note_id}")
async def rename_media(space: str, note_id: str, body: dict[str, Any] = Body(...)) -> dict[str, Any]:
    """Rename a media note (updates title in DB)."""
    db = await _db(space)
    note = await db.get_note(note_id)
    if not note:
        raise HTTPException(404, "Note not found")
    new_title = body.get("title")
    updated = await db.update_note(note_id, title=new_title)
    return updated.model_dump()


@roadmap_router.post("/{space}/media/{note_id}/analyze")
async def analyze_media(space: str, note_id: str) -> dict[str, Any]:
    """Transcribe (if needed) then run AI feedback + speaking stats on a clip."""
    db   = await _db(space)
    note = await db.get_note(note_id)
    if not note:
        raise HTTPException(404, "Note not found")
    path_str = note.video_path or note.audio_path
    if not path_str or not Path(path_str).exists():
        raise HTTPException(400, "No media file attached")

    # Transcribe if no existing transcript
    transcript_text = note.body_md or ""
    if not transcript_text.strip():
        if not is_stt_available():
            log.info("analyze_media_skip_no_stt", space=space, note_id=note_id)
            return {"feedback": "STT not configured — no transcript available.", "stats": {}, "transcript": ""}
        transcript_text = await transcribe_vtt(Path(path_str))
        await db.update_note(note_id, title=note.title, body_md=transcript_text)

    plain = vtt_to_plain(transcript_text) if "WEBVTT" in transcript_text else transcript_text
    roadmap = await db.load_roadmap()
    concept_title = note.title
    if roadmap and note.concept_id:
        cn = roadmap.get_concept(note.concept_id)
        if cn:
            concept_title = cn.title

    feedback  = await analyze_transcript(plain, concept_title)
    stats     = speaking_stats(transcript_text)
    return {"feedback": feedback, "stats": stats, "transcript": plain}


@roadmap_router.post("/{space}/media/{note_id}/teach-it-back")
async def teach_it_back_endpoint(space: str, note_id: str) -> dict[str, Any]:
    """Feynman score: compare learner's explanation vs RAG context for the concept."""
    db   = await _db(space)
    note = await db.get_note(note_id)
    if not note:
        raise HTTPException(404, "Note not found")

    transcript_text = note.body_md or ""
    if not transcript_text.strip():
        path_str = note.video_path or note.audio_path
        if not path_str or not Path(path_str).exists():
            raise HTTPException(400, "No transcript and no media file")
        if not is_stt_available():
            log.info("teach_it_back_skip_no_stt", space=space, note_id=note_id)
            raise HTTPException(400, "No transcript available and STT is not configured. Set [stt] provider in config.toml.")
        transcript_text = await transcribe_vtt(Path(path_str))
        await db.update_note(note_id, title=note.title, body_md=transcript_text)

    plain = vtt_to_plain(transcript_text) if "WEBVTT" in transcript_text else transcript_text
    roadmap = await db.load_roadmap()
    concept_title = note.title
    if roadmap and note.concept_id:
        cn = roadmap.get_concept(note.concept_id)
        if cn:
            concept_title = cn.title

    result = await teach_it_back(plain, concept_title, _space_dir(space))
    return result


@roadmap_router.post("/{space}/media/{note_id}/flashcards")
async def media_to_flashcards(space: str, note_id: str) -> dict[str, Any]:
    """Extract SRS flashcards from a clip's transcript."""
    db   = await _db(space)
    note = await db.get_note(note_id)
    if not note:
        raise HTTPException(404, "Note not found")
    plain = ""
    if note.body_md:
        plain = vtt_to_plain(note.body_md) if "WEBVTT" in note.body_md else note.body_md
    if not plain.strip():
        raise HTTPException(400, "No transcript available — generate subtitles first")
    roadmap = await db.load_roadmap()
    concept_title = note.title
    if roadmap and note.concept_id:
        cn = roadmap.get_concept(note.concept_id)
        if cn:
            concept_title = cn.title
    cards = await transcript_to_flashcards(plain, concept_title)
    return {"cards": cards}


@roadmap_router.delete("/{space}/media/{note_id}")
async def delete_media(space: str, note_id: str) -> dict[str, Any]:
    """Delete media note from DB and remove file from disk."""
    db = await _db(space)
    note = await db.get_note(note_id)
    if not note:
        raise HTTPException(404, "Note not found")
    for path_str in [note.audio_path, note.video_path]:
        if path_str:
            p = Path(path_str)
            if p.exists():
                p.unlink(missing_ok=True)
    await db.delete_note(note_id)
    return {"ok": True}


# ── QuickTest ────────────────────────────────────────────────────────────────

@roadmap_router.post("/{space}/quicktest")
async def create_quicktest(
    space: str, body: dict[str, Any] = Body(...)
) -> dict[str, Any]:
    sd  = _space_dir(space)

    input_mode = body.get("input_mode", "user")
    prompt     = body.get("prompt", "")
    chapter_id = body.get("chapter_id", "")
    topic_id   = body.get("topic_id", "")
    concept_id = body.get("concept_id", "")

    log.info("quicktest_start", space=space, concept_id=concept_id, input_mode=input_mode)
    try:
        qt = await create_quicktest_record(
            sd,
            input_mode=input_mode,
            prompt=prompt,
            chapter_id=chapter_id,
            topic_id=topic_id,
            concept_id=concept_id,
        )
        log.info("quicktest_done", space=space, concept_id=concept_id, qt_id=qt.id)
        # Record to activity store
        try:
            await _record_activity(
                activity_type="quicktest",
                space_dir=str(sd),
                concept_id=concept_id,
                content_text=qt.response_md[:2048],
                metadata={"input_mode": input_mode, "qt_id": qt.id},
            )
        except Exception:
            pass
        return qt.model_dump()
    except Exception as exc:
        log.error("quicktest_error", space=space, concept_id=concept_id, error=str(exc))
        raise


@roadmap_router.get("/{space}/quicktest")
async def list_quicktest(
    space: str,
    concept_id: str = Query(default=""),
) -> list[dict[str, Any]]:
    db = await _db(space)
    rows = await db.list_quicktests(concept_id=concept_id)
    return [r.model_dump() for r in rows]


# ── Notebooks ────────────────────────────────────────────────────────────────
# Stored as notes with type='notebook'; body_md holds the Python source.

@roadmap_router.get("/{space}/notebooks")
async def list_notebooks(
    space: str,
    concept_id: str = Query(default=""),
) -> list[dict[str, Any]]:
    db = await _db(space)
    rows = await db.list_notes(concept_id=concept_id, note_type="notebook")
    return [r.model_dump() for r in rows]


@roadmap_router.post("/{space}/notebooks")
async def create_notebook(
    space: str,
    body: dict[str, Any] = Body(...),
) -> dict[str, Any]:
    db = await _db(space)
    note = NoteRow(
        id=str(uuid.uuid4()),
        concept_id=body.get("concept_id", ""),
        title=body.get("title", "Notebook"),
        body_md=body.get("code", ""),
        type="notebook",
    )
    saved = await db.create_note(note)
    return saved.model_dump()


@roadmap_router.put("/{space}/notebooks/{note_id}")
async def update_notebook(
    space: str,
    note_id: str,
    body: dict[str, Any] = Body(...),
) -> dict[str, Any]:
    db = await _db(space)
    note = await db.get_note(note_id)
    if not note or note.type != "notebook":
        raise HTTPException(404, "Notebook not found")
    updated = await db.update_note(
        note_id,
        title=body.get("title", note.title),
        body_md=body.get("code", note.body_md),
    )
    return updated.model_dump()


@roadmap_router.delete("/{space}/notebooks/{note_id}")
async def delete_notebook(space: str, note_id: str) -> dict[str, Any]:
    db = await _db(space)
    note = await db.get_note(note_id)
    if not note or note.type != "notebook":
        raise HTTPException(404, "Notebook not found")
    await db.delete_note(note_id)
    return {"ok": True}


# ── Recommendations ───────────────────────────────────────────────────────────

@roadmap_router.post("/{space}/recommend")
async def get_recommendations(space: str) -> list[dict[str, Any]]:
    db      = await _db(space)
    roadmap = await db.load_roadmap()
    if roadmap is None:
        return []
    concepts = recommend_next(roadmap, top_k=3)
    return [c.model_dump(mode="json") for c in concepts]


# ── Files ─────────────────────────────────────────────────────────────────────

@roadmap_router.get("/{space}/files")
async def list_files(space: str) -> dict[str, Any]:
    db  = await _db(space)
    fls = await db.list_files()
    return {"files": [fl.model_dump(mode="json") for fl in fls]}


@roadmap_router.get("/{space}/files/content")
async def get_file_content(space: str, path: str = Query(...)) -> dict[str, Any]:
    """Return rendered content of a workspace file."""
    sd   = _space_dir(space)
    full = (sd / path).resolve()
    # Prevent path traversal
    if not str(full).startswith(str(sd)):
        raise HTTPException(status_code=403, detail="Access denied")
    if not full.exists() or not full.is_file():
        raise HTTPException(status_code=404, detail="File not found")
    text = full.read_text(encoding="utf-8", errors="replace")
    return {"path": path, "content": text, "size": full.stat().st_size}


@roadmap_router.get("/{space}/files/raw")
async def get_file_raw(space: str, path: str = Query(...)):
    """Serve a workspace file as raw bytes with correct MIME type (for PDFs, images, etc)."""
    import mimetypes
    sd   = _space_dir(space)
    full = (sd / path).resolve()
    if not str(full).startswith(str(sd)):
        raise HTTPException(status_code=403, detail="Access denied")
    if not full.exists() or not full.is_file():
        raise HTTPException(status_code=404, detail="File not found")
    mime, _ = mimetypes.guess_type(str(full))
    return FileResponse(str(full), media_type=mime or "application/octet-stream")


@roadmap_router.post("/{space}/files/link")
async def link_file(space: str, body: dict[str, Any] = Body(...)) -> dict[str, Any]:
    """Attach a file to a chapter/topic/concept in roadmap."""
    db   = await _db(space)
    path = body.get("path", "")
    lt   = [LinkedTarget(**x) for x in body.get("linked_to", [])]
    fls  = await db.list_files()
    existing = next((f for f in fls if f.path == path), None)
    fl = existing or FileLink(path=path)
    # Merge linked_to without duplicates
    existing_ids = {(x.type, x.id) for x in fl.linked_to}
    fl.linked_to.extend(t for t in lt if (t.type, t.id) not in existing_ids)
    await db.upsert_file(fl)
    return fl.model_dump(mode="json")


# ── RAG Search ────────────────────────────────────────────────────────────────

@roadmap_router.post("/{space}/rag/search")
async def rag_search(space: str, body: dict[str, Any] = Body(...)) -> dict[str, Any]:
    sd      = _space_dir(space)
    query   = body.get("query", "")
    top_k   = int(body.get("top_k", 5))
    results = await rag_mod.search_space_structured(sd, query, top_k=top_k)
    return {"results": [r.to_dict() for r in results]}


@roadmap_router.post("/{space}/rag/index")
async def rag_index(space: str) -> dict[str, Any]:
    sd    = _space_dir(space)
    count = await rag_mod.index_space(sd)
    st    = rag_mod.rag_status(sd)
    return {"chunks_indexed": count, "files_indexed": st.get("indexed_files", 0)}


@roadmap_router.get("/{space}/rag/files")
async def rag_files(space: str) -> dict[str, Any]:
    """List all files currently in the RAG index for this space."""
    sd    = _space_dir(space)
    paths = rag_mod.list_indexed_files(sd)
    st    = rag_mod.rag_status(sd)
    return {
        "files": [{"path": p} for p in paths],
        "indexed_files":  st.get("indexed_files", 0),
        "indexed_chunks": st.get("indexed_chunks", 0),
    }


@roadmap_router.get("/{space}/rag/walk")
async def rag_walk(space: str) -> dict[str, Any]:
    """Walk workspace and return every indexable file with its indexed status."""
    sd    = _space_dir(space)
    files = rag_mod.walk_space(sd)
    st    = rag_mod.rag_status(sd)
    return {
        "files":          files,
        "total_files":    len(files),
        "indexed_files":  st.get("indexed_files", 0),
        "indexed_chunks": st.get("indexed_chunks", 0),
    }


class RagIndexPathsReq(BaseModel):
    paths: list[str]
    pipeline: str = "text"  # "text" | "vision"


@roadmap_router.post("/{space}/rag/index-paths")
async def rag_index_paths(space: str, body: RagIndexPathsReq) -> dict[str, Any]:
    """Index only the selected files. pipeline: 'text' or 'vision'."""
    sd     = _space_dir(space)
    count  = await rag_mod.index_paths(sd, body.paths, pipeline=body.pipeline)
    st     = rag_mod.rag_status(sd)
    return {
        "chunks_indexed": count,
        "indexed_files":  st.get("indexed_files", 0),
        "indexed_chunks": st.get("indexed_chunks", 0),
    }


@roadmap_router.post("/{space}/rag/index-paths/stream")
async def rag_index_paths_stream(space: str, body: RagIndexPathsReq):
    """
    SSE stream of indexing progress. Yields JSON events per file + final done event.
    Client reads with EventSource or fetch + ReadableStream.
    """
    sd = _space_dir(space)
    return StreamingResponse(
        rag_mod.index_paths_streaming(sd, body.paths, pipeline=body.pipeline),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@roadmap_router.post("/{space}/rag/export-activities")
async def rag_export_activities(space: str) -> dict[str, Any]:
    """
    Export notes and media transcripts from activity store to markdown files,
    then return how many were written so the client can re-index.
    """
    sd = _space_dir(space)
    written = await rag_mod.export_activities_to_markdown(sd)
    return {"written": len(written), "paths": written}


@roadmap_router.get("/{space}/rag/status")
async def rag_status_endpoint(space: str) -> dict[str, Any]:
    sd = _space_dir(space)
    return rag_mod.rag_status(sd)


@roadmap_router.post("/{space}/rag/chat")
async def rag_chat(space: str, body: dict[str, Any] = Body(...)) -> dict[str, Any]:
    """
    RAG-grounded chat. Retrieves top-k chunks for the question, then calls
    the LLM with context + optional conversation history.

    Body: {question, history?: [{role, content}], top_k?: int}
    Returns: {answer, sources: [{source, line, score, text}]}
    """
    sd       = _space_dir(space)
    question = (body.get("question") or "").strip()
    history  = body.get("history") or []
    top_k    = int(body.get("top_k", 5))

    if not question:
        raise HTTPException(400, "question is required")

    results = await rag_mod.search_space_structured(sd, question, top_k=top_k)
    context_md = "\n\n---\n\n".join(
        f"[{r.source}:{r.line}]\n{r.text.strip()}" for r in results
    ) if results else ""

    system = (
        "You are a helpful learning assistant. Answer the user's question based on the "
        "workspace context below. Cite sources as [file:line] when relevant. "
        "If the context does not contain the answer, say so and provide what you know.\n\n"
        + (f"=== WORKSPACE CONTEXT ===\n{context_md}\n=== END CONTEXT ===" if context_md
           else "No workspace files are indexed yet.")
    )

    from sarthak.core.ai_utils.multi_provider import call_llm
    history_text = "".join(
        f"\n\n{'User' if t['role'] == 'user' else 'Assistant'}: {t['content']}"
        for t in history
    )
    prompt = system + history_text + f"\n\nUser: {question}"
    answer = await call_llm(prompt)

    return {
        "answer": answer,
        "sources": [r.to_dict() for r in results],
    }


@roadmap_router.post("/{space}/rag/upload")
async def rag_upload(
    space: str,
    file: UploadFile = File(...),
    pipeline: str = Query(default="text"),
) -> dict[str, Any]:
    """
    Upload a file directly into .sarthak_rag/uploads/ and index it immediately.
    pipeline: 'text' | 'vision'
    """
    sd = _space_dir(space)
    upload_dir = sd / ".sarthak_rag" / "uploads"
    upload_dir.mkdir(parents=True, exist_ok=True)

    raw_name = (file.filename or "").strip()
    fname    = Path(raw_name).name if raw_name else f"upload_{uuid.uuid4().hex}"
    if not fname:  # e.g. filename was just a slash
        fname = f"upload_{uuid.uuid4().hex}"
    dest     = upload_dir / fname
    dest.write_bytes(await file.read())
    rel_path = str(dest.relative_to(sd))

    count = await rag_mod.index_paths(sd, [rel_path], pipeline=pipeline)
    st    = rag_mod.rag_status(sd)
    return {
        "saved_as":      rel_path,
        "chunks_indexed": count,
        "indexed_files":  st.get("indexed_files", 0),
        "indexed_chunks": st.get("indexed_chunks", 0),
    }


# ── Whisper Transcription ─────────────────────────────────────────────────────

@roadmap_router.post("/{space}/transcribe")
async def transcribe_audio(
    space: str,
    file: UploadFile = File(...),
    note_id: str = Query(default=""),
) -> dict[str, Any]:
    """Transcribe an uploaded audio file via whisper-cli.

    Works in two modes:
    - note_id provided: save audio alongside the note, return transcript.
    - note_id omitted:  transcribe a temporary file (used for live STT dictation).
    """
    import tempfile

    if note_id:
        db = await _db(space)
        audio_path = db.audio_path(note_id)
        audio_path.parent.mkdir(parents=True, exist_ok=True)
        with audio_path.open("wb") as f:
            shutil.copyfileobj(file.file, f)
        try:
            transcript = await transcribe(audio_path)
        except (FileNotFoundError, RuntimeError):
            log.info("transcribe_note_skip_no_stt", space=space, note_id=note_id)
            return {"transcript": "", "audio_path": str(audio_path.relative_to(_space_dir(space)))}
        log.info("transcribe_note", space=space, note_id=note_id, chars=len(transcript))
        return {"transcript": transcript, "audio_path": str(audio_path.relative_to(_space_dir(space)))}
    else:
        # Temporary file for live dictation — not persisted
        if not is_stt_available():
            raise HTTPException(
                503,
                detail=(
                    "STT is not configured. "
                    "Set [stt] provider in config.toml and ensure the provider "
                    "is installed (local: python scripts/install-whisper.py; "
                    "API: add the api_key for openai / groq / deepgram / assemblyai)."
                ),
            )
        suffix = Path(file.filename or "audio.webm").suffix or ".webm"
        with tempfile.NamedTemporaryFile(suffix=suffix, delete=False) as tmp:
            tmp_path = Path(tmp.name)
            shutil.copyfileobj(file.file, tmp)
        try:
            transcript = await transcribe(tmp_path)
            log.info("transcribe_stt", space=space, chars=len(transcript))
        finally:
            tmp_path.unlink(missing_ok=True)
        return {"transcript": transcript}


@roadmap_router.post("/{space}/transcribe-subtitle")
async def transcribe_subtitle(
    space: str,
    note_id: str = Query(...),
) -> dict[str, Any]:
    """Transcribe a media note's file via Whisper and embed the transcript into body_md.

    Uses the already-stored media file on disk — no re-upload needed.
    Returns {transcript, note} where note is the updated NoteRow.
    """
    db   = await _db(space)
    note = await db.get_note(note_id)
    if not note:
        raise HTTPException(404, "Note not found")
    path_str = note.video_path or note.audio_path
    if not path_str:
        raise HTTPException(400, "Note has no media file")
    media_path = Path(path_str)
    if not media_path.exists():
        raise HTTPException(404, "Media file missing from disk")

    if not is_stt_available():
        log.info("transcribe_subtitle_skip_no_stt", space=space, note_id=note_id)
        return {"transcript": "", "note": note.model_dump()}

    vtt = await transcribe_vtt(media_path)
    log.info("transcribe_subtitle", space=space, note_id=note_id, chars=len(vtt), format="vtt")

    updated = await db.update_note(note_id, title=note.title, body_md=vtt)

    # Store transcript in user_activity for analysis pipeline
    try:
        from sarthak.spaces.roadmap.media_analysis import vtt_to_plain
        plain = vtt_to_plain(vtt) if "WEBVTT" in vtt else vtt
        note_type = "video_note" if note.video_path else "audio_note"
        await _record_activity(
            activity_type=note_type,  # type: ignore[arg-type]
            space_dir=str(_space_dir(space)),
            concept_id=note.concept_id,
            content_text=plain[:8192],  # full transcript for analysis
            media_path=note.video_path or note.audio_path or "",
            metadata={"note_id": note_id, "vtt": vtt[:4096], "transcribed": True},
            db=db,
        )
    except Exception:
        pass

    # Schedule SRS review for the concept now that transcript is available
    if note.concept_id and vtt:
        from .srs import sync_note_card
        roadmap2 = await db.load_roadmap()
        concept_title = note.concept_id
        if roadmap2:
            cn2 = roadmap2.get_concept(note.concept_id)
            if cn2:
                concept_title = cn2.title
        db_path = str(_space_dir(space) / ".spaces" / "sarthak.db")
        try:
            await sync_note_card(db_path, note_id, concept_title)
        except Exception as exc:
            log.warning("srs_media_sync_failed", note_id=note_id, error=str(exc))

    return {"transcript": vtt, "note": updated.model_dump()}


# ── Graph ────────────────────────────────────────────────────────────────────

@roadmap_router.get("/{space}/graph")
async def get_graph(space: str) -> dict[str, Any]:
    db = await _db(space)
    roadmap = await db.load_roadmap()
    if roadmap is None:
        return {"nodes": [], "links": []}
    nodes: list[dict[str, Any]] = []
    links: list[dict[str, Any]] = []
    for ch in roadmap.chapters:
        for tp in ch.topics:
            for cn in tp.concepts:
                nodes.append({
                    "id":      cn.id,
                    "title":   cn.title,
                    "status":  cn.status.value,
                    "chapter": ch.title,
                    "topic":   tp.title,
                    "tags":    cn.tags,
                })
                for rel in cn.related_concepts:
                    links.append({"source": cn.id, "target": rel})
    return {"nodes": nodes, "links": links}


# ── SRS ──────────────────────────────────────────────────────────────────────

@roadmap_router.get("/{space}/srs")
async def srs_concept_due(space: str) -> dict[str, Any]:
    """Concept-based SRS list for the frontend dashboard.

    Returns all concepts from the roadmap that are due for review today
    (or have never been reviewed). Uses concept_id as the SM-2 key.
    """
    from datetime import date

    from .srs import srs_status

    db_path = str(_space_dir(space) / ".spaces" / "sarthak.db")
    db      = await _db(space)
    roadmap = await db.load_roadmap()
    if roadmap is None:
        return {"due": []}

    today  = str(date.today())
    result = []
    for ch in roadmap.chapters:
        for tp in ch.topics:
            for cn in tp.concepts:
                card = await srs_status(db_path, cn.id)
                # Include if never reviewed OR due today or overdue
                if card is None or card.next_due <= today:
                    result.append({
                        "id":           cn.id,
                        "title":        cn.title,
                        "description":  cn.description or "",
                        "chapter_title": ch.title,
                        "topic_title":   tp.title,
                        "due_date":      card.next_due if card else today,
                        "ease_factor":   round(card.easiness, 2) if card else 2.5,
                        "interval":      card.interval if card else 1,
                        "repetitions":   card.repetitions if card else 0,
                    })
    return {"due": result}


@roadmap_router.post("/{space}/srs/rate")
async def srs_rate_concept(space: str, body: dict[str, Any] = Body(...)) -> dict[str, Any]:
    """Rate a concept review from the frontend SRS panel.

    Accepts {concept_id, rating} (rating 1-5 maps to SM-2 grade 0-5).
    """
    from .srs import record_review

    db_path    = str(_space_dir(space) / ".spaces" / "sarthak.db")
    concept_id = body.get("concept_id", "")
    rating     = int(body.get("rating", 3))
    if not concept_id:
        raise HTTPException(status_code=422, detail="concept_id required")
    # Frontend sends 1-5; SM-2 expects 0-5 (1→1, 5→5 — compatible as-is)
    card = await record_review(db_path, concept_id, rating)
    return {"ok": True, "next_due": card.next_due, "interval": card.interval}


# ── Digest ────────────────────────────────────────────────────────────────────

def _digest_subscribe_path(space_dir: Path) -> Path:
    p = space_dir / ".spaces" / "digest_subscribe.json"
    p.parent.mkdir(parents=True, exist_ok=True)
    return p


@roadmap_router.get("/{space}/digest/subscribe")
async def get_digest_subscribe(space: str) -> dict[str, Any]:
    """Return current Telegram digest subscription state."""
    path = _digest_subscribe_path(_space_dir(space))
    if not path.exists():
        return {"subscribed": False}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {"subscribed": False}


@roadmap_router.post("/{space}/digest/subscribe")
async def set_digest_subscribe(space: str, body: dict[str, Any] = Body(...)) -> dict[str, Any]:
    """Persist Telegram digest subscription preference."""
    subscribed = bool(body.get("subscribed", False))
    path = _digest_subscribe_path(_space_dir(space))
    payload = {"subscribed": subscribed}
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    return payload


@roadmap_router.get("/{space}/digest")
async def get_digest(
    space: str,
    send_telegram: bool = Query(default=False),
    refresh: bool = Query(default=False),
) -> dict[str, Any]:
    from datetime import date

    from sarthak.agents.roadmap_agents import build_digest, send_digest_telegram
    sd    = _space_dir(space)
    db    = await _db(space)
    today = date.today().isoformat()

    if not refresh:
        cached = await db.load_digest(today)
        if cached:
            if send_telegram:
                await send_digest_telegram(sd, space)
            return {"digest": cached, "cached": True}

    digest = await build_digest(sd, space)
    await db.save_digest(today, digest)
    if send_telegram:
        await send_digest_telegram(sd, space)
    return {"digest": digest, "cached": False}


# ── Explain SSE ───────────────────────────────────────────────────────────────

@roadmap_router.get("/{space}/explain")
async def explain_concept(space: str, concept_id: str = Query(...), prompt: str = Query(default="")) -> Any:
    from fastapi.responses import StreamingResponse

    from sarthak.agents.roadmap_agents import stream_explain
    db      = await _db(space)
    roadmap = await db.load_roadmap()
    if roadmap is None:
        raise HTTPException(status_code=404, detail="Roadmap not initialized")
    cn = roadmap.get_concept(concept_id)
    if cn is None:
        raise HTTPException(status_code=404, detail="Concept not found")
    ch_title = tp_title = ""
    for ch in roadmap.chapters:
        for tp in ch.topics:
            if any(c.id == concept_id for c in tp.concepts):
                ch_title, tp_title = ch.title, tp.title
                break
    log.info("explain_start", space=space, concept_id=concept_id, concept=cn.title, has_prompt=bool(prompt))

    async def _logged_stream():
        token_count = 0
        try:
            async for chunk in stream_explain(cn.title, cn.description, ch_title, tp_title, user_prompt=prompt):
                token_count += 1
                yield chunk
            log.info("explain_done", space=space, concept=cn.title, chunks=token_count)
        except Exception as exc:
            log.error("explain_error", space=space, concept=cn.title, error=str(exc))
            raise

    return StreamingResponse(
        _logged_stream(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


# ── Session Tagging ───────────────────────────────────────────────────────────

@roadmap_router.post("/{space}/tag-session")
async def tag_session_endpoint(space: str, body: dict[str, Any] = Body(...)) -> dict[str, Any]:
    from .session_tag import tag_session
    sd     = _space_dir(space)
    result = await tag_session(
        sd,
        command=body.get("command", ""),
        cwd=body.get("cwd", ""),
        concept_id=body.get("concept_id"),
    )
    return {"ok": True, "matched": result}


@roadmap_router.get("/{space}/session-tags")
async def session_tags(space: str, limit: int = Query(default=50)) -> dict[str, Any]:
    from .session_tag import get_session_tags
    sd   = _space_dir(space)
    tags = get_session_tags(sd, last_n=limit)
    return {"tags": tags}


# ── QuickTest Generation ──────────────────────────────────────────────────────

async def _sync_frontend_note(space: str, db: RoadmapDB, note: NoteRow) -> None:
    if note.type in ("audio", "video"):
        return
    if not note.body_md.strip():
        return
    roadmap = await db.load_roadmap()
    concept, tags = _resolve_note_scope(roadmap, note, space)
    await sync_frontend_note(
        _space_dir(space),
        note.id,
        concept,
        note.title,
        note.body_md,
        tags=tags,
        created_at=note.created_at,
    )


def _resolve_note_scope(
    roadmap: Roadmap | None,
    note: NoteRow,
    space: str,
) -> tuple[str, list[str]]:
    chapter = None
    topic = None
    concept = None
    if roadmap:
        for ch in roadmap.chapters:
            if ch.id == note.chapter_id:
                chapter = ch
            for tp in ch.topics:
                if tp.id == note.topic_id:
                    topic = tp
                    chapter = ch
                for cn in tp.concepts:
                    if cn.id == note.concept_id:
                        concept = cn
                        topic = tp
                        chapter = ch

    tags: list[str] = []
    if concept:
        tags.append("scope:concept")
        tags.append(f"concept:{concept.title}")
    elif topic:
        tags.append("scope:topic")
        tags.append(f"topic:{topic.title}")
    elif chapter:
        tags.append("scope:chapter")
        tags.append(f"chapter:{chapter.title}")
    else:
        tags.append("scope:space")

    # Add breadcrumb tags — only if not already present (concept scope already added them above)
    if topic and f"topic:{topic.title}" not in tags:
        tags.append(f"topic:{topic.title}")
    if chapter and f"chapter:{chapter.title}" not in tags:
        tags.append(f"chapter:{chapter.title}")

    if concept:
        return concept.title, tags
    if topic:
        return f"Topic: {topic.title}", tags
    if chapter:
        return f"Chapter: {chapter.title}", tags
    name = roadmap.space if roadmap else space
    return f"Space: {name}", tags


# ── Code Playground ─────────────────────────────────────────────────────────────

from .playground import (  # noqa: E402
    execute as _pg_execute,
    available_languages as _pg_langs,
    explain_error as _pg_explain,
    generate_concept_code as _pg_generate,
)


@roadmap_router.get("/{space}/playground/languages")
async def playground_languages(space: str) -> list[dict]:
    return _pg_langs()


@roadmap_router.post("/{space}/playground/run")
async def playground_run(space: str, body: dict[str, Any] = Body(...)) -> dict[str, Any]:
    language = body.get("language", "python")
    code     = body.get("code", "")
    stdin    = body.get("stdin", "")
    if not code.strip():
        raise HTTPException(400, "code is required")
    result = await _pg_execute(language, code, stdin, space=space, helper_code=body.get("helper_code", ""))
    # Persist run to history and global activity store
    if result.get("exit_code") is not None:
        try:
            db = await _db(space)
            run_meta = json.dumps({
                "stdout": result["stdout"][:4096],
                "stderr": result["stderr"][:2048],
                "exit_code": result["exit_code"],
            })
            # Store run output in body_md; title carries language + exit code
            await db.create_note(NoteRow(
                id=str(uuid.uuid4()),
                concept_id=body.get("concept_id", ""),
                title=f"[{language}] exit={result['exit_code']}",
                body_md=code + "\n\n---\n" + run_meta,
                type="run_history",
            ))
        except Exception:
            pass
        try:
            await _record_activity(
                activity_type="code_run",
                space_dir=str(_space_dir(space)),
                concept_id=body.get("concept_id", ""),
                content_text=code[:4096],
                metadata={
                    "language": language,
                    "exit_code": result.get("exit_code"),
                    "success": result.get("exit_code") == 0,
                },
            )
        except Exception:
            pass
    return result


@roadmap_router.post("/{space}/playground/explain-error")
async def playground_explain_error(space: str, body: dict[str, Any] = Body(...)) -> dict[str, Any]:
    explanation = await _pg_explain(
        body.get("language", "python"),
        body.get("code", ""),
        body.get("stderr", ""),
        body.get("stdout", ""),
    )
    return {"explanation": explanation}


@roadmap_router.post("/{space}/playground/generate-code")
async def playground_generate_code(space: str, body: dict[str, Any] = Body(...)) -> dict[str, Any]:
    db = await _db(space)
    roadmap = await db.load_roadmap()
    desc = ""
    if roadmap and body.get("concept_id"):
        cn = roadmap.get_concept(body["concept_id"])
        if cn: desc = cn.description
    code = await _pg_generate(
        body.get("language", "python"),
        body.get("concept_title", ""),
        desc,
    )
    return {"code": code}


@roadmap_router.get("/{space}/playground/history")
async def playground_history(
    space: str,
    concept_id: str = Query(default=""),
    limit: int = Query(default=20),
) -> list[dict[str, Any]]:
    db = await _db(space)
    rows = await db.list_notes(concept_id=concept_id, note_type="run_history")
    return [r.model_dump() for r in rows[:limit]]


@roadmap_router.get("/{space}/playground/snippets")
async def list_snippets(
    space: str,
    concept_id: str = Query(default=""),
) -> list[dict[str, Any]]:
    db = await _db(space)
    rows = await db.list_notes(concept_id=concept_id, note_type="snippet")
    return [r.model_dump() for r in rows]


@roadmap_router.post("/{space}/playground/snippets")
async def save_snippet(space: str, body: dict[str, Any] = Body(...)) -> dict[str, Any]:
    db = await _db(space)
    lang  = body.get("language", "python")
    title = body.get("title") or "Snippet"
    raw_code = body.get("code", "")
    if raw_code:
        m = _re.match(r'^(?://|#|--) language: (\w+)$', raw_code.split("\n", 1)[0])
        if m:
            lang = m.group(1)
    note = NoteRow(
        id=str(uuid.uuid4()),
        concept_id=body.get("concept_id", ""),
        title=f"[{lang}] {title}",
        body_md=raw_code,
        type="snippet",
    )
    saved = await db.create_note(note)
    return saved.model_dump()


@roadmap_router.put("/{space}/playground/snippets/{note_id}")
async def update_snippet(space: str, note_id: str, body: dict[str, Any] = Body(...)) -> dict[str, Any]:
    db = await _db(space)
    note = await db.get_note(note_id)
    if not note or note.type != "snippet":
        raise HTTPException(404, "Snippet not found")
    raw_code = body.get("code", note.body_md)
    header_lang = None
    if raw_code:
        m = _re.match(r'^(?://|#|--) language: (\w+)$', raw_code.split("\n", 1)[0])
        if m:
            header_lang = m.group(1)
    lang  = header_lang or body.get("language") or note.title.split("]")[0].lstrip("[")
    title = body.get("title") or note.title.split("] ", 1)[-1]
    updated = await db.update_note(note_id, title=f"[{lang}] {title}", body_md=raw_code)
    return updated.model_dump()


@roadmap_router.delete("/{space}/playground/snippets/{note_id}")
async def delete_snippet(space: str, note_id: str) -> dict[str, Any]:
    db = await _db(space)
    note = await db.get_note(note_id)
    if not note or note.type != "snippet":
        raise HTTPException(404, "Snippet not found")
    await db.delete_note(note_id)
    return {"ok": True}


# ── Space-scoped Agents ───────────────────────────────────────────────────────


class SpaceAgentCreate(_BaseModel):
    description: str
    notify_telegram: bool = False


@roadmap_router.get("/{space}/agents")
async def list_space_agents(space: str) -> list[dict]:
    from sarthak.agents.store import list_agents
    from sarthak.agents.models import AgentScope
    agents = list_agents(space_dir=_space_dir(space))
    return [a.model_dump() for a in agents if a.scope == AgentScope.SPACE]


@roadmap_router.post("/{space}/agents")
async def create_space_agent(space: str, body: SpaceAgentCreate) -> dict:
    from sarthak.agents.creator import create_agent_from_description
    spec = await create_agent_from_description(
        body.description, space_dir=_space_dir(space),
        notify_telegram=body.notify_telegram or None,
    )
    return spec.model_dump()


@roadmap_router.post("/{space}/agents/{agent_id}/run")
async def run_space_agent(space: str, agent_id: str) -> dict:
    from sarthak.agents.store import load_agent
    from sarthak.agents.runner import run_agent
    spec = load_agent(agent_id)
    if not spec:
        raise HTTPException(404, "Agent not found")
    run = await run_agent(spec)
    return {"success": run.success, "output": run.output, "error": run.error, "run_id": run.run_id}


@roadmap_router.get("/{space}/agents/{agent_id}/logs")
async def space_agent_logs(space: str, agent_id: str, limit: int = Query(default=5)) -> list[dict]:
    from sarthak.agents.store import load_runs
    return [r.model_dump() for r in load_runs(agent_id, limit=limit)]


@roadmap_router.delete("/{space}/agents/{agent_id}")
async def delete_space_agent(space: str, agent_id: str) -> dict:
    from sarthak.agents.store import delete_agent
    if not delete_agent(agent_id):
        raise HTTPException(404, "Agent not found")
    return {"ok": True}


@roadmap_router.patch("/{space}/agents/{agent_id}")
async def patch_space_agent(space: str, agent_id: str, body: dict = Body(...)) -> dict:
    from sarthak.agents.store import update_agent
    spec = update_agent(agent_id, **body)
    if not spec:
        raise HTTPException(404, "Agent not found")
    return spec.model_dump()
