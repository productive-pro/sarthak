"""
Sarthak AI — LLM Call Logger.

Single entry point: log_llm_call(agent, system, prompt, response)
  • Emits structured log lines via structlog (agent_prompt / agent_response events).
  • Writes a human-readable Markdown file to ~/.sarthak_ai/prompt_history/ for debugging.

Called automatically from run_llm() in features/ai/agents/_base.py — no per-agent wiring needed.
"""
from __future__ import annotations

import os
from datetime import datetime, timezone

from sarthak.core.logging import get_logger

log = get_logger(__name__)

HISTORY_DIR = os.path.expanduser("~/.sarthak_ai/prompt_history")


def log_llm_call(
    agent: str,
    system: str,
    prompt: str,
    response: str,
) -> None:
    """Log one complete LLM request+response pair.

    Args:
        agent:    Short identifier for the calling agent / context (e.g. 'orchestrator').
        system:   System prompt sent to the LLM.
        prompt:   User/task prompt sent to the LLM.
        response: Raw text returned by the LLM.
    """
    try:
        # ── Structured logs (picked up by any log sink) ───────────────────────
        log.info(
            "agent_prompt",
            agent=agent,
            prompt_len=len(prompt),
            system_len=len(system),
            prompt=prompt,
        )
        log.info(
            "agent_response",
            agent=agent,
            response_len=len(response),
            response=response,
        )

        # ── File log (human-readable markdown) ────────────────────────────────
        os.makedirs(HISTORY_DIR, exist_ok=True)
        ts = datetime.now(tz=timezone.utc)
        filename = f"{ts.strftime('%Y%m%d_%H%M%S_%f')}_{agent}.md"
        filepath = os.path.join(HISTORY_DIR, filename)

        with open(filepath, "w", encoding="utf-8") as f:
            f.write(f"# [{agent}] {ts.isoformat()}\n\n")
            f.write("## System\n\n")
            f.write(system.strip() + "\n\n")
            f.write("## Prompt\n\n")
            f.write(prompt.strip() + "\n\n")
            f.write("## Response\n\n")
            f.write(response.strip() + "\n")

    except Exception as exc:
        log.warning("llm_log_failed", agent=agent, error=str(exc))
