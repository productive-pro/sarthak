"""
Sarthak AI — Channel base (single source of truth for all channels).

Request flow (any channel → LLM → response):
  Web/TUI  : stream_dispatch()  → stream_orchestrator() [intent-classified, compacted]
  Telegram : dispatch()         → ask_orchestrator()    [intent-classified, compacted]
  WhatsApp : stream_dispatch()  → stream_orchestrator() [same path]

All channels share the same history storage and session IDs so conversations
started in Telegram continue in the web UI without any re-loading.

Public API:
  dispatch(question, …)                → OrchestratorResult
  stream_dispatch(question, …)         → AsyncIterator[str]
  save_chat_turn(session_id, q, reply) → None
  load_history_messages(session_id)    → list[ModelMessage]
  new_session_id()                     → str
  make_orchestrator_agent_and_deps(…)  → (Agent, OrchestratorDeps)  [legacy compat]
"""
from __future__ import annotations

import uuid
from collections.abc import AsyncIterator

from sarthak.core.logging import get_logger

log = get_logger(__name__)

_MAX_HISTORY = 40  # 20 Q/A pairs × 2 = 40 messages hard cap


def new_session_id() -> str:
    return str(uuid.uuid4())


# ── Shared DB helpers ─────────────────────────────────────────────────────────

async def save_chat_turn(
    session_id: str,
    question: str,
    reply: str,
    pool: object = None,  # kept for call-site compat; ignored
) -> None:
    """Persist one turn to the shared SQLite chat_history. Called by ALL channels."""
    if not session_id:
        return
    from sarthak.storage.helpers import write_chat_message
    await write_chat_message(session_id, "user", question)
    await write_chat_message(session_id, "assistant", reply)


async def load_history_messages(
    session_id: str,
    limit: int = _MAX_HISTORY,
    pool: object = None,  # kept for call-site compat; ignored
) -> list:
    """Load recent chat history as pydantic-ai ModelMessage list."""
    if not session_id:
        return []
    try:
        from pydantic_ai.messages import ModelRequest, ModelResponse, UserPromptPart, TextPart
        from sarthak.storage.helpers import get_chat_history
        rows = await get_chat_history(session_id, limit=limit)
        msgs: list = []
        for row in rows:
            role, content = row.get("role", ""), row.get("content", "")
            if role == "user":
                msgs.append(ModelRequest(parts=[UserPromptPart(content=content)]))
            elif role == "assistant":
                msgs.append(ModelResponse(parts=[TextPart(content=content)]))
        return msgs
    except Exception:
        return []


# ── Non-streaming dispatch ────────────────────────────────────────────────────

async def dispatch(
    question: str,
    pool: object | None = None,
    allow_web: bool = True,
    allow_shell: bool = True,
    cwd: str = "",
    provider: str | None = None,
    model_name: str | None = None,
    force_agent: bool = False,
    session_id: str | None = None,
    message_history: list | None = None,
) -> "OrchestratorResult":
    """Non-streaming dispatch. Used by Telegram, MCP, and CLI."""
    from sarthak.features.ai.agent import ask_orchestrator
    history = message_history
    if history is None and session_id:
        history = await load_history_messages(session_id)
    return await ask_orchestrator(
        question, pool=pool, allow_web=allow_web, allow_shell=allow_shell,
        cwd=cwd, provider=provider, model_name=model_name,
        message_history=history or [],
    )


# ── Streaming dispatch ────────────────────────────────────────────────────────

async def stream_dispatch(
    question: str,
    pool: object | None = None,
    allow_web: bool = True,
    allow_shell: bool = True,
    cwd: str = "",
    provider: str | None = None,
    model_name: str | None = None,
    message_history: list | None = None,
    session_id: str | None = None,
) -> AsyncIterator[str]:
    """
    Streaming dispatch — yields partial OrchestratorResult.reply strings.
    Applies intent classification + history compaction via stream_orchestrator.
    Caller is responsible for save_chat_turn after streaming completes.
    """
    from sarthak.features.ai.agent import stream_orchestrator
    async for chunk in stream_orchestrator(
        question, pool=pool, allow_web=allow_web, allow_shell=allow_shell,
        cwd=cwd, provider=provider, model_name=model_name,
        message_history=message_history, session_id=session_id,
    ):
        yield chunk


# ── Legacy compat shim ────────────────────────────────────────────────────────

def make_orchestrator_agent_and_deps(
    pool: object | None = None,
    cwd: str = "",
    provider: str | None = None,
    model_name: str | None = None,
    allow_web: bool = True,
    allow_shell: bool = True,
):
    """Legacy factory used by AG-UI and old callers. Prefer dispatch/stream_dispatch."""
    from sarthak.features.ai.agents import get_agent
    from sarthak.features.ai.agents._base import resolve_provider_model
    from sarthak.features.ai.deps import OrchestratorDeps
    p, m = resolve_provider_model(provider, model_name)
    agent = get_agent("orchestrator", provider=p, model_name=m)
    deps  = OrchestratorDeps(pool=pool, cwd=cwd, allow_web=allow_web, allow_shell=allow_shell)
    return agent, deps
