"""
Sarthak Agent Sandbox — ProcessSandbox.

Executes shell commands in a child process with:
  - Stripped environment (allowlist only)
  - CWD locked via PathGuard
  - Wall-clock timeout
  - POSIX rlimits: CPU time + address space (Linux/macOS only — skipped on Windows)
  - stdout/stderr captured and size-capped

Cross-platform: preexec_fn is never passed on Windows (sys.platform == 'win32').
"""
from __future__ import annotations

import asyncio
import os
import sys
from pathlib import Path

from sarthak.agents.sandbox.audit import emit
from sarthak.agents.sandbox.config import SandboxConfig
from sarthak.agents.sandbox.path_guard import PathGuard
from sarthak.agents.sandbox.secret_scrubber import scrub, scrub_env

_WIN = sys.platform == "win32"
_PROC_OUTPUT_CAP = 32 * 1024  # 32 KB


class ShellDenied(PermissionError):
    pass


class ShellTimeout(TimeoutError):
    pass


async def run_shell(command: str, cfg: SandboxConfig, guard: PathGuard) -> str:
    """Run *command* in a sandboxed subprocess. Returns scrubbed, capped output."""
    if not cfg.allow_shell:
        raise ShellDenied(f"Agent '{cfg.agent_id}' does not have shell permission.")

    cwd = guard.safe_cwd("")
    safe_env = scrub_env(dict(os.environ))

    emit("agent_sandbox_shell_start", agent_id=cfg.agent_id, cwd=cwd,
         command_preview=command[:120])

    try:
        stdout_t, stderr_t = await _launch(command, cwd, safe_env, cfg)
    except asyncio.TimeoutError:
        emit("agent_timeout", agent_id=cfg.agent_id, phase="shell", timeout=cfg.wall_timeout)
        raise ShellTimeout(f"Shell command exceeded {cfg.wall_timeout}s timeout.")

    combined = (stdout_t + "\n" + stderr_t).strip()
    if len(combined) > _PROC_OUTPUT_CAP:
        emit("agent_output_truncated", agent_id=cfg.agent_id, original_len=len(combined))
        combined = combined[:_PROC_OUTPUT_CAP] + "\n[output truncated]"

    scrubbed, _ = scrub(combined, agent_id=cfg.agent_id)
    return scrubbed


async def _launch(
    command: str, cwd: str, env: dict[str, str], cfg: SandboxConfig,
) -> tuple[str, str]:
    kwargs: dict = dict(
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
        cwd=cwd,
        env=env,
    )
    # preexec_fn is POSIX-only — never pass it on Windows
    if not _WIN and cfg.rlimits_available:
        kwargs["preexec_fn"] = _make_preexec(cfg)

    proc = await asyncio.create_subprocess_shell(command, **kwargs)
    try:
        stdout_b, stderr_b = await asyncio.wait_for(
            proc.communicate(), timeout=cfg.wall_timeout
        )
    except asyncio.TimeoutError:
        try:
            proc.kill()
        except ProcessLookupError:
            pass
        try:
            await asyncio.wait_for(proc.communicate(), timeout=5)
        except Exception:
            pass
        raise

    return (
        stdout_b.decode("utf-8", errors="replace"),
        stderr_b.decode("utf-8", errors="replace"),
    )


def _make_preexec(cfg: SandboxConfig):
    """Return a preexec_fn that applies POSIX rlimits in the child process."""
    import resource
    cpu, mem = cfg.cpu_seconds, cfg.memory_cap

    def _apply():
        resource.setrlimit(resource.RLIMIT_CPU,    (cpu, cpu))
        resource.setrlimit(resource.RLIMIT_AS,     (mem, mem))
        resource.setrlimit(resource.RLIMIT_NOFILE, (64, 64))

    return _apply
