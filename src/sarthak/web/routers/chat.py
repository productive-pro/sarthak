from __future__ import annotations

from typing import AsyncIterator

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

router = APIRouter()


class ChatReq(BaseModel):
    message: str
    session_id: str | None = None
    history: list[dict[str, str]] = []


async def _stream_chat(
    message: str,
    session_id: str | None,
    history: list[dict[str, str]] | None = None,
) -> AsyncIterator[str]:
    import uuid

    from sarthak.features.channels import (
        load_history_messages,
        save_chat_turn,
        stream_dispatch,
    )

    sid = session_id or str(uuid.uuid4())

    # Use pre-loaded history from request body if provided, else fetch from DB
    if history is None:
        history = await load_history_messages(sid)
    full_reply = ""
    try:
        async for partial_reply in stream_dispatch(
            message, session_id=sid, message_history=history
        ):
            full_reply = partial_reply
            yield f"data: {partial_reply}\n\n"
    except Exception as exc:
        yield f"data: [Error: {exc}]\n\n"

    if full_reply:
        try:
            await save_chat_turn(sid, message, full_reply)
        except Exception:
            pass

    yield f"data: [SESSION:{sid}]\n\n"
    yield "data: [DONE]\n\n"


@router.post("/api/chat")
async def chat(req: ChatReq):
    return StreamingResponse(
        _stream_chat(req.message, req.session_id, history=req.history or None),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@router.get("/api/chat/session")
async def get_chat_session():
    import uuid

    from sarthak.storage.helpers import get_latest_chat_session_id

    try:
        sid = await get_latest_chat_session_id()
        return {"session_id": sid or str(uuid.uuid4())}
    except Exception:
        return {"session_id": str(uuid.uuid4())}


@router.get("/api/chat/history")
async def get_chat_history_api(session_id: str, limit: int = 40):
    from sarthak.storage.helpers import get_chat_history

    try:
        rows = await get_chat_history(session_id, limit=limit)
        return {
            "session_id": session_id,
            "messages": [
                {"role": r["role"], "content": r["content"], "ts": r.get("ts")}
                for r in rows
            ],
        }
    except Exception as exc:
        raise HTTPException(500, str(exc))


@router.delete("/api/chat/sessions/{session_id}")
async def delete_chat_session(session_id: str) -> dict:
    from sarthak.storage.helpers import delete_chat_session
    try:
        await delete_chat_session(session_id)
        return {"ok": True}
    except Exception as exc:
        raise HTTPException(500, str(exc))


@router.get("/api/chat/sessions")
async def list_chat_sessions(limit: int = 20):
    from sarthak.storage.helpers import get_chat_sessions

    try:
        sessions = await get_chat_sessions(limit=limit)
        return {
            "sessions": [
                {
                    "session_id": s["session_id"],
                    "last_ts": s.get("last_ts"),
                    "msg_count": s.get("msg_count", 0),
                }
                for s in sessions
            ]
        }
    except Exception as exc:
        raise HTTPException(500, str(exc))


@router.post("/api/ag-ui")
async def ag_ui_endpoint(request: Request):
    from pydantic_ai.ui.ag_ui import AGUIAdapter

    from sarthak.features.channels import make_orchestrator_agent_and_deps

    agent, deps = make_orchestrator_agent_and_deps()
    return await AGUIAdapter.dispatch_request(request, agent=agent, deps=deps)
