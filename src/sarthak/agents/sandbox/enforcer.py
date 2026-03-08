"""
Sarthak Agent Sandbox — Enforcer.

enforce_sandbox(spec, execute_fn) wraps any async callable with:
  1. SandboxConfig construction
  2. Secret scrubbing on prompt (before execution)
  3. asyncio wall-clock timeout
  4. Secret scrubbing on output (after execution)
  5. Output size cap enforcement
  6. Structured audit events at start and end

This is the single integration point — runner.py calls only this.
"""
from __future__ import annotations

import asyncio
from typing import Awaitable, Callable

import structlog

from sarthak.agents.models import AgentSpec
from sarthak.agents.sandbox.audit import emit
from sarthak.agents.sandbox.config import SandboxConfig, build_sandbox_config
from sarthak.agents.sandbox.secret_scrubber import scrub

log = structlog.get_logger(__name__)


class AgentTimeoutError(TimeoutError):
    """Raised when an agent run exceeds its wall-clock timeout."""


async def enforce_sandbox(
    spec: AgentSpec,
    execute_fn: Callable[[AgentSpec, SandboxConfig], Awaitable[tuple[str, list[str]]]],
) -> tuple[str, list[str]]:
    """
    Wrap execute_fn with full sandbox enforcement.

    Parameters
    ----------
    spec:        The agent being run.
    execute_fn:  Async callable (spec, cfg) -> (output_str, tools_used_list).
                 Must accept a SandboxConfig as its second argument so it can
                 pass it down to PathGuard / ProcessSandbox as needed.

    Returns
    -------
    (scrubbed_output, tools_used)
    """
    cfg = build_sandbox_config(spec)

    # [agents.sandbox.system/space] enabled = false bypasses enforcement (dev only)
    from sarthak.agents.sandbox.config import _load_sandbox_cfg_overrides
    is_space = spec.scope.value == "space"
    overrides = _load_sandbox_cfg_overrides(is_space)
    if str(overrides.get("enabled", "true")).lower() == "false":
        log.warning("sandbox_disabled", agent_id=spec.agent_id, scope=spec.scope.value)
        return await execute_fn(spec, cfg)

    emit(
        "agent_sandbox_start",
        agent_id=cfg.agent_id,
        scope=cfg.scope,
        allow_shell=cfg.allow_shell,
        allow_web=cfg.allow_web,
        allow_file_read=cfg.allow_file_read,
        wall_timeout=cfg.wall_timeout,
        write_roots=[str(r) for r in cfg.write_roots],
        read_roots=[str(r) for r in cfg.read_roots],
    )

    # Scrub secrets from the prompt before any LLM or tool sees them
    clean_prompt, prompt_hits = scrub(spec.prompt, agent_id=cfg.agent_id)
    if prompt_hits:
        # Mutate a local copy — do not persist back to disk
        spec = spec.model_copy(update={"prompt": clean_prompt})

    try:
        output, tools_used = await asyncio.wait_for(
            execute_fn(spec, cfg),
            timeout=cfg.wall_timeout,
        )
    except asyncio.TimeoutError:
        emit(
            "agent_timeout",
            agent_id=cfg.agent_id,
            phase="execute",
            timeout=cfg.wall_timeout,
        )
        raise AgentTimeoutError(
            f"Agent '{cfg.agent_id}' exceeded wall-clock timeout of {cfg.wall_timeout}s."
        )

    # Scrub secrets from the output before it is saved to AgentRun
    output, output_hits = scrub(output, agent_id=cfg.agent_id)

    # Enforce output size cap
    if len(output) > cfg.output_cap:
        emit(
            "agent_output_truncated",
            agent_id=cfg.agent_id,
            original_len=len(output),
            cap=cfg.output_cap,
        )
        output = output[: cfg.output_cap] + "\n[output truncated by sandbox]"

    emit(
        "agent_sandbox_end",
        agent_id=cfg.agent_id,
        output_len=len(output),
        secrets_stripped=output_hits,
        tools_used=tools_used,
    )

    return output, tools_used
