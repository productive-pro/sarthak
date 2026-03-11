"""
Sarthak Spaces — Notes: OCR pipeline + concept note taker.

Two entry points:
  1. image_to_note(image_path, concept)  → str (Markdown note)
     Converts a photo of handwriting or a diagram to a structured Markdown note.
     Pipeline:
       Primary  — Anthropic vision model (claude-3-5-haiku or configured vision model)
       Fallback — Tesseract OCR → raw text → LLM structures it into Markdown note

  2. take_concept_note(space_dir, concept, content, source)  → NoteRecord
     Saves a structured concept note to .spaces/notes/ and triggers RAG reindex.
     Content can be free text, pasted code, or the output of image_to_note().

Notes are plain Markdown files: <space>/.spaces/notes/<concept_slug>/<timestamp>.md
They are first-class RAG sources — the note folder is indexed along with everything else.

Public API:
    image_to_note(image_path, concept, space_dir)       → str (Markdown)
    take_concept_note(space_dir, concept, content, ...)  → NoteRecord
    load_notes(space_dir, concept)                       → list[NoteRecord]
    load_all_notes(space_dir, since_days)                → list[NoteRecord]
    notes_summary_for_context(space_dir, concept, n)     → str  (inject into LLM prompts)
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from sarthak.core.logging import get_logger

log = get_logger(__name__)

_NOTES_DIR = ".spaces/notes"
_SUPPORTED_IMAGE_EXTS = {".jpg", ".jpeg", ".png", ".webp", ".gif", ".bmp", ".tiff", ".tif"}

_DOC_LLM_PROMPT = (
    "You are given raw text extracted from a document. "
    "Convert it into a clean, structured Markdown note. "
    "Preserve ALL content. Use ## headers, bullet points, and add a "
    "## Key Concepts section at the end. Output ONLY the Markdown."
)


async def document_to_note(
    file_path: Path,
    concept: str,
) -> str:
    """Convert a document → structured Markdown via MarkItDown + LLM."""
    import asyncio

    from markitdown import MarkItDown

    try:
        loop = asyncio.get_running_loop()
        result = await loop.run_in_executor(None, lambda: MarkItDown().convert(str(file_path)))
        text = (result.text_content or "").strip()
    except Exception as exc:
        log.warning("markitdown_doc_failed", path=str(file_path), error=str(exc))
        text = ""

    if not text:
        return (
            f"# {concept}\n\n*Note: Could not extract content from "
            f"{file_path.name}. Please add text manually.*\n"
        )

    client, model = _build_llm_client()
    if client:
        prompt = f"This document is about: {concept}.\n\nRaw text:\n{text}\n\n{_DOC_LLM_PROMPT}"

        def _call_llm() -> str:
            resp = client.chat.completions.create(
                model=model,
                messages=[
                    {"role": "system", "content": "You convert raw text into Markdown notes."},
                    {"role": "user", "content": prompt},
                ],
                temperature=0.2,
            )
            return (resp.choices[0].message.content or "").strip()

        try:
            loop = asyncio.get_running_loop()
            md = await loop.run_in_executor(None, _call_llm)
            if md:
                return md
        except Exception as exc:
            log.warning("markitdown_doc_llm_failed", path=str(file_path), error=str(exc))

    if not text.startswith("#"):
        return f"# {concept}\n\n{text}"
    return text


async def file_to_note(
    file_path: Path,
    concept: str,
) -> str:
    """Convert any supported file to a Markdown note."""
    if file_path.suffix.lower() in _SUPPORTED_IMAGE_EXTS:
        return await image_to_note(file_path, concept)
    return await document_to_note(file_path, concept)


# ── Models ─────────────────────────────────────────────────────────────────────

@dataclass
class NoteRecord:
    note_id: str
    concept: str
    content_md: str
    source: str          # "manual" | "image_ocr" | "paste" | "session"
    image_path: str = ""
    created_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    tags: list[str] = field(default_factory=list)
    space_dir: str = ""

    def to_dict(self) -> dict:
        return {
            "note_id":    self.note_id,
            "concept":    self.concept,
            "content_md": self.content_md,
            "source":     self.source,
            "image_path": self.image_path,
            "created_at": self.created_at,
            "tags":       self.tags,
            "space_dir":  self.space_dir,
        }

    @staticmethod
    def from_dict(d: dict) -> "NoteRecord":
        return NoteRecord(
            note_id=d.get("note_id", ""),
            concept=d.get("concept", ""),
            content_md=d.get("content_md", ""),
            source=d.get("source", "manual"),
            image_path=d.get("image_path", ""),
            created_at=d.get("created_at", ""),
            tags=d.get("tags", []),
            space_dir=d.get("space_dir", ""),
        )


# ── Slugify ────────────────────────────────────────────────────────────────────

def _slug(text: str) -> str:
    return re.sub(r"[^a-z0-9_-]", "_", text.lower().strip())[:60]


def _note_id() -> str:
    from datetime import datetime, timezone
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S")


# ── Config helper ──────────────────────────────────────────────────────────────

def _load_ai_config() -> dict[str, Any]:
    try:
        from sarthak.core.config import load_config
        return load_config()
    except Exception:
        return {}


# ── MarkItDown OCR ─────────────────────────────────────────────────────────────

_OCR_LLM_PROMPT = (
    "Convert this image of handwritten notes or a diagram to a clean, "
    "structured Markdown note. Preserve ALL content. "
    "Format math as LaTeX ($inline$, $$block$$). "
    "Use ## headers, bullet points, and add a ## Key Concepts section at the end. "
    "Output ONLY the Markdown — no preamble."
)


def _build_llm_client() -> tuple[Any, str] | tuple[None, None]:
    """
    Return (sync openai.OpenAI client, model) using the project's ProviderConfig
    so that encrypted ENC:... keys and all configured providers are supported.
    Provider priority: default_provider from config, then fallback order.
    """
    from openai import OpenAI

    from sarthak.core.ai_utils.multi_provider import Provider, ProviderConfig

    cfg = _load_ai_config()
    ai_cfg = cfg.get("ai", {})

    # Providers that expose an OpenAI-compatible sync endpoint; ordered by preference.
    _PROVIDER_DEFAULTS: list[tuple[Provider, str | None]] = [
        (Provider.OPENROUTER, "https://openrouter.ai/api/v1"),
        (Provider.OPENAI,     None),
        (Provider.ANTHROPIC,  "https://api.anthropic.com/v1"),
        (Provider.OLLAMA,     "http://localhost:11434/v1"),
    ]

    default_provider_str = ai_cfg.get("default_provider", "ollama")
    try:
        default_provider = Provider.from_str(default_provider_str)
    except Exception:
        default_provider = Provider.OLLAMA

    # Re-order so the configured default is tried first.
    ordered = sorted(
        _PROVIDER_DEFAULTS,
        key=lambda t: 0 if t[0] == default_provider else 1,
    )

    for provider, base_url in ordered:
        pc = ProviderConfig(provider, cfg)
        if not pc.is_configured():
            continue
        # Prefer vision_model when available, else default_model.
        # Prefer explicitly configured vision model, then provider default
        vision_cfg = ai_cfg.get("vision", {})
        vis_prov = vision_cfg.get("provider", "")
        vis_model = vision_cfg.get("model", "")
        model = (
            (vis_model if vis_prov == pc.provider.value.replace("_", "-") else "")
            or pc.default_model
            or "gpt-4o"
        )
        client_kwargs: dict[str, Any] = {
            "api_key": pc.api_key or "none",
            "timeout": pc.timeout,
        }
        if base_url:
            client_kwargs["base_url"] = base_url
        elif pc.base_url:
            client_kwargs["base_url"] = pc.base_url
        return OpenAI(**client_kwargs), model

    return None, None


async def _markitdown_ocr(image_path: Path, concept: str) -> str:
    """Convert image → structured Markdown via MarkItDown (with LLM if available)."""
    import asyncio

    from markitdown import MarkItDown

    client, model = _build_llm_client()
    prompt = f"This image is about: {concept}. " + _OCR_LLM_PROMPT

    if client:
        md = MarkItDown(llm_client=client, llm_model=model, llm_prompt=prompt)
    else:
        md = MarkItDown()

    try:
        loop = asyncio.get_running_loop()
        result = await loop.run_in_executor(None, lambda: md.convert(str(image_path)))
        text = (result.text_content or "").strip()
    except Exception as exc:
        log.warning("markitdown_ocr_failed", path=str(image_path), error=str(exc))
        text = ""

    if not text:
        return (
            f"# {concept}\n\n*Note: Could not extract content from "
            f"{image_path.name}. Please add text manually.*\n"
        )
    if not text.startswith("#"):
        text = f"# {concept}\n\n{text}"
    return text


# ── Main OCR entry point ───────────────────────────────────────────────────────

async def image_to_note(
    image_path: Path,
    concept: str,
    space_dir: Path | None = None,
) -> str:
    """
    Convert a photo of handwriting / diagram → Markdown note via MarkItDown.
    Uses an LLM vision client when configured (OpenAI or Anthropic), otherwise
    falls back to MarkItDown's built-in EXIF/metadata extraction.
    If space_dir is given, automatically saves and RAG-indexes the result.
    Returns the Markdown string.
    """
    image_path = Path(image_path)
    if not image_path.exists():
        raise FileNotFoundError(f"Image not found: {image_path}")
    if image_path.suffix.lower() not in _SUPPORTED_IMAGE_EXTS:
        raise ValueError(f"Unsupported image type: {image_path.suffix}")

    log.info("ocr_start", path=str(image_path), concept=concept)
    md = await _markitdown_ocr(image_path, concept)
    log.info("ocr_done", chars=len(md))

    if space_dir:
        await take_concept_note(
            space_dir, concept, md,
            source="image_ocr",
            image_path=str(image_path),
        )
    return md


# ── Concept note taker ─────────────────────────────────────────────────────────

async def take_concept_note(
    space_dir: Path,
    concept: str,
    content: str,
    source: str = "manual",
    image_path: str = "",
    tags: list[str] | None = None,
    reindex: bool = True,
) -> NoteRecord:
    """
    Save a concept note to .spaces/notes/<concept_slug>/<timestamp>.md
    and auto-trigger RAG reindex so the note is immediately searchable.

    Args:
        space_dir:  Root of the Sarthak space.
        concept:    Concept this note is about (e.g. "Linear Regression").
        content:    Markdown content to save.
        source:     One of "manual", "image_ocr", "paste", "session".
        image_path: Original image path if source=="image_ocr".
        tags:       Optional list of concept/topic tags.
        reindex:    If True, trigger incremental RAG reindex after saving.

    Returns:
        NoteRecord with the saved note metadata.
    """
    space_dir = Path(space_dir)
    concept_dir = space_dir / _NOTES_DIR / _slug(concept)
    concept_dir.mkdir(parents=True, exist_ok=True)

    note_id = _note_id()
    note_file = concept_dir / f"{note_id}.md"

    # Build Markdown with frontmatter header comment
    header = (
        f"<!-- note_id: {note_id} | concept: {concept} | "
        f"source: {source} | created: {datetime.now(timezone.utc).isoformat()} -->\n\n"
    )
    # Ensure content has a proper heading
    if not content.strip().startswith("#"):
        full_content = f"# {concept}\n\n{content}"
    else:
        full_content = content

    note_file.write_text(header + full_content, encoding="utf-8")

    record = NoteRecord(
        note_id=note_id,
        concept=concept,
        content_md=full_content,
        source=source,
        image_path=image_path,
        tags=tags or [],
        space_dir=str(space_dir),
    )

    # Save metadata to notes index (upsert to avoid duplicates on retry)
    _upsert_note_index(space_dir, record)

    log.info("note_saved", concept=concept, path=str(note_file), source=source)

    # Trigger RAG reindex + SRS card update
    if reindex:
        import asyncio
        try:
            loop = asyncio.get_running_loop()
            loop.create_task(_reindex_notes(space_dir))
            loop.create_task(_update_srs_for_note(space_dir, record.note_id, concept))
        except RuntimeError:
            pass  # not in an async context — skip background reindex

    return record


async def _reindex_notes(space_dir: Path) -> None:
    """Background reindex — silently swallow errors."""
    try:
        from sarthak.spaces.rag import index_space
        await index_space(space_dir, incremental=True)
    except Exception as exc:
        log.debug("note_bg_reindex_failed", error=str(exc))


async def _update_srs_for_note(space_dir: Path, note_id: str, concept: str) -> None:
    """Background SRS card update when a note is written — silently swallow errors."""
    try:
        from sarthak.spaces.roadmap.srs import sync_note_card
        db_path = str(space_dir / ".spaces" / "sarthak.db")
        await sync_note_card(db_path, note_id, concept)
    except Exception as exc:
        log.debug("note_srs_update_failed", error=str(exc))


# ── Frontend note sync (DB notes -> notes index) ──────────────────────────────

def _load_note_index(space_dir: Path) -> list[NoteRecord]:
    path = _index_path(space_dir)
    if not path.exists():
        return []
    records: list[NoteRecord] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        try:
            records.append(NoteRecord.from_dict(json.loads(line)))
        except (json.JSONDecodeError, KeyError, TypeError):
            pass
    return records


def _write_note_index(space_dir: Path, records: list[NoteRecord]) -> None:
    path = _index_path(space_dir)
    with path.open("w", encoding="utf-8") as f:
        for record in records:
            f.write(json.dumps(record.to_dict()) + "\n")


def _upsert_note_index(space_dir: Path, record: NoteRecord) -> None:
    records = _load_note_index(space_dir)
    records = [r for r in records if r.note_id != record.note_id]
    records.append(record)
    _write_note_index(space_dir, records)


def _remove_note_index(space_dir: Path, note_id: str) -> NoteRecord | None:
    records = _load_note_index(space_dir)
    match = next((r for r in records if r.note_id == note_id), None)
    if not match:
        return None
    records = [r for r in records if r.note_id != note_id]
    _write_note_index(space_dir, records)
    return match


async def sync_frontend_note(
    space_dir: Path,
    note_id: str,
    concept: str,
    title: str,
    content: str,
    tags: list[str] | None = None,
    source: str = "frontend",
    created_at: str = "",
    reindex: bool = True,
) -> NoteRecord:
    """
    Sync a frontend note (from the DB) into .spaces/notes + notes_index.jsonl
    so learner context and RAG can use it.
    """
    space_dir = Path(space_dir)
    concept_dir = space_dir / _NOTES_DIR / _slug(concept)
    concept_dir.mkdir(parents=True, exist_ok=True)

    note_file = concept_dir / f"{note_id}.md"
    created = created_at or datetime.now(timezone.utc).isoformat()
    header = (
        f"<!-- note_id: {note_id} | concept: {concept} | "
        f"source: {source} | created: {created} -->\n\n"
    )
    heading = title or concept
    full_content = content
    if not content.strip().startswith("#"):
        full_content = f"# {heading}\n\n{content}"

    note_file.write_text(header + full_content, encoding="utf-8")

    record = NoteRecord(
        note_id=note_id,
        concept=concept,
        content_md=full_content,
        source=source,
        tags=tags or [],
        space_dir=str(space_dir),
        created_at=created,
    )
    _upsert_note_index(space_dir, record)

    if reindex:
        import asyncio
        try:
            loop = asyncio.get_running_loop()
            loop.create_task(_reindex_notes(space_dir))
        except RuntimeError:
            pass  # not in an async context

    return record


def remove_frontend_note(space_dir: Path, note_id: str) -> None:
    """Remove a synced frontend note from index + filesystem."""
    record = _remove_note_index(space_dir, note_id)
    if not record:
        return
    note_path = space_dir / _NOTES_DIR / _slug(record.concept) / f"{note_id}.md"
    if note_path.exists():
        note_path.unlink(missing_ok=True)

# ── Note index (fast lookup) ───────────────────────────────────────────────────

def _index_path(space_dir: Path) -> Path:
    p = space_dir / ".spaces" / "notes_index.jsonl"
    p.parent.mkdir(parents=True, exist_ok=True)
    return p


def load_notes(space_dir: Path, concept: str, limit: int = 20) -> list[NoteRecord]:
    """Load notes for a specific concept from the index."""
    slug = _slug(concept)
    path = _index_path(space_dir)
    if not path.exists():
        return []
    records = []
    for line in path.read_text(encoding="utf-8").splitlines():
        try:
            d = json.loads(line)
            if _slug(d.get("concept", "")) == slug:
                records.append(NoteRecord.from_dict(d))
        except (json.JSONDecodeError, KeyError, TypeError):
            pass
    return records[-limit:]


def load_all_notes(space_dir: Path, since_days: int = 7) -> list[NoteRecord]:
    """Load all notes created within the last `since_days` days."""
    path = _index_path(space_dir)
    if not path.exists():
        return []
    cutoff = datetime.now(timezone.utc) - timedelta(days=since_days)
    records = []
    for line in path.read_text(encoding="utf-8").splitlines():
        try:
            d = json.loads(line)
            created = datetime.fromisoformat(d.get("created_at", "2000-01-01"))
            if created.tzinfo is None:
                created = created.replace(tzinfo=timezone.utc)
            if created >= cutoff:
                records.append(NoteRecord.from_dict(d))
        except (json.JSONDecodeError, ValueError, KeyError, TypeError):
            pass
    return records


def notes_summary_for_context(
    space_dir: Path,
    concept: str = "",
    n: int = 5,
) -> str:
    """
    Return a compact Markdown summary of recent notes — inject into LLM prompts.
    If concept is given, shows notes for that concept.
    Otherwise shows the n most recent notes across all concepts.
    """
    if concept:
        notes = load_notes(space_dir, concept, limit=n)
        header = f"## Recent Notes on {concept}"
    else:
        notes = load_all_notes(space_dir, since_days=14)[-n:]
        header = "## Recent Notes"

    if not notes:
        return ""

    lines = [header, ""]
    for note in notes:
        date_str = note.created_at[:10] if note.created_at else ""
        # Show first 300 chars of content
        snippet = note.content_md.replace("<!-- note_id:", "").strip()[:300]
        lines.append(f"**[{note.concept}]** ({date_str}, {note.source})")
        lines.append(snippet)
        lines.append("")
    return "\n".join(lines)
