"""
Sarthak Agent Sandbox — Audit log.

All sandbox events are emitted here via structlog so they flow into the
existing orchestration log without any extra configuration.

Event names follow the pattern:  agent_<noun>_<verb>
"""
from __future__ import annotations

from typing import Any

import structlog

_log = structlog.get_logger("sarthak.agents.sandbox")


def emit(event: str, **fields: Any) -> None:
    """Emit a structured sandbox audit event."""
    _log.info(event, **fields)
