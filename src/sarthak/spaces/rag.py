"""
Sarthak Spaces — RAG using sqlite-vec.

Storage layout per space directory:
    <space>/.sarthak_rag/
        sarthak.vec   — sqlite-vec database (chunks + float32 embeddings)
        mtimes.json   — mtime fingerprints for incremental indexing

Public API:
    index_space(directory, incremental=True)                   -> int
    index_paths(directory, rel_paths, pipeline="text")         -> int
    index_paths_streaming(directory, rel_paths, pipeline)      -> AsyncGenerator
    search_space(directory, query, top_k)                      -> str
    search_space_structured(directory, query, top_k)           -> list[SearchResult]
    list_indexed_files(directory)                              -> list[str]
    walk_space(directory)                                      -> list[dict]
    chat_with_file(file_path, question, history)               -> str
    rag_tool_for(directory)                                    -> async callable
    rag_status(directory)                                      -> dict
    export_activities_to_markdown(directory)                   -> list[str]
    start_watcher(directory)                                   -> Observer | None
    stop_watcher(observer)                                     -> None
"""
from __future__ import annotations

import asyncio
import json
import os
import re
import struct
import threading
import time
from pathlib import Path
from typing import Any, AsyncGenerator

import structlog

log = structlog.get_logger(__name__)

# ── Constants ──────────────────────────────────────────────────────────────────

_ALL_EXTS = {
    ".pdf", ".docx", ".doc", ".pptx", ".ppt", ".xlsx", ".xls",
    ".html", ".htm", ".epub", ".zip",
    ".txt", ".md", ".rst", ".py", ".js", ".ts", ".json", ".toml", ".yaml",
    ".yml", ".csv", ".xml", ".sh", ".r", ".ipynb", ".tex",
}
_SKIP_DIRS = {".sarthak_rag", ".git", "__pycache__", "node_modules", ".venv"}
_PLAINTEXT_EXTS = {
    ".txt", ".md", ".rst", ".py", ".js", ".ts", ".toml", ".yaml",
    ".yml", ".sh", ".r", ".tex", ".xml", ".json", ".csv", ".ipynb",
}
_VISION_EXTS = {".png", ".jpg", ".jpeg", ".gif", ".webp", ".bmp", ".tiff", ".tif"}
_SKIP_FILES_IN_SPACES = {
    "sessions.jsonl", "tests.jsonl", "test_results.jsonl",
    "notes_index.jsonl", "mtimes.json", "sarthak.vec", "sarthak.db",
}

# Chunking: paragraph-aware, token-friendly
_CHUNK_CHARS   = 400    # ~150 tokens — right-sized for most embedding models
_CHUNK_OVERLAP = 80     # 20% overlap
_MAX_FILE_KB   = 20480
_TOP_K         = 5
_MTIME_FILE    = "mtimes.json"
_DB_FILE       = "sarthak.vec"
_DEBOUNCE_S    = 1.0

_SCHEMA = """
PRAGMA journal_mode=WAL;
PRAGMA synchronous=NORMAL;

CREATE TABLE IF NOT EXISTS chunks (
    id      TEXT PRIMARY KEY,
    source  TEXT NOT NULL,
    chunk   INTEGER NOT NULL,
    line    INTEGER NOT NULL,
    text    TEXT NOT NULL
);

CREATE VIRTUAL TABLE IF NOT EXISTS chunks_fts USING fts5(
    id UNINDEXED,
    text,
    source UNINDEXED,
    content=chunks,
    content_rowid=rowid
);
"""

# ── Paths ──────────────────────────────────────────────────────────────────────

def _rag_dir(directory: Path) -> Path:
    d = directory / ".sarthak_rag"
    d.mkdir(exist_ok=True)
    return d

def _db_path(directory: Path) -> Path:
    return _rag_dir(directory) / _DB_FILE

def _legacy_db_path(directory: Path) -> Path:
    return directory / ".spaces" / _DB_FILE

def _mtime_path(directory: Path) -> Path:
    return _rag_dir(directory) / _MTIME_FILE

def _legacy_mtime_path(directory: Path) -> Path:
    return directory / ".spaces" / _MTIME_FILE

def _load_mtimes(directory: Path) -> dict[str, float]:
    for p in (_mtime_path(directory), _legacy_mtime_path(directory)):
        if p.exists():
            try:
                return json.loads(p.read_text(encoding="utf-8")) or {}
            except Exception:
                return {}
    return {}

def _save_mtimes(directory: Path, mtimes: dict[str, float]) -> None:
    _mtime_path(directory).write_text(json.dumps(mtimes, indent=2), encoding="utf-8")

def _encode(vec: list[float]) -> bytes:
    return struct.pack(f"{len(vec)}f", *vec)

def _char_to_line(text: str, char_pos: int) -> int:
    return text.count("\n", 0, char_pos) + 1


# ── Recursive semantic chunker ────────────────────────────────────────────────
#
# Splitting priority (highest → lowest):
#   1. Markdown / document headings  (# H1, ## H2, UNIT I, 1.2 Topic …)
#   2. Double newline  (blank-line paragraph breaks — works for DOCX, TXT)
#   3. Single newline  (line breaks without blank lines — dense plain text)
#   4. Sentence boundary  (. / ? / ! followed by whitespace)
#   5. Hard character split  (last resort — e.g. a single 2 000-char sentence)
#
# Every level falls through to the next only when the current level produces
# segments that are still over _CHUNK_CHARS.  This makes the chunker work
# correctly for ALL file types with or without headings.

# Heading patterns — must occupy the full line
_HEADING_RE = re.compile(
    r"^(?:"
    r"#{1,6}\s+\S.*"                                  # Markdown: ## Title
    r"|(?:\d+\.)+\d*\s+\S.*"                           # Numbered: 1.2 Topic
    r"|(?:unit|section|chapter|part|module|topic)\s+[\dIVXivx]+.*"  # Unit I / Chapter 3
    r"|[A-Z][A-Z0-9 ]{3,}:?\s*"                        # ALL-CAPS HEADER:
    r")$",
    re.MULTILINE | re.IGNORECASE,
)

# Sentence boundary: period/question/exclamation + whitespace (not abbreviations)
_SENTENCE_RE = re.compile(r"(?<=[.?!])\s+")


def _split_at(text: str, pattern: re.Pattern | str, keep_delimiter: bool = False) -> list[str]:
    """Split text by regex pattern; return non-empty stripped parts."""
    parts = re.split(pattern, text)
    return [p.strip() for p in parts if p.strip()]


def _split_by_headings(text: str) -> list[str]:
    """
    Split text at heading lines, attaching each heading to the block that follows it.
    Falls back to [text] if no headings are found.
    """
    segments: list[str] = []
    last = 0
    for m in _HEADING_RE.finditer(text):
        pre = text[last:m.start()].strip()
        if pre:
            segments.append(pre)
        last = m.start()
    tail = text[last:].strip()
    if tail:
        segments.append(tail)
    return segments if len(segments) > 1 else [text]


def _atomic_splits(text: str) -> list[str]:
    """
    Recursively split text into pieces <= _CHUNK_CHARS using the priority ladder.
    Returns a flat list of strings, each <= _CHUNK_CHARS (except unavoidable edge cases).
    """
    if len(text) <= _CHUNK_CHARS:
        return [text]

    # Level 1 — headings
    parts = _split_by_headings(text)
    if len(parts) > 1:
        return [s for p in parts for s in _atomic_splits(p)]

    # Level 2 — blank-line paragraphs (works for DOCX, TXT, any prose)
    parts = _split_at(text, r"\n{2,}")
    if len(parts) > 1:
        return [s for p in parts for s in _atomic_splits(p)]

    # Level 3 — single newlines (line-wrapped plain text, code, CSV rows)
    parts = _split_at(text, r"\n")
    if len(parts) > 1:
        return [s for p in parts for s in _atomic_splits(p)]

    # Level 4 — sentence boundaries
    parts = _SENTENCE_RE.split(text)
    parts = [p.strip() for p in parts if p.strip()]
    if len(parts) > 1:
        return [s for p in parts for s in _atomic_splits(p)]

    # Level 5 — hard character split (last resort)
    result = []
    start = 0
    while start < len(text):
        result.append(text[start:start + _CHUNK_CHARS])
        start += _CHUNK_CHARS - _CHUNK_OVERLAP
    return result


def _chunk(text: str, path: str) -> list[dict[str, Any]]:
    """
    Produce overlapping chunks from text using the recursive semantic splitter.

    Works for every file type:
    - Markdown / RST / HTML   → heading-split
    - DOCX / TXT (paragraphs) → blank-line-split
    - Dense plain text        → sentence-split
    - Code files              → line-split then sentence-split
    - Worst case              → hard character-split

    Adjacent atomic pieces are packed into a buffer up to _CHUNK_CHARS with
    _CHUNK_OVERLAP carry-over so context is never cut cold.
    """
    atoms = _atomic_splits(text)

    chunks: list[dict[str, Any]] = []
    idx = 0
    buf = ""
    buf_line = 1
    char_cursor = 0  # tracks approximate char position in original text

    for atom in atoms:
        sep = "\n\n" if buf else ""
        if buf and len(buf) + len(sep) + len(atom) > _CHUNK_CHARS:
            # Flush current buffer
            chunks.append({
                "id":     f"{path}::{idx}",
                "text":   buf.strip(),
                "source": path,
                "chunk":  idx,
                "line":   buf_line,
            })
            idx += 1
            # Carry overlap into next buffer
            tail = buf[-_CHUNK_OVERLAP:].strip() if len(buf) > _CHUNK_OVERLAP else buf.strip()
            buf = tail + ("\n\n" + atom if tail else atom)
            buf_line = _char_to_line(text, max(0, char_cursor - _CHUNK_OVERLAP))
        else:
            if not buf:
                buf_line = _char_to_line(text, char_cursor)
            buf = buf + sep + atom if buf else atom

        char_cursor += len(atom) + 2  # +2 approximates separator

    # Flush remainder
    if buf.strip():
        chunks.append({
            "id":     f"{path}::{idx}",
            "text":   buf.strip(),
            "source": path,
            "chunk":  idx,
            "line":   buf_line,
        })

    # Safety: never return empty list
    if not chunks:
        chunks.append({"id": f"{path}::0", "text": text[:_CHUNK_CHARS].strip(),
                       "source": path, "chunk": 0, "line": 1})
    return chunks


# ── Text extraction ────────────────────────────────────────────────────────────

_markitdown: Any = None
_markitdown_vision: Any = None


def _get_markitdown(vision: bool = False) -> Any:
    global _markitdown, _markitdown_vision
    if vision:
        if _markitdown_vision is None:
            from markitdown import MarkItDown
            try:
                from sarthak.core.ai_utils.multi_provider import build_openai_client
                llm_client, llm_model = build_openai_client()
                _markitdown_vision = MarkItDown(llm_client=llm_client, llm_model=llm_model)
            except Exception:
                from markitdown import MarkItDown as _MD
                _markitdown_vision = _MD()
        return _markitdown_vision
    if _markitdown is None:
        from markitdown import MarkItDown
        _markitdown = MarkItDown()
    return _markitdown


def _extract_pdf(p: Path) -> str | None:
    """Extract PDF text preserving structure via pdfminer.six."""
    try:
        from pdfminer.high_level import extract_text as _pdfminer_extract
        text = _pdfminer_extract(str(p)).strip()
        return text or None
    except ImportError:
        pass
    except Exception as exc:
        log.debug("rag_pdf_pdfminer_failed", file=str(p), error=str(exc))
    # Fallback: MarkItDown
    return _extract_via_markitdown(p)


def _extract_via_markitdown(p: Path) -> str | None:
    try:
        md = _get_markitdown(vision=False)
        result = md.convert(str(p))
        # Support both MarkItDown API versions
        text = (
            getattr(result, "markdown", None)
            or getattr(result, "text_content", None)
            or ""
        ).strip()
        return text or None
    except Exception as exc:
        log.warning("rag_markitdown_failed", file=str(p), error=str(exc))
        return None


def _extract_text(p: Path, pipeline: str = "text") -> str | None:
    """
    Universal file → text extractor.

    Strategy:
    - Plain text/code: read directly (fast, no codec issues)
    - PDF: pdfminer.six for structure-preserving extraction, MarkItDown fallback
    - Everything else: MarkItDown (excellent for DOCX, PPTX, XLSX, HTML, EPUB, ZIP)
    - Vision pipeline: use MarkItDown with LLM hint for images
    """
    try:
        if p.suffix.lower() in _PLAINTEXT_EXTS:
            return p.read_text(encoding="utf-8", errors="replace").strip() or None

        if p.suffix.lower() == ".pdf":
            return _extract_pdf(p)

        if pipeline == "vision" and p.suffix.lower() in _VISION_EXTS:
            try:
                md = _get_markitdown(vision=True)
                result = md.convert(str(p))
                text = (
                    getattr(result, "markdown", None)
                    or getattr(result, "text_content", None)
                    or ""
                ).strip()
                return text or None
            except Exception:
                pass  # fall through to standard MarkItDown

        return _extract_via_markitdown(p)

    except ImportError:
        raise
    except Exception as exc:
        log.warning("rag_extract_error", file=str(p), error=str(exc))
        return None


# ── File iteration ─────────────────────────────────────────────────────────────

def _is_indexable(p: Path, directory: Path) -> bool:
    parts = p.parts[len(directory.parts):]
    if any(part in _SKIP_DIRS for part in parts):
        return False
    if ".spaces" in parts:
        if p.name in _SKIP_FILES_IN_SPACES:
            return False
        if p.suffix.lower() != ".md" and "notes" not in parts:
            return False
    if not p.is_file():
        return False
    if p.suffix.lower() not in _ALL_EXTS:
        return False
    if p.stat().st_size > _MAX_FILE_KB * 1024:
        return False
    return True


def _iter_files(directory: Path, pipeline: str = "text"):
    for p in directory.rglob("*"):
        if _is_indexable(p, directory):
            text = _extract_text(p, pipeline=pipeline)
            if text:
                yield p, text


# ── Embedder ───────────────────────────────────────────────────────────────────

def _get_embedder():
    """
    Build embedder from config.

    Config priority:
      [ai.embeddings]
      model = "provider:model-id"      # e.g. "ollama:nomic-embed-text"
      provider = "ollama"              # legacy split form
      model_name = "nomic-embed-text"  # legacy split form

    Falls back to ollama:nomic-embed-text if nothing configured.
    """
    from sarthak.core.ai_utils.multi_provider import (
        ENV_KEYS,
        ConfigurationError,
        Provider,
        ProviderConfig,
    )
    from sarthak.core.config import load_config

    cfg = load_config()
    emb_cfg = cfg.get("ai", {}).get("embeddings", {})

    model_str  = (emb_cfg.get("model") or "").strip()
    provider   = (emb_cfg.get("provider") or "").strip().lower()
    model_name = (emb_cfg.get("model_name") or "").strip()

    # Build canonical "provider:model" string
    if model_str:
        if ":" not in model_str:
            if provider:
                model_str = f"{provider}:{model_str}"
            else:
                raise ConfigurationError(
                    "Set ai.embeddings.model = 'provider:model' in config.toml. "
                    "Example: 'ollama:nomic-embed-text' or 'openai:text-embedding-3-small'"
                )
        provider = model_str.split(":", 1)[0].strip().lower()
    elif provider and model_name:
        model_str = f"{provider}:{model_name}"
    else:
        # Default: ollama nomic-embed-text (free, local, 768-dim)
        log.info("rag_embedder_default", model="ollama:nomic-embed-text")
        return _OllamaEmbedder("nomic-embed-text")

    log.info("rag_embedder", model=model_str)

    if provider == "ollama":
        return _OllamaEmbedder(model_str.split(":", 1)[1])

    try:
        p = Provider.from_str(provider)
    except ValueError as exc:
        raise ConfigurationError(str(exc)) from exc

    pc = ProviderConfig(p, cfg)
    env_key = ENV_KEYS.get(p)
    if env_key and pc.api_key and not os.environ.get(env_key):
        os.environ[env_key] = pc.api_key
    if env_key and not pc.is_configured():
        raise ConfigurationError(
            f"{p.value} API key not configured. Set [ai.{p.value}] api_key in config.toml "
            f"or export {env_key}."
        )

    from pydantic_ai.models import EmbeddingModel
    return EmbeddingModel(model_str)


class _OllamaEmbedResult:
    def __init__(self, embeddings: list[list[float]]):
        self.embeddings = embeddings


class _OllamaEmbedder:
    """Minimal Ollama embeddings client — no pydantic-ai dependency."""

    def __init__(self, model: str, base_url: str = ""):
        self.model = model
        try:
            from sarthak.core.config import load_config
            cfg = load_config()
            self.base_url = (
                base_url
                or cfg.get("ai", {}).get("ollama", {}).get("base_url", "")
                or "http://localhost:11434"
            ).rstrip("/")
        except Exception:
            self.base_url = base_url or "http://localhost:11434"

    async def _embed(self, texts: list[str]) -> list[list[float]]:
        import httpx
        async with httpx.AsyncClient(timeout=120.0) as client:
            if self.base_url.endswith("/v1"):
                resp = await client.post(
                    f"{self.base_url}/embeddings",
                    json={"model": self.model, "input": texts},
                )
                resp.raise_for_status()
                return [row["embedding"] for row in resp.json().get("data", [])]
            resp = await client.post(
                f"{self.base_url}/api/embed",
                json={"model": self.model, "input": texts},
            )
            resp.raise_for_status()
            return resp.json()["embeddings"]

    async def embed_documents(self, texts: list[str]) -> _OllamaEmbedResult:
        return _OllamaEmbedResult(await self._embed(texts))

    async def embed_query(self, query: str) -> _OllamaEmbedResult:
        return _OllamaEmbedResult(await self._embed([query]))


# ── sqlite-vec DB ──────────────────────────────────────────────────────────────

def _open_db(directory: Path):
    import sqlite3
    import sqlite_vec

    db = sqlite3.connect(str(_db_path(directory)), check_same_thread=False)
    db.enable_load_extension(True)
    sqlite_vec.load(db)
    db.enable_load_extension(False)
    db.executescript(_SCHEMA)
    db.commit()
    return db


def _ensure_vec_table(db, dim: int) -> None:
    existing = db.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name='vec_chunks'"
    ).fetchone()
    if not existing:
        db.execute(
            f"CREATE VIRTUAL TABLE vec_chunks USING vec0(id TEXT PRIMARY KEY, embedding float[{dim}])"
        )
        db.commit()


def _upsert_chunks(db, chunks: list[dict], embeddings: list[list[float]]) -> None:
    """Insert/replace chunks into both relational and vector tables, sync FTS5."""
    for chunk, emb in zip(chunks, embeddings):
        db.execute(
            "INSERT OR REPLACE INTO chunks(id, source, chunk, line, text) VALUES(?,?,?,?,?)",
            (chunk["id"], chunk["source"], chunk["chunk"], chunk["line"], chunk["text"]),
        )
        db.execute(
            "INSERT OR REPLACE INTO vec_chunks(id, embedding) VALUES(?,?)",
            (chunk["id"], _encode(emb)),
        )
    # Rebuild FTS5 index for the rows we just wrote
    db.execute("INSERT INTO chunks_fts(chunks_fts) VALUES('rebuild')")
    db.commit()


# ── Hybrid search (vector + FTS5 RRF) ─────────────────────────────────────────

def _fts5_search(db, query: str, top_k: int) -> list[tuple[str, float]]:
    """BM25 full-text search via FTS5. Returns [(id, rank)] sorted best-first."""
    try:
        # fts5 rank is negative BM25 (lower = better match); negate for RRF
        rows = db.execute(
            "SELECT id, rank FROM chunks_fts WHERE text MATCH ? ORDER BY rank LIMIT ?",
            (query, top_k * 2),
        ).fetchall()
        return [(row[0], -row[1]) for row in rows]  # positive = better
    except Exception:
        return []


def _reciprocal_rank_fusion(
    vec_hits: list[str],
    fts_hits: list[tuple[str, float]],
    k: int = 60,
) -> list[str]:
    """Merge vector and FTS5 result lists via Reciprocal Rank Fusion."""
    scores: dict[str, float] = {}
    for rank, chunk_id in enumerate(vec_hits):
        scores[chunk_id] = scores.get(chunk_id, 0.0) + 1.0 / (k + rank + 1)
    for rank, (chunk_id, _) in enumerate(fts_hits):
        scores[chunk_id] = scores.get(chunk_id, 0.0) + 1.0 / (k + rank + 1)
    return sorted(scores, key=lambda x: scores[x], reverse=True)


# ── Public API ─────────────────────────────────────────────────────────────────

async def index_space(directory: Path, incremental: bool = True) -> int:
    """Index all files in directory. Returns number of chunks upserted."""
    directory = Path(directory)
    stored_mtimes = _load_mtimes(directory) if incremental else {}
    new_mtimes = dict(stored_mtimes)
    all_chunks: list[dict[str, Any]] = []

    for path, text in _iter_files(directory):
        rel = str(path.relative_to(directory))
        mtime = path.stat().st_mtime
        if incremental and stored_mtimes.get(rel) == mtime:
            continue
        all_chunks.extend(_chunk(text, rel))
        new_mtimes[rel] = mtime

    if not all_chunks:
        log.debug("rag_index_no_changes", directory=str(directory))
        return 0

    embedder = _get_embedder()
    result = await embedder.embed_documents([c["text"] for c in all_chunks])
    embeddings = result.embeddings
    dim = len(embeddings[0])

    db = _open_db(directory)
    _ensure_vec_table(db, dim)
    _upsert_chunks(db, all_chunks, embeddings)
    db.close()

    _save_mtimes(directory, new_mtimes)
    log.info("rag_indexed", directory=str(directory), chunks=len(all_chunks))
    return len(all_chunks)


async def index_paths(directory: Path, rel_paths: list[str], pipeline: str = "text") -> int:
    """Index only the specified relative paths. Returns chunks upserted."""
    directory = Path(directory)
    stored_mtimes = _load_mtimes(directory)
    new_mtimes = dict(stored_mtimes)
    all_chunks: list[dict[str, Any]] = []

    for rel in rel_paths:
        p = (directory / rel).resolve()
        if not str(p).startswith(str(directory.resolve())):
            continue
        if not p.is_file() or p.suffix.lower() not in _ALL_EXTS:
            continue
        if p.stat().st_size > _MAX_FILE_KB * 1024:
            continue
        text = _extract_text(p, pipeline=pipeline)
        if text:
            all_chunks.extend(_chunk(text, rel))
            new_mtimes[rel] = p.stat().st_mtime

    if not all_chunks:
        return 0

    embedder = _get_embedder()
    result = await embedder.embed_documents([c["text"] for c in all_chunks])
    embeddings = result.embeddings
    dim = len(embeddings[0])

    db = _open_db(directory)
    _ensure_vec_table(db, dim)
    _upsert_chunks(db, all_chunks, embeddings)
    db.close()

    _save_mtimes(directory, new_mtimes)
    log.info("rag_index_paths", directory=str(directory), paths=len(rel_paths), chunks=len(all_chunks))
    return len(all_chunks)


async def index_paths_streaming(
    directory: Path, rel_paths: list[str], pipeline: str = "text"
) -> AsyncGenerator[str, None]:
    """Like index_paths but yields SSE JSON events per file + final done event."""
    directory = Path(directory)
    stored_mtimes = _load_mtimes(directory)
    new_mtimes = dict(stored_mtimes)
    total = len(rel_paths)
    all_chunks: list[dict[str, Any]] = []

    for idx, rel in enumerate(rel_paths):
        p = (directory / rel).resolve()
        if not str(p).startswith(str(directory.resolve())):
            continue
        if not p.is_file() or p.suffix.lower() not in _ALL_EXTS:
            continue
        if p.stat().st_size > _MAX_FILE_KB * 1024:
            continue
        text = _extract_text(p, pipeline=pipeline)
        file_chunks = []
        if text:
            file_chunks = _chunk(text, rel)
            new_mtimes[rel] = p.stat().st_mtime
        all_chunks.extend(file_chunks)
        yield f"data: {json.dumps({'done': False, 'file': rel, 'file_index': idx + 1, 'total_files': total, 'chunks_so_far': len(all_chunks)})}\n\n"

    if not all_chunks:
        yield f"data: {json.dumps({'done': True, 'chunks_indexed': 0, 'indexed_files': len(_load_mtimes(directory)), 'indexed_chunks': 0})}\n\n"
        return

    embedder = _get_embedder()
    result = await embedder.embed_documents([c["text"] for c in all_chunks])
    embeddings = result.embeddings
    dim = len(embeddings[0])

    db = _open_db(directory)
    _ensure_vec_table(db, dim)
    _upsert_chunks(db, all_chunks, embeddings)
    db.close()
    _save_mtimes(directory, new_mtimes)

    st = rag_status(directory)
    yield f"data: {json.dumps({'done': True, 'chunks_indexed': len(all_chunks), 'indexed_files': st.get('indexed_files', 0), 'indexed_chunks': st.get('indexed_chunks', 0)})}\n\n"


class SearchResult:
    """Structured RAG search result."""
    __slots__ = ("source", "line", "chunk", "text", "distance")

    def __init__(self, source: str, line: int, chunk: int, text: str, distance: float) -> None:
        self.source   = source
        self.line     = line
        self.chunk    = chunk
        self.text     = text
        self.distance = distance

    def to_dict(self) -> dict:
        return {
            "source":  self.source,
            "line":    self.line,
            "chunk":   self.chunk,
            "text":    self.text,
            "score":   round(1 - self.distance, 4),
        }


async def _vec_search(directory: Path, query: str, top_k: int) -> list[SearchResult]:
    """
    Hybrid search: vector cosine + FTS5 BM25 merged via Reciprocal Rank Fusion.
    Falls back to vector-only if FTS5 returns nothing.
    """
    db_file = _db_path(directory)
    if not db_file.exists():
        # Check legacy location
        legacy = _legacy_db_path(directory)
        if not legacy.exists():
            return []

    embedder = _get_embedder()
    q_result = await embedder.embed_query(query)
    q_vec = q_result.embeddings[0]

    db = _open_db(directory)
    try:
        # Vector search — get top_k * 2 candidates for RRF
        vec_rows = db.execute(
            """
            SELECT c.id, c.source, c.line, c.chunk, c.text, v.distance
            FROM   vec_chunks v
            JOIN   chunks c ON c.id = v.id
            ORDER  BY vec_distance_cosine(embedding, ?)
            LIMIT  ?
            """,
            (_encode(q_vec), top_k * 2),
        ).fetchall()

        vec_ids = [r[0] for r in vec_rows]
        vec_meta = {r[0]: r for r in vec_rows}

        # FTS5 keyword search
        fts_hits = _fts5_search(db, query, top_k)

        # Merge via RRF
        merged_ids = _reciprocal_rank_fusion(vec_ids, fts_hits)[:top_k]

        # Fetch rows not already in vec_meta (FTS-only hits)
        fts_only_ids = [cid for cid in merged_ids if cid not in vec_meta]
        if fts_only_ids:
            placeholders = ",".join("?" * len(fts_only_ids))
            extra = db.execute(
                f"SELECT id, source, line, chunk, text, 0.5 FROM chunks WHERE id IN ({placeholders})",
                fts_only_ids,
            ).fetchall()
            for row in extra:
                vec_meta[row[0]] = row

        return [
            SearchResult(
                source=vec_meta[cid][1],
                line=vec_meta[cid][2],
                chunk=vec_meta[cid][3],
                text=vec_meta[cid][4],
                distance=vec_meta[cid][5],
            )
            for cid in merged_ids
            if cid in vec_meta
        ]
    finally:
        db.close()


async def search_space(directory: Path, query: str, top_k: int = _TOP_K) -> str:
    """Search the RAG index. Returns Markdown with [file:line] refs, or an error string."""
    directory = Path(directory)
    if not _db_path(directory).exists():
        return "Space not indexed yet. Run: sarthak spaces rag index"
    results = await _vec_search(directory, query, top_k)
    if not results:
        return "No relevant content found."
    parts = [
        f"[{r.source}:{r.line}]\n{r.text.strip()}" if r.line else f"[{r.source}]\n{r.text.strip()}"
        for r in results
    ]
    return "\n\n---\n\n".join(parts)


async def search_space_structured(
    directory: Path, query: str, top_k: int = _TOP_K
) -> list[SearchResult]:
    """Search the RAG index. Returns structured SearchResult list."""
    return await _vec_search(Path(directory), query, top_k)


def list_indexed_files(directory: Path) -> list[str]:
    """Return sorted list of relative paths recorded in mtimes.json."""
    return sorted(_load_mtimes(Path(directory)).keys())


def walk_space(directory: Path) -> list[dict[str, Any]]:
    """Return metadata for every indexable file (without extracting text)."""
    directory = Path(directory)
    indexed_set = set(_load_mtimes(directory).keys())
    results: list[dict[str, Any]] = []
    for p in directory.rglob("*"):
        if _is_indexable(p, directory):
            rel = str(p.relative_to(directory))
            results.append({
                "path":    rel,
                "size":    p.stat().st_size,
                "indexed": rel in indexed_set,
            })
    return sorted(results, key=lambda f: f["path"])


async def export_activities_to_markdown(directory: Path) -> list[str]:
    """Export notes/transcripts from activity store to .spaces/activity_exports/ for RAG."""
    directory = Path(directory)
    export_dir = directory / ".spaces" / "activity_exports"
    export_dir.mkdir(parents=True, exist_ok=True)

    try:
        from sarthak.storage.activity_store import query_activity
        items = await query_activity(space_dir=str(directory), days=365, limit=2000)
    except Exception as exc:
        log.warning("activity_export_failed", error=str(exc))
        return []

    written: list[str] = []
    for item in items:
        content = (item.get("content_text") or "").strip()
        if not content:
            continue
        atype   = item.get("activity_type", "activity")
        concept = (item.get("concept_title") or "unknown").replace("/", "_")
        ts      = (item.get("created_at") or "")[:19].replace(":", "-").replace(" ", "_")
        out_path = export_dir / concept / f"{atype}_{ts}.md"
        out_path.parent.mkdir(parents=True, exist_ok=True)
        md = f"# {atype}: {concept}\n\n*{ts}*\n\n{content}\n"
        if not out_path.exists() or out_path.read_text(encoding="utf-8") != md:
            out_path.write_text(md, encoding="utf-8")
            written.append(str(out_path.relative_to(directory)))

    log.info("activity_export", directory=str(directory), written=len(written))
    return written


async def chat_with_file(
    file_path: Path,
    question: str,
    history: list[dict[str, str]] | None = None,
    *,
    max_context_chars: int = 12_000,
) -> str:
    """Answer a question grounded in a single file's content."""
    text = _extract_text(file_path)
    if not text:
        return f"Could not extract text from {file_path.name}."

    context = text[:max_context_chars]
    if len(text) > max_context_chars:
        context += f"\n\n… (truncated — showing first {max_context_chars:,} of {len(text):,} chars)"

    system = (
        "You are a helpful assistant. Answer ONLY based on the file content below. "
        "Say so clearly if the answer is not in the file.\n\n"
        f"=== FILE: {file_path.name} ===\n{context}\n=== END FILE ==="
    )
    history_text = "".join(
        f"\n\n{'User' if t['role'] == 'user' else 'Assistant'}: {t['content']}"
        for t in (history or [])
    )
    from sarthak.core.ai_utils.multi_provider import call_llm
    return await call_llm(system + history_text + f"\n\nUser: {question}")


def rag_tool_for(directory: Path):
    """Return an async callable for injection as a pydantic-ai tool."""
    ws_dir = Path(directory)

    async def search_workspace(query: str) -> str:
        """Search the workspace files for relevant content."""
        return await search_space(ws_dir, query)

    return search_workspace


def rag_status(directory: Path) -> dict[str, Any]:
    """Return status dict for the RAG index."""
    directory = Path(directory)
    db_file = _db_path(directory)
    if not db_file.exists():
        legacy = _legacy_db_path(directory)
        if legacy.exists():
            db_file = legacy
    if not db_file.exists():
        return {
            "enabled":        False,
            "indexed_chunks": 0,
            "indexed_files":  0,
            "db_path":        str(db_file),
            "db_size_kb":     0,
        }
    db = _open_db(directory)
    n        = db.execute("SELECT COUNT(*) FROM chunks").fetchone()[0]
    distinct = db.execute("SELECT COUNT(DISTINCT source) FROM chunks").fetchone()[0]
    db.close()
    mtimes = _load_mtimes(directory)
    return {
        "enabled":        True,
        "indexed_chunks": n,
        "indexed_files":  len(mtimes) or distinct,
        "db_path":        str(db_file),
        "db_size_kb":     db_file.stat().st_size // 1024,
    }


# ── Watchdog auto-indexer ──────────────────────────────────────────────────────

def start_watcher(directory: Path):
    """Watch directory for changes and auto-reindex incrementally."""
    try:
        from watchdog.events import FileSystemEventHandler
        from watchdog.observers import Observer
    except ImportError:
        log.warning("rag_watcher_unavailable", hint="pip install watchdog")
        return None

    directory = Path(directory)
    _last_seen: dict[str, float] = {}
    _lock = threading.Lock()

    def _reindex(rel: str) -> None:
        time.sleep(_DEBOUNCE_S)
        with _lock:
            if time.monotonic() - _last_seen.get(rel, 0) < _DEBOUNCE_S:
                return
        try:
            # Use a fresh loop to avoid RuntimeError when called from a thread
            # that shares a process with a running event loop (e.g. uvicorn).
            loop = asyncio.new_event_loop()
            try:
                n = loop.run_until_complete(index_space(directory, incremental=True))
            finally:
                loop.close()
            log.info("rag_auto_reindexed", file=rel, chunks=n)
        except Exception as exc:
            log.warning("rag_auto_reindex_failed", file=rel, error=str(exc))

    class _Handler(FileSystemEventHandler):
        def on_modified(self, event) -> None:
            self._handle(event)

        def on_created(self, event) -> None:
            self._handle(event)

        def _handle(self, event) -> None:
            if event.is_directory:
                return
            path = Path(event.src_path)
            parts = path.parts[len(directory.parts):]
            if any(p in _SKIP_DIRS for p in parts):
                return
            if path.suffix.lower() not in _ALL_EXTS:
                return
            rel = str(path.relative_to(directory))
            with _lock:
                _last_seen[rel] = time.monotonic()
            threading.Thread(target=_reindex, args=(rel,), daemon=True).start()

    observer = Observer()
    observer.schedule(_Handler(), str(directory), recursive=True)
    observer.start()
    log.info("rag_watcher_started", directory=str(directory))
    return observer


def stop_watcher(observer) -> None:
    if observer is None:
        return
    try:
        observer.stop()
        observer.join(timeout=5)
        log.info("rag_watcher_stopped")
    except Exception as exc:
        log.warning("rag_watcher_stop_failed", error=str(exc))
