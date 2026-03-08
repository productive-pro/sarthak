"""
Sarthak AI — Process supervisor.
`sarthak orchestrator` starts background services (web, telegram) in the foreground until
SIGTERM/SIGINT.

Services are defined in _SERVICES. Each gets a shared asyncio.Event for
coordinated shutdown.

Key design decisions:
  - Telegram is isolated: network/DB failures never crash the orchestrator.
  - Web port conflict is resolved cross-platform (psutil, no lsof required).
  - Network readiness probe delays Telegram start until DNS is up.
"""
from __future__ import annotations

import asyncio
import os
import signal
import sys
from typing import Any

from sarthak.core.logging import (
    enable_file_logging,
    get_logger,
    get_orchestration_log_path,
    setup_logging,
)

log = get_logger(__name__)

_IS_WINDOWS = sys.platform == "win32"


# ── Helpers ───────────────────────────────────────────────────────────────────

async def _wait_for_network(
    host: str = "api.telegram.org",
    port: int = 443,
    timeout: float = 120.0,
    interval: float = 5.0,
    stop: asyncio.Event | None = None,
) -> bool:
    """Probe TCP connectivity; return True when reachable, False on timeout/stop."""
    deadline = asyncio.get_event_loop().time() + timeout
    attempt = 0
    while True:
        if stop and stop.is_set():
            return False
        try:
            _, writer = await asyncio.wait_for(
                asyncio.open_connection(host, port), timeout=5
            )
            writer.close()
            try:
                await writer.wait_closed()
            except Exception:
                pass
            return True
        except (OSError, asyncio.TimeoutError):
            attempt += 1
            remaining = deadline - asyncio.get_event_loop().time()
            if remaining <= 0:
                return False
            wait = min(interval, remaining)
            log.info(
                "network_probe_waiting",
                host=host, attempt=attempt, retry_in=wait,
            )
            try:
                if stop:
                    await asyncio.wait_for(
                        asyncio.shield(stop.wait()), timeout=wait
                    )
                else:
                    await asyncio.sleep(wait)
                if stop and stop.is_set():
                    return False
            except asyncio.TimeoutError:
                pass


def _free_port_cross_platform(port: int) -> None:
    """Kill any process listening on *port* — works on Linux, macOS, Windows."""
    try:
        import psutil
    except ImportError:
        log.warning("psutil_missing_skipping_port_kill", port=port)
        return
    for proc in psutil.process_iter(["pid"]):
        try:
            for conn in proc.net_connections(kind="inet"):
                if conn.laddr.port == port and conn.status == "LISTEN":
                    log.info("killing_port_owner", pid=proc.pid, port=port)
                    proc.terminate()
                    try:
                        proc.wait(timeout=3)
                    except psutil.TimeoutExpired:
                        proc.kill()
                    return
        except (psutil.NoSuchProcess, psutil.AccessDenied, AttributeError):
            continue


# ── Service runners ───────────────────────────────────────────────────────────

async def _run_agent_scheduler(cfg: dict[str, Any], stop: asyncio.Event) -> None:
    """Run the agent scheduler loop until stop is set."""
    from sarthak.agents.scheduler import run_scheduler_loop
    scheduler_task = asyncio.create_task(run_scheduler_loop(interval_seconds=60))
    await stop.wait()
    scheduler_task.cancel()
    await asyncio.gather(scheduler_task, return_exceptions=True)


async def _run_telegram(cfg: dict[str, Any], stop: asyncio.Event) -> None:
    """Start telegram bot, isolated so crashes never propagate to orchestrator.

    Boot sequence:
      1. Wait up to 2 min for network (TCP to api.telegram.org:443).
      2. Retry bot on any network/transient error with exponential backoff.
      3. Non-network errors are logged but do NOT raise — telegram is optional.
    """
    import httpx

    _NETWORK_ERRORS = (
        httpx.ConnectError,
        httpx.ConnectTimeout,
        httpx.NetworkError,
        OSError,
    )
    _MAX_DELAY = 300  # seconds
    delay = 5

    # ── 1. Network readiness probe ────────────────────────────────────────────
    log.info("telegram_waiting_for_network")
    reachable = await _wait_for_network(
        host="api.telegram.org", port=443,
        timeout=120.0, interval=5.0, stop=stop,
    )
    if not reachable:
        if stop.is_set():
            return
        log.warning(
            "telegram_network_unreachable",
            hint="api.telegram.org:443 unreachable after 120s — bot will not start",
        )
        return  # Don't crash orchestrator — telegram is optional

    log.info("telegram_network_ready")

    from sarthak.features.channels.telegram.bot import run_bot

    # ── 2. Run with retry loop ────────────────────────────────────────────────
    while not stop.is_set():
        bot_task = asyncio.create_task(run_bot(cfg))
        stop_task = asyncio.create_task(stop.wait())
        done, pending = await asyncio.wait(
            {bot_task, stop_task}, return_when=asyncio.FIRST_COMPLETED
        )
        for t in pending:
            t.cancel()
        await asyncio.gather(*pending, return_exceptions=True)

        if stop.is_set():
            return

        if bot_task in done and not bot_task.cancelled():
            exc = bot_task.exception()
            if exc is None:
                return  # clean exit
            if isinstance(exc, _NETWORK_ERRORS):
                log.warning(
                    "telegram_network_error_retrying",
                    error=str(exc),
                    retry_in=delay,
                )
                try:
                    await asyncio.wait_for(stop.wait(), timeout=delay)
                except asyncio.TimeoutError:
                    pass
                delay = min(delay * 2, _MAX_DELAY)
                continue
            # ── Non-network error: log but DO NOT propagate ─────────────────
            log.error(
                "telegram_fatal_error",
                error=repr(exc),
                hint="Telegram bot stopped; orchestrator continues running.",
            )
            return


async def _run_web(cfg: dict[str, Any], stop: asyncio.Event) -> None:
    """Run the FastAPI web server via uvicorn's async API.

    Uses psutil (cross-platform) to free the port before binding.
    Works on Linux, macOS, and Windows — no lsof dependency.
    """
    import uvicorn
    from sarthak.web.app import app as web_app

    web_cfg = cfg.get("web", {})
    host = str(web_cfg.get("host", "127.0.0.1"))
    port = int(web_cfg.get("port", 7860))

    # Free port using cross-platform psutil helper
    _free_port_cross_platform(port)
    await asyncio.sleep(0.5)  # brief grace period after SIGTERM

    config = uvicorn.Config(web_app, host=host, port=port, log_level="warning")
    server = uvicorn.Server(config)

    serve_task = asyncio.create_task(server.serve())
    await stop.wait()
    server.should_exit = True
    await serve_task


# ── Service registry ──────────────────────────────────────────────────────────
# (name, runner, enabled_check(cfg) -> bool)

_SERVICES = [
    (
        "web",
        _run_web,
        lambda cfg: cfg.get("web", {}).get("enabled", False),
    ),
    (
        "telegram",
        _run_telegram,
        lambda cfg: cfg.get("telegram", {}).get("enabled", False),
    ),
    (
        "agent_scheduler",
        _run_agent_scheduler,
        lambda cfg: True,
    ),
]

# Services whose crash/exit must NOT stop the entire orchestrator
_ISOLATED_SERVICES = {"telegram"}


# ── Supervisor ────────────────────────────────────────────────────────────────

async def _supervise(cfg: dict[str, Any]) -> None:
    stop = asyncio.Event()
    loop = asyncio.get_running_loop()

    # Windows doesn't support add_signal_handler; use signal.signal instead
    if _IS_WINDOWS:
        import signal as _sig
        for sig in (_sig.SIGTERM, _sig.SIGINT):
            _sig.signal(sig, lambda s, f: stop.set())
    else:
        for sig in (signal.SIGTERM, signal.SIGINT):
            loop.add_signal_handler(sig, lambda s=sig.name: (
                log.info("signal_received", signal=s), stop.set()
            ))

    tasks: dict[asyncio.Task, str] = {}
    for name, runner, enabled_check in _SERVICES:
        if not enabled_check(cfg):
            log.info("service_skipped", service=name, reason="disabled_in_config")
            continue
        t = asyncio.create_task(runner(cfg, stop), name=name)
        tasks[t] = name
        log.info("service_started", service=name)

    if not tasks:
        log.warning("no_services_started")
        return

    while tasks:
        done, _ = await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)
        for t in done:
            name = tasks.pop(t)
            if t.cancelled():
                log.info("service_cancelled", service=name)
            elif exc := t.exception():
                log.error("service_crashed", service=name, error=str(exc))
                if name not in _ISOLATED_SERVICES:
                    stop.set()
                else:
                    log.warning(
                        "isolated_service_crashed",
                        service=name,
                        hint="Orchestrator continues; service crashed but is non-critical.",
                    )
            else:
                log.info("service_stopped", service=name)

    log.info("orchestrator_stopped")


# ── Entry point ───────────────────────────────────────────────────────────────

def main() -> None:
    """Start all enabled Sarthak services. Called by `sarthak orchestrator`."""
    from sarthak.core.config import load_config

    cfg = load_config()
    enable_file_logging(get_orchestration_log_path())
    setup_logging(cfg)
    log.info("orchestrator_starting")
    asyncio.run(_supervise(cfg))


if __name__ == "__main__":
    main()
