"""
Sarthak AI — Orchestrator.

All questions are routed directly to the orchestrator agent.
No regex-based rule matching — deterministic button actions are handled
in the channel layer (bot.py) by calling tools directly.

Public API
----------
  route(question, pool, ...) → OrchestratorResult
  ask = route  (backward-compat alias)
"""
from __future__ import annotations

from sarthak.core.logging import get_logger
from sarthak.features.ai.deps import OrchestratorResult

log = get_logger(__name__)


async def route(
    question: str,
    pool: object | None = None,
    allow_web: bool = True,
    allow_shell: bool = True,
    cwd: str = "",
    provider: str | None = None,
    model_name: str | None = None,
    force_agent: bool = False,
    message_history: list | None = None,
) -> OrchestratorResult:
    """
    Route a question to the orchestrator agent.

    Deterministic analytics/system actions are called directly in the channel
    layer (Telegram bot.py _RUN_HANDLERS) — they never reach this function.
    All free-text input goes straight to the agent with full cross-channel
    conversation history injected as context.
    """
    log.info("agent_dispatch", question=question[:60])
    from sarthak.features.ai.agent import ask_orchestrator
    return await ask_orchestrator(
        question,
        pool=pool,
        allow_web=allow_web,
        allow_shell=allow_shell,
        cwd=cwd,
        provider=provider,
        model_name=model_name,
        message_history=message_history or [],
    )


# Backward-compat alias
ask = route
