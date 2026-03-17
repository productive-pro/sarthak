"""
Web chat service — SSE streaming + session management.

Request flow:
  POST /api/chat → stream_chat_sse()
    → load_history_messages(sid)      [once]
    → stream_orchestrator(…)          [intent-classified, history-compacted]
        ↳ emits tool_start/tool_done events via event_stream_handler
    → save_chat_turn(sid, q, reply)   [after stream]

Tool events (tool_start / tool_done) are emitted as SSE alongside text so
the frontend can show a live "Using tool: X…" indicator.
"""
from __future__ import annotations

import asyncio
import json
from collections.abc import AsyncIterator
from uuid import uuid4

from sarthak.core.logging import get_logger
from sarthak.features.channels import load_history_messages, save_chat_turn
from sarthak.features.ai.agent import (
    _classify_intent, _compact_history, _MAX_HISTORY, _COMPACT_THRESHOLD,
    stream_orchestrator,
)
from sarthak.storage.db import connect
from sarthak.storage.repositories.chat import default as chat_repo

log = get_logger(__name__)


async def stream_chat_sse(
    message: str,
    session_id: str | None,
    history: list[dict[str, str]] | None = None,
) -> AsyncIterator[str]:
    """
    Stream SSE for a chat message.

    Yields JSON-encoded SSE lines:
      {"type":"tool_start","tool":"<n>"}
      {"type":"tool_done", "tool":"<n>"}
      {"type":"text",      "text":"<partial>"}
      {"type":"error",     "text":"<e>"}
      [SESSION:<sid>]
      [DONE]
    """
    sid = session_id or str(uuid4())

    # Resolve history once — never re-loaded inside the agent
    if history is not None:
        from pydantic_ai.messages import ModelRequest, ModelResponse, UserPromptPart, TextPart
        msg_history: list = []
        for h in history[-_MAX_HISTORY:]:
            role, content = h.get("role", ""), h.get("content", "")
            if role == "user":
                msg_history.append(ModelRequest(parts=[UserPromptPart(content=content)]))
            elif role == "assistant":
                msg_history.append(ModelResponse(parts=[TextPart(content=content)]))
    else:
        msg_history = await load_history_messages(sid)

    # Apply compaction here so the SSE path also benefits
    if len(msg_history) > _COMPACT_THRESHOLD:
        msg_history = await _compact_history(msg_history)

    full_reply = ""
    queue: asyncio.Queue[str | None] = asyncio.Queue()

    async def _run() -> None:
        nonlocal full_reply
        try:
            from sarthak.features.ai.agents._base import resolve_provider_model
            from sarthak.features.ai.agents import get_agent
            from sarthak.features.ai.deps import OrchestratorDeps
            from pydantic_ai.messages import FunctionToolCallEvent, FunctionToolResultEvent

            p, m   = resolve_provider_model()
            groups = _classify_intent(message)
            agent  = get_agent("orchestrator", provider=p, model_name=m, tool_groups=groups)
            deps   = OrchestratorDeps(question_hint=message)

            async def _on_event(_ctx, event_stream):
                async for ev in event_stream:
                    if isinstance(ev, FunctionToolCallEvent):
                        await queue.put(json.dumps(
                            {"type": "tool_start", "tool": ev.part.tool_name}
                        ))
                    elif isinstance(ev, FunctionToolResultEvent):
                        await queue.put(json.dumps(
                            {"type": "tool_done", "tool": ev.result.tool_name}
                        ))

            async with agent.run_stream(
                message, deps=deps, message_history=msg_history,
                event_stream_handler=_on_event,
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

    task = asyncio.create_task(_run())
    try:
        while True:
            item = await queue.get()
            if item is None:
                break
            yield f"data: {item}\n\n"
    except GeneratorExit:
        # Client disconnected mid-stream — cancel the background LLM task
        task.cancel()
        raise
    finally:
        # Ensure the task is always cleaned up, whether we finished or were abandoned
        if not task.done():
            task.cancel()
        try:
            await task
        except (asyncio.CancelledError, Exception):
            pass

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
            {"role": r["role"], "content": r["content"], "ts": r.get("ts")}
            for r in rows
        ],
    }


async def list_chat_sessions(limit: int = 20) -> dict:
    sessions = await chat_repo.get_sessions(limit=limit)
    return {
        "sessions": [
            {"session_id": s["session_id"], "last_ts": s.get("last_ts"),
             "msg_count": s.get("msg_count", 0)}
            for s in sessions
        ]
    }


async def delete_chat_session(session_id: str) -> None:
    async with connect() as db:
        await db.execute("DELETE FROM chat_history WHERE session_id=?", (session_id,))
        await db.commit()


async def ag_ui_dispatch(request_body: dict, request) -> object:
    from pydantic_ai.ui.ag_ui import AGUIAdapter
    from sarthak.features.channels import load_history_messages, make_orchestrator_agent_and_deps
    thread_id = request_body.get("thread_id") or request_body.get("threadId")
    history   = await load_history_messages(thread_id) if thread_id else []
    agent, deps = make_orchestrator_agent_and_deps()
    return await AGUIAdapter.dispatch_request(
        request, agent=agent, deps=deps, message_history=history or None,
    )
