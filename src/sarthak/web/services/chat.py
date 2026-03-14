from __future__ import annotations

import asyncio
import json
from collections.abc import AsyncIterator
from uuid import uuid4

from pydantic_ai.messages import FunctionToolCallEvent, FunctionToolResultEvent

from sarthak.core.logging import get_logger
from sarthak.features.channels import (
    load_history_messages,
    make_orchestrator_agent_and_deps,
    save_chat_turn,
)
from sarthak.storage.db import connect
from sarthak.storage.repositories.chat import default as chat_repo

log = get_logger(__name__)


async def stream_chat_sse(
    message: str,
    session_id: str | None,
    history: list[dict[str, str]] | None = None,
) -> AsyncIterator[str]:
    sid = session_id or str(uuid4())
    message_history = history
    if message_history is None:
        message_history = await load_history_messages(sid)

    agent, deps = make_orchestrator_agent_and_deps()
    full_reply = ""
    queue: asyncio.Queue[str | None] = asyncio.Queue()

    async def event_handler(_ctx, event_stream):
        async for event in event_stream:
            if isinstance(event, FunctionToolCallEvent):
                payload = {"type": "tool_start", "tool": event.part.tool_name}
                await queue.put(json.dumps(payload))
            elif isinstance(event, FunctionToolResultEvent):
                payload = {"type": "tool_done", "tool": event.result.tool_name}
                await queue.put(json.dumps(payload))

    async def run_agent() -> None:
        nonlocal full_reply
        try:
            async with agent.run_stream(
                message,
                deps=deps,
                message_history=message_history,
                event_stream_handler=event_handler,
            ) as stream:
                async for partial in stream.stream_output(debounce_by=0.05):
                    reply = partial.reply or ""
                    if reply:
                        full_reply = reply
                        await queue.put(json.dumps({"type": "text", "text": reply}))
        except Exception as exc:
            log.error("chat_stream_failed", error=str(exc))
            await queue.put(json.dumps({"type": "error", "text": str(exc)}))
        finally:
            await queue.put(None)

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


async def get_chat_history(session_id: str, limit: int = 40) -> dict:
    rows = await chat_repo.get_history(session_id, limit=limit)
    return {
        "session_id": session_id,
        "messages": [
            {"role": row["role"], "content": row["content"], "ts": row.get("ts")}
            for row in rows
        ],
    }


async def list_chat_sessions(limit: int = 20) -> dict:
    sessions = await chat_repo.get_sessions(limit=limit)
    return {
        "sessions": [
            {
                "session_id": session["session_id"],
                "last_ts": session.get("last_ts"),
                "msg_count": session.get("msg_count", 0),
            }
            for session in sessions
        ]
    }


async def delete_chat_session(session_id: str) -> None:
    async with connect() as db:
        await db.execute("DELETE FROM chat_history WHERE session_id=?", (session_id,))
        await db.commit()


async def ag_ui_dispatch(request_body: dict, request) -> object:
    from pydantic_ai.ui.ag_ui import AGUIAdapter

    thread_id = request_body.get("thread_id") or request_body.get("threadId")
    history = await load_history_messages(thread_id) if thread_id else []
    agent, deps = make_orchestrator_agent_and_deps()
    return await AGUIAdapter.dispatch_request(
        request,
        agent=agent,
        deps=deps,
        message_history=history if history else None,
    )
