"""
Sarthak AI — Centralized logging configuration.
Single source of truth for structlog setup across all modules.

Usage:
    from sarthak.core.logging import setup_logging, get_logger

    # At process startup (once):
    setup_logging(cfg)

    # In every module:
    log = get_logger(__name__)
"""
from __future__ import annotations

import logging
import sys
from pathlib import Path
from typing import Any, TextIO

import structlog

_configured = False
_log_file: TextIO | None = None


class _Tee:
    """Write to multiple streams simultaneously."""

    def __init__(self, *streams: TextIO) -> None:
        self._streams = streams

    def write(self, data: str) -> int:
        total = 0
        for s in self._streams:
            total += s.write(data)
        return total

    def flush(self) -> None:
        for s in self._streams:
            s.flush()

    def isatty(self) -> bool:
        return any(getattr(s, "isatty", lambda: False)() for s in self._streams)


def get_orchestration_log_path() -> Path:
    """Return the orchestration log path inside the install dir (not repo root).

    Priority:
      1. ~/.sarthak_ai/logs/orchestration.log   (production install)
      2. ./orchestration.log                     (dev / fallback)
    """
    candidate = Path.home() / ".sarthak_ai" / "logs" / "orchestration.log"
    try:
        candidate.parent.mkdir(parents=True, exist_ok=True)
        return candidate
    except OSError:
        return Path("orchestration.log")


def enable_file_logging(log_path: Path) -> None:
    """Mirror stderr to a file for background services. Idempotent."""
    global _log_file
    if _log_file:
        return
    try:
        log_path.parent.mkdir(parents=True, exist_ok=True)
        _log_file = log_path.open("a", encoding="utf-8")
        sys.stderr = _Tee(sys.stderr, _log_file)
    except OSError as exc:
        # Non-fatal: log to stderr only
        print(f"[sarthak] Warning: could not open log file {log_path}: {exc}", file=sys.stderr)


def setup_logging(cfg: dict[str, Any] | None = None) -> None:
    """Configure structlog for the entire process. Safe to call multiple times."""
    global _configured
    if _configured:
        return
    _configured = True

    level_name = "INFO"
    fmt        = "console"

    if cfg:
        general    = cfg.get("general", {})
        level_name = general.get("log_level", "INFO").upper()
        fmt        = general.get("log_format", "console")

    level = getattr(logging, level_name, logging.INFO)

    shared_processors: list[Any] = [
        structlog.contextvars.merge_contextvars,
        structlog.processors.add_log_level,
        structlog.processors.TimeStamper(fmt="iso"),
        structlog.processors.StackInfoRenderer(),
        structlog.processors.ExceptionRenderer(),
    ]

    if fmt == "json":
        shared_processors.append(structlog.processors.JSONRenderer())
    else:
        shared_processors.append(
            structlog.dev.ConsoleRenderer(colors=getattr(sys.stderr, "isatty", lambda: False)())
        )

    structlog.configure(
        processors=shared_processors,
        wrapper_class=structlog.make_filtering_bound_logger(level),
        logger_factory=structlog.PrintLoggerFactory(),
        cache_logger_on_first_use=True,
    )

    logging.basicConfig(format="%(message)s", stream=sys.stderr, level=level)
    for noisy in ("httpx", "httpcore", "telegram", "asyncio"):
        logging.getLogger(noisy).setLevel(logging.WARNING)


def get_logger(name: str) -> structlog.BoundLogger:
    """Return a structlog logger bound with the module name as 'logger'."""
    return structlog.get_logger().bind(logger=name)
