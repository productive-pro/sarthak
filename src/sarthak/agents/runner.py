"""
Sarthak Agent Engine — executor.

run_agent(spec) → AgentRun
  1. Build SandboxConfig from spec
  2. Read agent memory (deduplicated, if spec.enable_memory)
  3. Enforce sandbox: scrub → timeout → scrub output → cap
  4. Persist run + update next_run_at
  5. Write memory note (compact, deduped)
  6. Notify (Telegram / WhatsApp)

Model tier routing (fast/balanced/powerful) is resolved in _execute().
Context assembly (memory + space dirs) uses asyncio.gather for parallel I/O.
"""
from __future__ import annotations

import asyncio
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

_MEM_MAX_CHARS = 800
_MEM_MAX_LINES = 60
_MEM_SNIPPET   = 200


# ── Agent memory ──────────────────────────────────────────────────────────────

def _memory_dir(spec: AgentSpec) -> Path:
    from sarthak.agents.store import _agent_dir
    return _agent_dir(spec) / "memory"


def _read_agent_memory(spec: AgentSpec) -> str:
    """Read recent memory notes (deduped lines, newest-first)."""
    if not spec.enable_memory:
        return ""
    mem_dir = _memory_dir(spec)
    if not mem_dir.exists():
        return ""
    notes = sorted(mem_dir.glob("*.md"), reverse=True)[:5]
    seen: set[str] = set()
    parts: list[str] = []
    for p in notes:
        try:
            for line in p.read_text(encoding="utf-8").splitlines():
                line = line.strip()
                if line and line not in seen:
                    seen.add(line)
                    parts.append(line)
        except Exception:
            pass
    combined = "\n".join(parts)
    return combined[:_MEM_MAX_CHARS] if combined else ""


def _write_memory_note(spec: AgentSpec, output: str) -> None:
    """Append a compact run summary to today's memory file (deduped, capped)."""
    if not spec.enable_memory or not output:
        return
    try:
        mem_dir = _memory_dir(spec)
        mem_dir.mkdir(parents=True, exist_ok=True)
        today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        note_file = mem_dir / f"{today}.md"
        snippet = output[:_MEM_SNIPPET].replace("\n", " ").strip()
        line = f"- {today}: {snippet}\n"
        # Avoid writing duplicate lines
        existing = note_file.read_text(encoding="utf-8") if note_file.exists() else ""
        if snippet in existing:
            return
        with note_file.open("a", encoding="utf-8") as f:
            f.write(line)
        # Trim to cap
        lines = note_file.read_text(encoding="utf-8").splitlines(keepends=True)
        if len(lines) > _MEM_MAX_LINES:
            note_file.write_text("".join(lines[-_MEM_MAX_LINES:]), encoding="utf-8")
    except Exception as exc:
        log.debug("memory_note_write_failed", agent_id=spec.agent_id, error=str(exc))


# ── Pre-tool hook ─────────────────────────────────────────────────────────────

async def _pre_tool_hook(tool_name: str, tool_input: dict, spec: AgentSpec, guard: PathGuard) -> str | None:
    """Block disallowed tool calls before they execute. Returns error string or None."""
    try:
        if tool_name == "write_file":
            path_arg = tool_input.get("path", "")
            if path_arg:
                try:
                    guard.check_write(path_arg)
                except PathViolation as e:
                    log.warning("pre_tool_hook_blocked_write", agent_id=spec.agent_id, path=path_arg)
                    return f"Pre-tool hook: write blocked — {e}"
        if tool_name == "run_shell" and AgentTool.SHELL not in spec.tools:
            log.warning("pre_tool_hook_blocked_shell", agent_id=spec.agent_id)
            return "Pre-tool hook: shell access not declared for this agent."
    except Exception as exc:
        log.debug("pre_tool_hook_error", agent_id=spec.agent_id, error=str(exc))
    return None


# ── Prompt assembly ───────────────────────────────────────────────────────────

async def _build_prompt(spec: AgentSpec) -> str:
    """Assemble prompt: memory + space contexts (parallel I/O) + task."""
    parts: list[str] = []

    memory_ctx = _read_agent_memory(spec)
    if memory_ctx:
        parts.append(f"## Agent Memory\n{memory_ctx}")

    # Collect all space dirs to load concurrently
    space_dirs: list[str] = []
    if spec.scope == AgentScope.SPACE and spec.space_dir:
        space_dirs.append(spec.space_dir)
    space_dirs.extend(spec.context_space_dirs)

    if space_dirs:
        from sarthak.spaces.store import get_space_context

        async def _load(d: str) -> str | None:
            try:
                return await asyncio.to_thread(get_space_context, Path(d))
            except Exception as exc:
                log.debug("context_load_failed", space_dir=d, error=str(exc))
                return None

        results = await asyncio.gather(*[_load(d) for d in space_dirs])
        parts.extend(ctx for ctx in results if ctx and ctx.strip())

    parts.append(spec.prompt)
    return "\n\n---\n\n".join(parts)


# ── Tool builders ─────────────────────────────────────────────────────────────

def _make_file_read_tool(guard: PathGuard):
    from pydantic_ai import Tool

    def read_file(path: str) -> str:
        """Read a file within the agent's sandbox read roots."""
        try:
            return guard.check_read(path).read_text(encoding="utf-8", errors="replace")
        except PathViolation as e:
            return f"Access denied: {e}"
        except OSError as e:
            return f"Read error: {e}"

    return Tool(read_file, name="read_file", description="Read a file by path (sandboxed).")


def _make_file_write_tool(guard: PathGuard, spec: AgentSpec):
    from pydantic_ai import Tool

    async def write_file(path: str, content: str) -> str:
        """Write content atomically within the agent's sandbox write roots."""
        if blocked := await _pre_tool_hook("write_file", {"path": path}, spec, guard):
            return blocked
        try:
            resolved = guard.check_write(path)
        except PathViolation as e:
            return f"Access denied: {e}"
        try:
            resolved.parent.mkdir(parents=True, exist_ok=True)
            tmp = resolved.with_suffix(resolved.suffix + ".tmp")
            tmp.write_text(content, encoding="utf-8")
            tmp.replace(resolved)
            return f"Written: {resolved}"
        except OSError as e:
            return f"Write error: {e}"

    return Tool(write_file, name="write_file", description="Write content to a file (sandboxed, atomic).")


def _make_http_fetch_tool():
    from pydantic_ai import Tool

    async def http_fetch(url: str) -> str:
        """Fetch text content from a single URL."""
        import httpx
        try:
            async with httpx.AsyncClient(follow_redirects=True, timeout=20) as client:
                r = await client.get(url, headers={"User-Agent": "sarthak-agent/1.0"})
                r.raise_for_status()
                return r.text[:32_000]
        except Exception as e:
            return f"Fetch error: {e}"

    return Tool(http_fetch, name="http_fetch", description="Fetch text from a URL.")


def _make_shell_tool(cfg: SandboxConfig, guard: PathGuard, spec: AgentSpec):
    from pydantic_ai import Tool

    async def run_command(command: str) -> str:
        """Run a shell command inside the agent sandbox."""
        if blocked := await _pre_tool_hook("run_shell", {"command": command}, spec, guard):
            return blocked
        return await run_shell(command, cfg, guard)

    return Tool(run_command, name="run_shell", description="Execute a shell command (sandboxed).")


def _build_tools(spec: AgentSpec, cfg: SandboxConfig, guard: PathGuard) -> list:
    tools = []
    if cfg.allow_file_read:
        tools.append(_make_file_read_tool(guard))
    if cfg.allow_file_write:
        tools.append(_make_file_write_tool(guard, spec))
    if cfg.allow_http_fetch:
        tools.append(_make_http_fetch_tool())
    if cfg.allow_shell:
        tools.append(_make_shell_tool(cfg, guard, spec))
    if cfg.allow_web:
        from pydantic_ai.common_tools.duckduckgo import duckduckgo_search_tool
        tools.append(duckduckgo_search_tool(max_results=cfg.max_web_calls))
    return tools


# ── Core execution ────────────────────────────────────────────────────────────

async def _execute(spec: AgentSpec, cfg: SandboxConfig) -> tuple[str, list[str]]:
    """Build tier-appropriate model, assemble prompt, run agent."""
    from pydantic_ai import Agent
    from sarthak.features.ai.agents._base import resolve_provider_model
    from sarthak.core.ai_utils.multi_provider import build_fallback_model, resolve_model_for_tier
    from sarthak.core.config import load_config

    guard = PathGuard(cfg)
    # Parallel: build prompt + resolve model config
    cfg_data = load_config()
    prompt = await _build_prompt(spec)
    tools = _build_tools(spec, cfg, guard)

    p_str, _ = resolve_provider_model()
    model_str = resolve_model_for_tier(p_str, spec.model_tier, cfg_data)
    model = build_fallback_model(p_str, model_str, cfg_data)

    log.debug("agent_execute", agent_id=spec.agent_id, tier=spec.model_tier, model=model_str)
    result = await Agent(model, output_type=str, tools=tools).run(prompt)
    return result.output or "", [t.value for t in spec.tools]


# ── Main entry point ──────────────────────────────────────────────────────────

async def run_agent(spec: AgentSpec) -> AgentRun:
    run = AgentRun(
        run_id=new_run_id(),
        agent_id=spec.agent_id,
        model_tier_used=spec.model_tier,
    )
    log.info("agent_run_start", agent_id=spec.agent_id, run_id=run.run_id, tier=spec.model_tier)

    try:
        output, tools_used = await enforce_sandbox(spec, _execute)
        run.output, run.tools_used, run.success = output, tools_used, bool(output)
    except Exception as exc:
        run.error, run.success = str(exc), False
        log.error("agent_run_failed", agent_id=spec.agent_id, error=str(exc))

    run.finished_at = datetime.now(timezone.utc).isoformat()
    save_run(spec, run)
    update_agent(
        spec.agent_id,
        last_run_at=datetime.now(timezone.utc).isoformat(),
        next_run_at=compute_next_run(spec.schedule),
    )

    if run.success:
        _write_memory_note(spec, run.output)

    if spec.notify_telegram and run.output:
        from sarthak.core.config import load_config
        await send_telegram(load_config(), run.output[:3800], agent_id=spec.agent_id)

    if getattr(spec, "notify_whatsapp", False) and run.output:
        try:
            from sarthak.features.channels.whatsapp import send_message_standalone
            await send_message_standalone(run.output[:3800])
        except Exception as exc:
            log.warning("whatsapp_notify_failed", agent_id=spec.agent_id, error=str(exc))

    log.info("agent_run_done", agent_id=spec.agent_id, success=run.success)
    return run
