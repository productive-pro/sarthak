"""
Sarthak Agent Sandbox — ProcessSandbox.

Executes shell commands in a child process with:
  - Stripped environment (allowlist only, no credentials)
  - CWD locked via PathGuard
  - Wall-clock timeout
  - POSIX rlimits: CPU time + address space (skipped on Windows)
  - stdout/stderr captured and size-capped
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


class ShellDenied(PermissionError):
    """Raised when shell execution is not permitted by SandboxConfig."""


class ShellTimeout(TimeoutError):
    """Raised when the subprocess exceeds its wall-clock timeout."""


# Output size cap for subprocess stdout+stderr combined (32 KB)
_PROC_OUTPUT_CAP = 32 * 1024


async def run_shell(
    command: str,
    cfg: SandboxConfig,
    guard: PathGuard,
) -> str:
    """
    Run *command* in a sandboxed subprocess.

    Returns combined stdout+stderr (scrubbed, capped).
    Raises ShellDenied if shell is not allowed by cfg.
    Raises ShellTimeout on wall-clock timeout.
    """
    if not cfg.allow_shell:
        raise ShellDenied(
            f"Agent '{cfg.agent_id}' does not have shell permission."
        )

    cwd = guard.safe_cwd("")
    safe_env = scrub_env(dict(os.environ))

    emit(
        "agent_sandbox_shell_start",
        agent_id=cfg.agent_id,
        cwd=cwd,
        command_preview=command[:120],
    )

    try:
        proc = await asyncio.wait_for(
            _launch(command, cwd, safe_env, cfg),
            timeout=cfg.wall_timeout,
        )
    except asyncio.TimeoutError:
        emit("agent_timeout", agent_id=cfg.agent_id, phase="shell", timeout=cfg.wall_timeout)
        raise ShellTimeout(
            f"Agent '{cfg.agent_id}' shell command exceeded {cfg.wall_timeout}s timeout."
        )

    stdout, stderr = proc
    combined = (stdout + "\n" + stderr).strip()

    if len(combined) > _PROC_OUTPUT_CAP:
        emit("agent_output_truncated", agent_id=cfg.agent_id, original_len=len(combined))
        combined = combined[:_PROC_OUTPUT_CAP] + "\n[output truncated]"

    scrubbed, _ = scrub(combined, agent_id=cfg.agent_id)
    return scrubbed


async def _launch(
    command: str,
    cwd: str,
    env: dict[str, str],
    cfg: SandboxConfig,
) -> tuple[str, str]:
    """
    Spawn the subprocess with rlimits (POSIX) or plain limits (Windows).
    Returns (stdout_text, stderr_text).
    """
    preexec = _make_preexec(cfg) if cfg.rlimits_available else None

    proc = await asyncio.create_subprocess_shell(
        command,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
        cwd=cwd,
        env=env,
        preexec_fn=preexec,
    )

    try:
        stdout_b, stderr_b = await asyncio.wait_for(
            proc.communicate(), timeout=cfg.wall_timeout
        )
    except asyncio.TimeoutError:
        proc.kill()
        await proc.communicate()
        raise

    return (
        stdout_b.decode("utf-8", errors="replace"),
        stderr_b.decode("utf-8", errors="replace"),
    )


def _make_preexec(cfg: SandboxConfig):
    """
    Return a preexec_fn that applies POSIX rlimits in the child process.
    Called after fork(), before exec() — POSIX only.
    """
    import resource  # available on POSIX

    cpu_seconds = cfg.cpu_seconds
    memory_cap  = cfg.memory_cap

    def _apply():
        # CPU time: SIGKILL after cpu_seconds
        resource.setrlimit(resource.RLIMIT_CPU, (cpu_seconds, cpu_seconds))
        # Address space: hard cap on virtual memory
        resource.setrlimit(resource.RLIMIT_AS, (memory_cap, memory_cap))
        # Max open file descriptors: 64
        resource.setrlimit(resource.RLIMIT_NOFILE, (64, 64))

    return _apply
