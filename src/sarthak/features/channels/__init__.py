"""
Sarthak AI — Channel base.

Single source of truth for building the orchestrator agent and its deps.
All channels (Telegram, TUI, Web) MUST use these functions — no duplicated
routing logic anywhere.

Public API
----------
  make_orchestrator_agent_and_deps(pool, cwd, provider, model_name)
      → (Agent, OrchestratorDeps)

  dispatch(question, pool, ...)
      → OrchestratorResult
      Non-streaming. Used by Telegram and the orchestrator rule-router.

  stream_dispatch(question, pool, ...)
      → AsyncIterator[str]
      Streams the reply field of OrchestratorResult token by token using
      pydantic-ai streaming structured output (stream_output()).
      Used by TUI chat and Web chat for live rendering.

  save_chat_turn(pool, session_id, question, reply)
      Persists one user+assistant turn to chat_history (shared DB table).
      All channels call this after every successful response so history is
      cross-channel: a conversation started in TUI continues in Telegram
      or the Web UI within the same session_id.

  load_history_messages(pool, session_id, limit)
      Returns pydantic-ai ModelMessage list ready to pass into agent.run*()
      so the agent sees full conversation context no matter which channel
      originated the earlier turns.
"""
from __future__ import annotations

import uuid
from collections.abc import AsyncIterator
from pathlib import Path

from sarthak.features.ai.deps import OrchestratorDeps, OrchestratorResult


# ── Agent factory ─────────────────────────────────────────────────────────────

def make_orchestrator_agent_and_deps(
    pool: object | None = None,
    cwd: str = "",
    provider: str | None = None,
    model_name: str | None = None,
    allow_web: bool = True,
    allow_shell: bool = True,
) -> tuple:
    """
    Build the orchestrator agent and its runtime deps.

    This is the single canonical factory used by ALL channels:
      - Telegram bot  (bot.py  → _dispatch → dispatch → here)
      - TUI chat      (chat.py → stream_dispatch        → here)
      - Web AG-UI     (app.py  → _stream_chat           → here)
    """
    from sarthak.features.ai.agents import get_agent
    from sarthak.features.ai.agents._base import resolve_provider_model

    resolved_provider, resolved_model = resolve_provider_model(provider, model_name)
    agent = get_agent("orchestrator", provider=resolved_provider, model_name=resolved_model)
    deps = OrchestratorDeps(
        pool=pool,
        cwd=cwd or str(Path.home()),
        allow_web=allow_web,
        allow_shell=allow_shell,
    )
    return agent, deps


# ── Shared DB helpers ─────────────────────────────────────────────────────────

def new_session_id() -> str:
    """Generate a fresh chat session UUID."""
    return str(uuid.uuid4())


async def save_chat_turn(
    session_id: str,
    question: str,
    reply: str,
    pool: object = None,  # kept for call-site compat; ignored
) -> None:
    """
    Persist one user+assistant turn to the shared SQLite chat_history table.

    ALL channels (Telegram, TUI, Web) must call this after every successful
    LLM response so that the conversation log is unified and cross-channel.
    """
    if not session_id:
        return
    from sarthak.storage.helpers import write_chat_message
    await write_chat_message(session_id, "user", question)
    await write_chat_message(session_id, "assistant", reply)


async def load_history_messages(
    session_id: str,
    limit: int = 40,
    pool: object = None,  # kept for call-site compat; ignored
) -> list:
    """
    Load recent chat history from SQLite and convert to pydantic-ai
    ModelMessage objects for context injection.
    """
    if not session_id:
        return []
    try:
        from pydantic_ai.messages import ModelRequest, ModelResponse, UserPromptPart, TextPart
        from sarthak.storage.helpers import get_chat_history
        rows = await get_chat_history(session_id, limit=limit)
        messages: list = []
        for row in rows:
            role = row.get("role", "")
            content = row.get("content", "")
            if role == "user":
                messages.append(ModelRequest(parts=[UserPromptPart(content=content)]))
            elif role == "assistant":
                messages.append(ModelResponse(parts=[TextPart(content=content)]))
        return messages
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
) -> OrchestratorResult:
    """
    Non-streaming dispatch. Used by Telegram bot.

    Loads conversation history from DB when session_id is provided (and
    message_history is not already supplied), then injects it as context so
    the agent sees the full cross-channel conversation.
    """
    history = message_history
    if history is None:
        history = await load_history_messages(session_id) if session_id else []
    from sarthak.orchestrator.orchestrator import route
    return await route(
        question,
        pool=pool,
        allow_web=allow_web,
        allow_shell=allow_shell,
        cwd=cwd,
        provider=provider,
        model_name=model_name,
        force_agent=force_agent,
        message_history=history,
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
    Streaming structured output dispatch.

    Yields the `reply` field of OrchestratorResult as it builds up, token by
    token, using pydantic-ai's stream_output() over the structured output.

    If session_id is provided and message_history is not, history is loaded
    from the shared DB table so context is consistent across channels.

    Yields each partial OrchestratorResult.reply string (cumulative, not delta).
    The final yield is the complete reply.
    """
    history = message_history
    if history is None:
        history = await load_history_messages(session_id) if session_id else []
    agent, deps = make_orchestrator_agent_and_deps(
        pool=pool, cwd=cwd, provider=provider, model_name=model_name,
        allow_web=allow_web, allow_shell=allow_shell,
    )
    async with agent.run_stream(question, deps=deps, message_history=history) as stream:
        async for partial in stream.stream_output(debounce_by=0.05):
            reply = partial.reply if partial.reply else ""
            if reply:
                yield reply
