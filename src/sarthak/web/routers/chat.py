from __future__ import annotations

from typing import AsyncIterator

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from sarthak.core.logging import get_logger

router = APIRouter()
log = get_logger(__name__)


class ChatReq(BaseModel):
    message: str
    session_id: str | None = None
    history: list[dict[str, str]] = []


async def _stream_chat(
    message: str,
    session_id: str | None,
    history: list[dict[str, str]] | None = None,
) -> AsyncIterator[str]:
    import asyncio
    import json
    import uuid
    from pydantic_ai.messages import FunctionToolCallEvent, FunctionToolResultEvent
    from sarthak.features.channels import (
        load_history_messages,
        save_chat_turn,
        make_orchestrator_agent_and_deps,
    )

    sid = session_id or str(uuid.uuid4())
    if history is None:
        history = await load_history_messages(sid)

    agent, deps = make_orchestrator_agent_and_deps()
    full_reply = ""

    # Queue bridges the event_stream_handler (called inside run_stream) → our SSE generator
    queue: asyncio.Queue[str | None] = asyncio.Queue()

    async def event_handler(_ctx, event_stream):
        """Intercept tool call events and push SSE frames to the queue."""
        async for event in event_stream:
            if isinstance(event, FunctionToolCallEvent):
                await queue.put(json.dumps({"type": "tool_start", "tool": event.part.tool_name}))
            elif isinstance(event, FunctionToolResultEvent):
                await queue.put(json.dumps({"type": "tool_done", "tool": event.result.tool_name}))

    async def run_agent():
        nonlocal full_reply
        try:
            async with agent.run_stream(
                message, deps=deps, message_history=history, event_stream_handler=event_handler
            ) as stream:
                async for partial in stream.stream_output(debounce_by=0.05):
                    reply = partial.reply if partial.reply else ""
                    if reply:
                        full_reply = reply
                        await queue.put(json.dumps({"type": "text", "text": reply}))
        except Exception as exc:
            log.error("chat_stream_failed", error=str(exc))
            await queue.put(json.dumps({"type": "error", "text": str(exc)}))
        finally:
            await queue.put(None)  # sentinel — stream done

    task = asyncio.create_task(run_agent())

    try:
        while True:
            item = await queue.get()
            if item is None:
                break
            yield f"data: {item}\n\n"
    finally:
        await task

    if full_reply:
        try:
            await save_chat_turn(sid, message, full_reply)
        except Exception:
            log.warning("chat_save_failed", session_id=sid)

    yield f"data: [SESSION:{sid}]\n\n"
    yield "data: [DONE]\n\n"


@router.post("/api/chat")
async def chat(req: ChatReq):
    return StreamingResponse(
        _stream_chat(req.message, req.session_id, history=req.history or None),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


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
    from sarthak.features.channels import (
        make_orchestrator_agent_and_deps,
        load_history_messages,
    )

    # Parse AG-UI request body for thread_id to inject cross-channel history
    try:
        body = await request.json()
    except Exception:
        body = {}

    thread_id = body.get("thread_id") or body.get("threadId")
    history = await load_history_messages(thread_id) if thread_id else []

    agent, deps = make_orchestrator_agent_and_deps()
    return await AGUIAdapter.dispatch_request(
        request, agent=agent, deps=deps,
        message_history=history if history else None,
    )
