from __future__ import annotations

from fastapi import APIRouter, HTTPException, Query, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from sarthak.web.services import chat as chat_service

router = APIRouter()


class ChatReq(BaseModel):
    message: str = Field(min_length=1, max_length=12000)
    session_id: str | None = None
    history: list[dict[str, str]] = Field(default_factory=list, max_length=100)


@router.post("/api/chat")
async def chat(req: ChatReq):
    return StreamingResponse(
        chat_service.stream_chat_sse(
            req.message,
            req.session_id,
            history=req.history or None,
        ),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@router.get("/api/chat/history")
async def get_chat_history_api(
    session_id: str,
    limit: int = Query(default=40, ge=1, le=200),
):
    try:
        return await chat_service.get_chat_history(session_id, limit=limit)
    except Exception as exc:
        raise HTTPException(500, str(exc))


@router.delete("/api/chat/sessions/{session_id}")
async def delete_chat_session(session_id: str) -> dict:
    try:
        await chat_service.delete_chat_session(session_id)
        return {"ok": True}
    except Exception as exc:
        raise HTTPException(500, str(exc))


@router.get("/api/chat/sessions")
async def list_chat_sessions(limit: int = Query(default=20, ge=1, le=100)):
    try:
        return await chat_service.list_chat_sessions(limit=limit)
    except Exception as exc:
        raise HTTPException(500, str(exc))


@router.post("/api/ag-ui")
async def ag_ui_endpoint(request: Request):
    try:
        body = await request.json()
    except Exception:
        body = {}
    return await chat_service.ag_ui_dispatch(body, request)
