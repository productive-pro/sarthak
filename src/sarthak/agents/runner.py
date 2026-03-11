"""
Sarthak Agent Engine — executor.

run_agent(spec) → AgentRun
  1. Build sandbox config from spec
  2. Scrub secrets from prompt (enforcer)
  3. Execute with wall-clock timeout (enforcer)
  4. Scrub secrets from output (enforcer)
  5. Cap output size (enforcer)
  6. Save run record
  7. Optionally notify Telegram
"""
from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

import structlog

from sarthak.agents.models import AgentRun, AgentScope, AgentSpec, AgentTool
from sarthak.agents.sandbox import SandboxConfig, enforce_sandbox
from sarthak.agents.sandbox.path_guard import PathGuard, PathViolation
from sarthak.agents.sandbox.process_sandbox import run_shell
from sarthak.agents.store import compute_next_run, new_run_id, save_run, update_agent
from sarthak.core.notify import send_telegram

log = structlog.get_logger(__name__)


async def run_agent(spec: AgentSpec) -> AgentRun:
    run = AgentRun(run_id=new_run_id(), agent_id=spec.agent_id)
    log.info("agent_run_start", agent_id=spec.agent_id, run_id=run.run_id)

    try:
        output, tools_used = await enforce_sandbox(spec, _execute)
        run.output = output
        run.tools_used = tools_used
        run.success = bool(output)
    except Exception as exc:
        run.error = str(exc)
        run.success = False
        log.error("agent_run_failed", agent_id=spec.agent_id, error=str(exc))

    run.finished_at = datetime.now(timezone.utc).isoformat()
    save_run(spec, run)
    update_agent(
        spec.agent_id,
        last_run_at=datetime.now(timezone.utc).isoformat(),
        next_run_at=compute_next_run(spec.schedule),
    )

    if spec.notify_telegram and run.output:
        from sarthak.core.config import load_config
        await send_telegram(load_config(), run.output[:3800], agent_id=spec.agent_id)

    if getattr(spec, "notify_whatsapp", False) and run.output:
        try:
            from sarthak.features.channels.whatsapp.client import send_message_standalone
            await send_message_standalone(run.output[:3800])
        except Exception as exc:
            log.warning("whatsapp_notify_failed", agent_id=spec.agent_id, error=str(exc))

    log.info("agent_run_done", agent_id=spec.agent_id, success=run.success)
    return run


# ── Tool builders ─────────────────────────────────────────────────────────────

def _make_file_read_tool(guard: PathGuard):
    """Cross-platform sandboxed file read tool for pydantic-ai."""
    from pydantic_ai import Tool

    def read_file(path: str) -> str:
        """Read a file within the agent's sandbox read/write roots."""
        try:
            resolved = guard.check_read(path)
        except PathViolation as e:
            return f"Access denied: {e}"
        try:
            return resolved.read_text(encoding="utf-8", errors="replace")
        except OSError as e:
            return f"Read error: {e}"

    return Tool(read_file, name="read_file", description="Read a file by path (sandboxed).")


def _make_file_write_tool(guard: PathGuard):
    """Cross-platform sandboxed atomic file write tool for pydantic-ai."""
    from pydantic_ai import Tool

    def write_file(path: str, content: str) -> str:
        """Write content to a file within the agent's sandbox write roots. Atomic on all platforms."""
        try:
            resolved = guard.check_write(path)
        except PathViolation as e:
            return f"Access denied: {e}"
        try:
            resolved.parent.mkdir(parents=True, exist_ok=True)
            # Atomic write: write to temp sibling, then replace
            tmp = resolved.with_suffix(resolved.suffix + ".tmp")
            tmp.write_text(content, encoding="utf-8")
            tmp.replace(resolved)   # atomic on POSIX; best-effort on Windows (py3.3+)
            return f"Written: {resolved}"
        except OSError as e:
            return f"Write error: {e}"

    return Tool(write_file, name="write_file", description="Write content to a file (sandboxed, atomic).")


def _make_http_fetch_tool():
    """Narrow HTTP fetch tool — single URL, no search API."""
    from pydantic_ai import Tool

    async def http_fetch(url: str) -> str:
        """Fetch the text content of a single URL."""
        import httpx
        try:
            async with httpx.AsyncClient(follow_redirects=True, timeout=20) as client:
                r = await client.get(url, headers={"User-Agent": "sarthak-agent/1.0"})
                r.raise_for_status()
                return r.text[:32_000]
        except Exception as e:
            return f"Fetch error: {e}"

    return Tool(http_fetch, name="http_fetch", description="Fetch text content from a single URL.")


def _make_shell_tool(cfg: SandboxConfig, guard: PathGuard):
    """Sandboxed shell tool — delegates to ProcessSandbox."""
    from pydantic_ai import Tool

    async def run_command(command: str) -> str:
        """Run a shell command inside the agent sandbox."""
        return await run_shell(command, cfg, guard)

    return Tool(run_command, name="run_shell", description="Execute a shell command (sandboxed).")


def _build_tools(spec: AgentSpec, cfg: SandboxConfig, guard: PathGuard) -> list:
    tools = []
    if cfg.allow_file_read:
        tools.append(_make_file_read_tool(guard))
    if cfg.allow_file_write:
        tools.append(_make_file_write_tool(guard))
    if cfg.allow_http_fetch:
        tools.append(_make_http_fetch_tool())
    if cfg.allow_shell:
        tools.append(_make_shell_tool(cfg, guard))
    if cfg.allow_web:
        from pydantic_ai.common_tools.duckduckgo import duckduckgo_search_tool
        tools.append(duckduckgo_search_tool(max_results=cfg.max_web_calls))
    return tools


# ── Execution ─────────────────────────────────────────────────────────────────

async def _build_prompt(spec: AgentSpec) -> str:
    """Assemble full prompt with space context for space/multi-space agents."""
    parts: list[str] = []
    from sarthak.spaces.store import get_space_context

    # Primary space context
    if spec.scope == AgentScope.SPACE and spec.space_dir:
        ctx = get_space_context(Path(spec.space_dir))
        if ctx and ctx.strip():
            parts.append(ctx)

    # Extra context spaces (system agents that span multiple spaces)
    for extra_dir in spec.context_space_dirs:
        try:
            ctx = get_space_context(Path(extra_dir))
            if ctx and ctx.strip():
                parts.append(ctx)
        except Exception as exc:
            log.debug("context_load_failed", space_dir=extra_dir, error=str(exc))

    parts.append(spec.prompt)
    return "\n\n---\n\n".join(parts)


async def _execute(spec: AgentSpec, cfg: SandboxConfig) -> tuple[str, list[str]]:
    from pydantic_ai import Agent
    from sarthak.features.ai.agents._base import build_pydantic_model, resolve_provider_model

    guard = PathGuard(cfg)
    prompt = await _build_prompt(spec)
    tools = _build_tools(spec, cfg, guard)

    p, m = resolve_provider_model()
    agent: Agent = Agent(
        build_pydantic_model(p, m),
        output_type=str,
        tools=tools,
    )

    result = await agent.run(prompt)
    tools_used = [t.value for t in spec.tools]
    return result.output or "", tools_used
