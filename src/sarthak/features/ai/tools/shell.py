"""Shell tool — safe read-only command execution."""
from __future__ import annotations

import asyncio
import os

from sarthak.core.logging import get_logger
from sarthak.core.constants import (
    SAFE_SHELL_PREFIXES,
    SHELL_BLOCK_PATTERNS,
    SHELL_TIMEOUT_SECONDS,
    SHELL_OUTPUT_MAX_CHARS,
)

log = get_logger(__name__)


def is_safe_command(command: str) -> bool:
    if not command.strip():
        return False
    if any(p in command for p in SHELL_BLOCK_PATTERNS):
        return False
    return os.path.basename(command.strip().split()[0]) in SAFE_SHELL_PREFIXES


async def tool_run_shell(command: str, cwd: str | None = None) -> str:
    """Run a safe read-only shell command. Returns stdout+stderr (truncated)."""
    if not is_safe_command(command):
        return f"Command not allowed: '{command}'. Only read-only commands are permitted."
    try:
        proc = await asyncio.create_subprocess_shell(
            command,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            cwd=cwd or os.path.expanduser("~"),
        )
        stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=SHELL_TIMEOUT_SECONDS)
        combined = (stdout.decode().strip() + "\n" + stderr.decode().strip()).strip()
        return combined[:SHELL_OUTPUT_MAX_CHARS] or "(no output)"
    except asyncio.TimeoutError:
        return f"Command timed out ({SHELL_TIMEOUT_SECONDS}s limit)."
    except Exception as exc:
        return f"Shell error: {exc}"
