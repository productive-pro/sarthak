"""
spaces_rag.py — RAG (document search) endpoints for a Space.

All routes: /api/spaces/{space_id}/rag/*
"""
from __future__ import annotations

import asyncio
from pathlib import Path

from fastapi import APIRouter, File, HTTPException, UploadFile
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from sarthak.web.routers.helpers import SpaceEntry, resolve_space_dir

router = APIRouter()


# ── Legacy fixed-path RAG endpoints (body carries {directory}) ────────────────


class _DirBody(BaseModel):
    directory: str
    reshape: bool = False


@router.post("/api/spaces/rag/index")
async def rag_index_legacy(body: _DirBody) -> dict:
    from sarthak.spaces.rag import index_space
    ws = Path(body.directory).expanduser().resolve()
    count = await index_space(ws)
    return {"chunks_indexed": count, "directory": str(ws)}


@router.get("/api/spaces/rag/status")
async def rag_status_legacy(directory: str) -> dict:
    from sarthak.spaces.rag import rag_status
    return await asyncio.to_thread(rag_status, Path(directory).expanduser().resolve())


class _RagQueryLegacy(BaseModel):
    directory: str
    query: str
    top_k: int = 5


@router.post("/api/spaces/rag/search")
async def rag_search_legacy(body: _RagQueryLegacy) -> dict:
    from sarthak.spaces.rag import search_space_structured
    ws = Path(body.directory).expanduser().resolve()
    results = await search_space_structured(ws, body.query, top_k=body.top_k)
    return {"results": [r.to_dict() for r in results]}


# ── Per-space RAG endpoints (/api/spaces/{space_id}/rag/*) ────────────────────


@router.get("/api/spaces/{space_id}/rag/walk")
async def space_rag_walk(space_id: str) -> dict:
    from sarthak.spaces.rag import rag_status, walk_space
    ws = resolve_space_dir(space_id)
    files = walk_space(ws)
    st = rag_status(ws)
    return {
        "files": files,
        "total_files": len(files),
        "indexed_files": st.get("indexed_files", 0),
        "indexed_chunks": st.get("indexed_chunks", 0),
    }


@router.get("/api/spaces/{space_id}/rag/files")
async def space_rag_files(space_id: str) -> dict:
    from sarthak.spaces.rag import list_indexed_files, rag_status
    ws = resolve_space_dir(space_id)
    st = rag_status(ws)
    return {
        "files": [{"path": p} for p in list_indexed_files(ws)],
        "indexed_files": st.get("indexed_files", 0),
        "indexed_chunks": st.get("indexed_chunks", 0),
    }


class RagIndexPathsReq(BaseModel):
    paths: list[str]
    pipeline: str = "text"


@router.post("/api/spaces/{space_id}/rag/index-paths/stream")
async def space_rag_index_stream(space_id: str, body: RagIndexPathsReq):
    from sarthak.spaces.rag import index_paths_streaming
    ws = resolve_space_dir(space_id)
    return StreamingResponse(
        index_paths_streaming(ws, body.paths, pipeline=body.pipeline),
        media_type="text/event-stream",
    )


@router.post("/api/spaces/{space_id}/rag/export-activities")
async def space_rag_export_activities(space_id: str) -> dict:
    from sarthak.spaces.rag import export_activities_to_markdown
    ws = resolve_space_dir(space_id)
    written = await export_activities_to_markdown(ws)
    return {"written": len(written), "paths": written}


@router.post("/api/spaces/{space_id}/rag/upload")
async def space_rag_upload(
    space_id: str,
    pipeline: str = "text",
    file: UploadFile = File(...),
) -> dict:
    from sarthak.spaces.rag import index_paths, rag_status
    ws = resolve_space_dir(space_id)
    filename = Path(file.filename).name if file.filename else "upload"
    dest = ws / filename
    dest.write_bytes(await file.read())
    count = await index_paths(ws, [filename], pipeline=pipeline)
    st = rag_status(ws)
    return {
        "chunks_indexed": count,
        "indexed_files": st.get("indexed_files", 0),
        "indexed_chunks": st.get("indexed_chunks", 0),
    }


class SpaceRagQuery(BaseModel):
    query: str
    top_k: int = 5


@router.post("/api/spaces/{space_id}/rag/search")
async def space_rag_search(space_id: str, body: SpaceRagQuery) -> dict:
    from sarthak.spaces.rag import search_space_structured
    ws = resolve_space_dir(space_id)
    try:
        results = await search_space_structured(ws, body.query, top_k=body.top_k)
        return {"results": [r.to_dict() for r in results]}
    except Exception as exc:
        msg = str(exc)
        if "not configured" in msg.lower() or "embedding" in msg.lower() or "api key" in msg.lower():
            raise HTTPException(400, f"RAG embeddings not configured: {msg}")
        if "not indexed" in msg.lower():
            raise HTTPException(400, "Space not indexed yet. Use 'Index all files' first.")
        raise HTTPException(500, msg)


@router.get("/api/spaces/{space_id}/rag/status")
async def space_rag_status(space_id: str) -> dict:
    from sarthak.spaces.rag import rag_status
    ws = resolve_space_dir(space_id)
    return await asyncio.to_thread(rag_status, ws)


class RagChatReq(BaseModel):
    question: str
    history: list[dict] = []
    top_k: int = 5


@router.post("/api/spaces/{space_id}/rag/chat")
async def space_rag_chat(space_id: str, body: RagChatReq) -> dict:
    from sarthak.spaces.rag import search_space_structured
    from sarthak.core.ai_utils.multi_provider import call_llm
    ws = resolve_space_dir(space_id)
    try:
        results = await search_space_structured(ws, body.question, top_k=body.top_k)
    except Exception as exc:
        msg = str(exc)
        if "not configured" in msg.lower() or "embedding" in msg.lower() or "api key" in msg.lower():
            raise HTTPException(400, f"RAG embeddings not configured: {msg}")
        raise HTTPException(500, msg)

    context = (
        "\n\n---\n\n".join(f"[{r.source}:{r.line}]\n{r.text.strip()}" for r in results)
        if results
        else "No relevant content found in the indexed workspace files."
    )
    history_text = "".join(
        f"\n\n{'User' if t.get('role') == 'user' else 'Assistant'}: {t.get('content', '')}"
        for t in body.history
    )
    prompt = (
        "You are a knowledgeable assistant. Answer using ONLY the workspace excerpts below. "
        "Cite file:line references when relevant. If the answer is not in the excerpts, say so.\n\n"
        f"=== WORKSPACE CONTEXT ===\n{context}\n=== END CONTEXT ==="
        f"{history_text}\n\nUser: {body.question}\n\nAssistant:"
    )
    answer = await call_llm(prompt)
    sources = [{"source": r.source, "line": r.line, "score": round(1 - r.distance, 3)} for r in results]
    return {"answer": answer, "sources": sources}
