"""System tools — service status, restart, desktop notifications."""
from __future__ import annotations

import asyncio
import sys

from sarthak.core.constants import (
    ALLOWED_RESTART_SERVICES,
    SYSTEMD_SERVICES,
    SERVICE_CHECK_TIMEOUT,
    SERVICE_RESTART_TIMEOUT,
)
from sarthak.core.logging import get_logger

log = get_logger(__name__)


async def tool_service_status() -> str:
    """Return service status for all Sarthak services (Linux/systemd only)."""
    if sys.platform != "linux" or not SYSTEMD_SERVICES:
        return "Service management is only available on Linux with systemd."
    lines = []
    for svc in SYSTEMD_SERVICES:
        proc = await asyncio.create_subprocess_exec(
            "systemctl", "--user", "is-active", svc,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, _ = await asyncio.wait_for(proc.communicate(), timeout=SERVICE_CHECK_TIMEOUT)
        lines.append(f"{svc}: {stdout.decode().strip()}")
    return "\n".join(lines)


async def tool_restart_service(service: str) -> str:
    """Restart a Sarthak systemd user service (Linux only, allowlisted)."""
    if sys.platform != "linux":
        return "Service restart is only supported on Linux with systemd."
    if service not in ALLOWED_RESTART_SERVICES:
        return f"Cannot restart '{service}'. Allowed: {', '.join(ALLOWED_RESTART_SERVICES)}"
    proc = await asyncio.create_subprocess_exec(
        "systemctl", "--user", "restart", service,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    _, stderr = await asyncio.wait_for(proc.communicate(), timeout=SERVICE_RESTART_TIMEOUT)
    err = stderr.decode().strip()
    return f"Restarted {service}." + (f" Warning: {err}" if err else "")


async def tool_send_notification(title: str, body: str) -> str:
    """Send a desktop notification via dunstify (non-blocking)."""
    try:
        await asyncio.create_subprocess_exec(
            "dunstify", "-a", "Sarthak", title, body,
            stdout=asyncio.subprocess.DEVNULL,
            stderr=asyncio.subprocess.DEVNULL,
        )
        return "Notification sent."
    except Exception as exc:
        return f"Notification failed: {exc}"
