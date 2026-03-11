"""
Shared agent infrastructure: provider resolution, model building, alert helper.

Intentionally thin — heavy logic lives in providers.py and individual agents.
"""
from __future__ import annotations

import asyncio
import os
import time
import re
from typing import Any

from sarthak.core.constants import (
    DEFAULT_MODEL, DEFAULT_PROVIDER,
    SAFE_SHELL_PREFIXES, SHELL_BLOCK_PATTERNS,
    SHELL_TIMEOUT_SECONDS, SHELL_OUTPUT_MAX_CHARS,
)
from sarthak.core.logging import get_logger
from sarthak.features.ai.deps import sanitize_args

log = get_logger(__name__)


# ── Provider / model resolution ───────────────────────────────────────────────

def resolve_provider_model(
    provider: str | None = None, model_name: str | None = None
) -> tuple[str, str]:
    from sarthak.core.config import load_config
    from sarthak.core.ai_utils.multi_provider import normalize_model_name

    cfg = load_config()
    ai = cfg.get("ai", {})
    provider = provider or ai.get("default_provider", DEFAULT_PROVIDER)
    if not model_name:
        pc = ai.get(provider, {})
        model_name = (
            (pc.get("text_model") or pc.get("model") if isinstance(pc, dict) else None)
            or ai.get("default_model", DEFAULT_MODEL)
        )
    return provider, normalize_model_name(provider, model_name)


def build_pydantic_model(provider: str, model_name: str):
    """Build FallbackModel chain (primary → fallback1 → fallback2)."""
    from sarthak.core.ai_utils.multi_provider import build_fallback_model
    return build_fallback_model(provider, model_name)


# ── Logging helper ────────────────────────────────────────────────────────────

def log_tool(name: str, stage: str, agent: str, args: dict | None = None, **kw: Any) -> None:
    payload: dict[str, Any] = {"tool": name, "stage": stage, "agent": agent}
    if args is not None:
        payload["args"] = sanitize_args(args)
    payload.update(kw)
    log.info("tool_call", **payload)


# ── Alert helper ──────────────────────────────────────────────────────────────

async def record_alert(
    pool: object | None, level: str, source: str, message: str, details: dict | None = None
) -> None:
    try:
        from sarthak.storage.helpers import write_alert
        await write_alert(level=level, source=source, message=message, details=details)
    except Exception:
        pass


# ── Shell safety ──────────────────────────────────────────────────────────────

def is_safe_command(command: str) -> bool:
    if not command.strip():
        return False
    if any(p in command for p in SHELL_BLOCK_PATTERNS):
        return False
    return os.path.basename(command.strip().split()[0]) in SAFE_SHELL_PREFIXES


# ── Reusable LLM call ────────────────────────────────────────────────────────

async def run_llm(
    system: str,
    user: str,
    provider: str | None = None,
    model: str | None = None,
    retries: int = 2,
    agent: str = "",
) -> str:
    """One-shot LLM call returning a plain string. Shared by all agents.

    Every call is logged via log_llm_call (structlog + markdown file).
    Pass ``agent`` for a meaningful name in the log; defaults to the caller's
    module name derived at runtime.
    """
    import inspect
    from sarthak.core.ai_utils.multi_provider import call_llm
    from sarthak.core.ai_utils.prompt_logger import log_llm_call

    p, m = resolve_provider_model(provider, model)

    # Derive a readable agent name when caller doesn't supply one
    if not agent:
        frame = inspect.stack()[1]
        caller_mod = frame[0].f_globals.get("__name__", "")
        agent = caller_mod.rsplit(".", 1)[-1]

    last = ""
    for attempt in range(retries + 1):
        last = await call_llm(user, provider=p, model=m, system=system)
        if last and not last.startswith("[Error:"):
            break
        if attempt < retries:
            await asyncio.sleep(1.0 * (attempt + 1))  # 1s, 2s backoff

    log_llm_call(agent=agent, system=system, prompt=user, response=last)
    return last


def parse_json_response(raw: str) -> dict:
    """Strip markdown fences and parse JSON safely."""
    import json
    clean = raw.strip()
    # Remove optional fenced code blocks (```json ... ```)
    clean = re.sub(r"^```(?:json)?\s*", "", clean, flags=re.IGNORECASE)
    clean = re.sub(r"\s*```$", "", clean)
    clean = clean.strip()
    return json.loads(clean)


async def shared_run_shell(command: str, cwd: str, agent_name: str) -> str:
    t = time.monotonic()
    if not is_safe_command(command):
        return f"Command '{command}' is not in the safe allowlist."
    try:
        proc = await asyncio.create_subprocess_shell(
            command,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            cwd=cwd or os.path.expanduser("~"),
        )
        stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=SHELL_TIMEOUT_SECONDS)
        result = (stdout.decode().strip() + "\n" + stderr.decode().strip())[:SHELL_OUTPUT_MAX_CHARS]
        log_tool("run_shell", "ok", agent_name, duration_ms=int((time.monotonic() - t) * 1000))
        return result
    except asyncio.TimeoutError:
        return "Command timed out."
    except Exception as exc:
        return f"Error: {exc}"
