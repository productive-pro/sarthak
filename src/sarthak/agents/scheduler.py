"""
Sarthak Agent Engine — scheduler.

run_scheduler_loop(interval=60) is called by the orchestrator service every 60s.
Due agents fire as background asyncio.Tasks; duplicate concurrent runs are prevented.

Built-in agents are declared in data/agents/builtin.toml (no hardcoded Python dicts).
Handler functions are registered via @register_handler("agent-id") decorator.
Adding a new built-in: add [[agent]] to builtin.toml + @register_handler function here.

Built-in agents:
  sarthak-daily-digest       0 8 * * *    daily digest → Telegram
  sarthak-srs-push           0 9 * * *    SRS due cards → Telegram
  sarthak-recommendations    0 * * * *    hourly next-concept refresh
  sarthak-weekly-digest      0 9 * * 0    week-in-review → Telegram
  sarthak-workspace-analyse  */30 * * * * smart workspace re-analysis
"""
from __future__ import annotations

import asyncio
from collections.abc import Callable, Awaitable
from datetime import datetime, timezone
from pathlib import Path

import structlog

from sarthak.agents.models import AgentRun, AgentScope, AgentSpec
from sarthak.agents.store import (
    compute_next_run, list_agents, load_agent,
    new_run_id, save_agent, save_run, update_agent,
)
from sarthak.core.notify import send_telegram

log = structlog.get_logger(__name__)

# ── State ─────────────────────────────────────────────────────────────────────
_running: set[str] = set()
_tasks:   set[asyncio.Task] = set()  # strong refs prevent premature GC

_active_cache: list[tuple[Path, dict]] = []
_active_cache_at: float = 0.0
_ACTIVE_TTL = 2.0

# Handler registry: agent_id → async handler fn
_HANDLERS: dict[str, Callable[[AgentSpec], Awaitable[None]]] = {}


def register_handler(agent_id: str):
    """Decorator: register an async handler for a built-in agent id."""
    def _dec(fn: Callable[[AgentSpec], Awaitable[None]]):
        _HANDLERS[agent_id] = fn
        return fn
    return _dec


# ── Built-in agent registration from TOML ────────────────────────────────────

def ensure_builtin_agents() -> None:
    """
    Register built-in agents declared in data/agents/builtin.toml.
    Idempotent — skips agents already persisted to disk.
    Falls back to empty list on any parse error (logged).
    """
    from sarthak.data.loader import load_builtin_agent_specs
    specs = load_builtin_agent_specs()
    if not specs:
        log.warning("no_builtin_specs_loaded", hint="Check data/agents/builtin.toml")
        return
    for spec_dict in specs:
        agent_id = spec_dict.get("agent_id", "")
        if not agent_id:
            continue
        if load_agent(agent_id):
            continue
        # Strip non-AgentSpec keys before constructing
        safe = {k: v for k, v in spec_dict.items()
                if k in AgentSpec.model_fields and k != "handler"}
        try:
            save_agent(AgentSpec(**safe))
            log.info("builtin_agent_registered", agent_id=agent_id)
        except Exception as exc:
            log.warning("builtin_agent_register_failed", agent_id=agent_id, error=str(exc))


# ── Tick ──────────────────────────────────────────────────────────────────────

async def tick() -> list[str]:
    now = datetime.now(timezone.utc)
    active_dirs = {str(Path(sd).resolve()) for sd, _ in _active_spaces()}
    triggered: list[str] = []

    for spec in list_agents():
        if not spec.enabled or spec.agent_id in _running or not _is_due(spec, now):
            continue
        if spec.scope == AgentScope.SPACE:
            if not spec.space_dir:
                continue
            try:
                if str(Path(spec.space_dir).resolve()) not in active_dirs:
                    continue
            except Exception:
                continue

        triggered.append(spec.agent_id)
        _running.add(spec.agent_id)

        async def _run(s: AgentSpec) -> None:
            try:
                await _dispatch(s)
            except Exception as exc:
                log.error("agent_task_failed", agent_id=s.agent_id, error=str(exc))
            finally:
                _running.discard(s.agent_id)

        task = asyncio.create_task(_run(spec))
        _tasks.add(task)
        task.add_done_callback(_tasks.discard)
        log.info("agent_scheduled", agent_id=spec.agent_id)

    return triggered


def _is_due(spec: AgentSpec, now: datetime) -> bool:
    if not spec.schedule:
        return False
    if spec.next_run_at:
        try:
            nxt = datetime.fromisoformat(spec.next_run_at)
            if nxt.tzinfo is None:
                nxt = nxt.replace(tzinfo=timezone.utc)
            return now >= nxt
        except Exception:
            pass
    try:
        from croniter import croniter
        return croniter.match(spec.schedule, now)
    except Exception:
        return False


async def _dispatch(spec: AgentSpec) -> None:
    handler = _HANDLERS.get(spec.agent_id)
    if handler:
        await handler(spec)
    else:
        from sarthak.agents.runner import run_agent
        await run_agent(spec)


# ── Shared helpers ─────────────────────────────────────────────────────────────

async def _finish_run(spec: AgentSpec, run: AgentRun, output: str, success: bool = True) -> None:
    run.output, run.success = output, success
    run.finished_at = datetime.now(timezone.utc).isoformat()
    save_run(spec, run)
    now_iso = datetime.now(timezone.utc).isoformat()
    update_agent(spec.agent_id, last_run_at=now_iso, next_run_at=compute_next_run(spec.schedule))


def _active_spaces() -> list[tuple[Path, dict]]:
    from sarthak.spaces.store import get_active_space, load_space
    global _active_cache, _active_cache_at
    import time as _time
    now = _time.monotonic()
    if _active_cache and (now - _active_cache_at) < _ACTIVE_TTL:
        return list(_active_cache)
    result: list[tuple[Path, dict]] = []
    active = get_active_space()
    if active and (d := active.get("directory")):
        sd = Path(d)
        if sd.exists():
            cfg = load_space(sd) or {}
            result = [(sd, {
                "name": active.get("name") or cfg.get("name", sd.name),
                "directory": str(sd),
                "goal": cfg.get("goal", ""),
                "space_type": (cfg.get("__profile__") or {}).get("space_type", ""),
                "domain": (cfg.get("__profile__") or {}).get("domain", ""),
            })]
    _active_cache, _active_cache_at = result, now
    return result


def invalidate_active_space_cache() -> None:
    global _active_cache, _active_cache_at
    _active_cache, _active_cache_at = [], 0.0


async def _run_per_space(spaces: list[tuple[Path, dict]], worker) -> list:
    results = await asyncio.gather(*[worker(sd, info) for sd, info in spaces])
    return [r for r in results if r]


# ── Built-in handlers (registered via @register_handler) ──────────────────────

@register_handler("sarthak-daily-digest")
async def _run_digest_agent(spec: AgentSpec) -> None:
    from sarthak.agents.roadmap_agents import build_digest
    from sarthak.core.config import load_config
    run = AgentRun(run_id=new_run_id(), agent_id=spec.agent_id)
    cfg = load_config()

    async def _do(sd: Path, info: dict) -> str | None:
        try:
            digest = await build_digest(sd, info.get("name", sd.name))
            if spec.notify_telegram:
                await send_telegram(cfg, digest, agent_id=spec.agent_id)
            return f"=== {info.get('name', sd.name)} ===\n{digest}"
        except Exception as exc:
            log.warning("digest_failed", space=str(sd), error=str(exc))
            return None

    outputs = await _run_per_space(_active_spaces(), _do)
    await _finish_run(spec, run, "\n\n".join(outputs) or "No spaces.", success=bool(outputs))


@register_handler("sarthak-srs-push")
async def _run_srs_push_agent(spec: AgentSpec) -> None:
    from datetime import date
    from sarthak.spaces.roadmap.srs import get_due
    from sarthak.core.config import load_config
    run = AgentRun(run_id=new_run_id(), agent_id=spec.agent_id)
    cfg = load_config()

    async def _do(sd: Path, info: dict) -> tuple[str, int] | None:
        try:
            due = await get_due(str(sd / ".spaces" / "sarthak.db"))
            if not due:
                return None
            name  = info.get("name", sd.name)
            lines = [f"{name}: {len(due)} card(s) due"]
            for c in due[:6]:
                try:
                    od = (date.today() - date.fromisoformat(c.next_due)).days
                    overdue_str = f" [{od}d overdue]" if od > 0 else ""
                except Exception:
                    overdue_str = ""
                lines.append(f"  - {c.concept or c.card_id}{overdue_str}")
            if len(due) > 6:
                lines.append(f"  ... and {len(due) - 6} more")
            return "\n".join(lines), len(due)
        except Exception as exc:
            log.warning("srs_push_failed", space=str(sd), error=str(exc))
            return None

    results = await _run_per_space(_active_spaces(), _do)
    total   = sum(r[1] for r in results if r)
    if total == 0:
        output = "No SRS cards due today."
    else:
        output = "SRS Review Due Today\n\n" + "\n\n".join(r[0] for r in results if r)
        if spec.notify_telegram:
            await send_telegram(cfg, output, agent_id=spec.agent_id)
    await _finish_run(spec, run, output)


@register_handler("sarthak-recommendations")
async def _run_recommendations_agent(spec: AgentSpec) -> None:
    from sarthak.spaces.models import SpaceContext
    from sarthak.spaces.store import load_profile
    from sarthak.spaces.agents import WorkspaceAnalyserAgent, detect_platform
    run      = AgentRun(run_id=new_run_id(), agent_id=spec.agent_id)
    analyser = WorkspaceAnalyserAgent()

    async def _do(sd: Path, info: dict) -> str | None:
        try:
            profile = await asyncio.to_thread(load_profile, sd)
            if not profile:
                return None
            ctx = SpaceContext(workspace_dir=str(sd), profile=profile, platform=detect_platform())
            content = await analyser.analyse(ctx)
            await asyncio.to_thread(analyser.write_optimal_learn, sd, content)
            await asyncio.to_thread(_write_recommendations_summary, sd, profile)
            return info.get("name", sd.name)
        except Exception as exc:
            log.warning("recommendations_refresh_failed", space=str(sd), error=str(exc))
            return None

    updated = await _run_per_space(_active_spaces(), _do)
    await _finish_run(spec, run, f"Updated: {', '.join(updated)}" if updated else "No spaces updated.")


@register_handler("sarthak-weekly-digest")
async def _run_weekly_digest_agent(spec: AgentSpec) -> None:
    from datetime import date
    from sarthak.agents.roadmap_agents import build_digest
    from sarthak.storage.activity_store import activity_summary, concepts_touched
    from sarthak.spaces.agents import EngagementAgent
    from sarthak.spaces.store import load_profile
    from sarthak.core.config import load_config
    run        = AgentRun(run_id=new_run_id(), agent_id=spec.agent_id)
    cfg        = load_config()
    engagement = EngagementAgent()

    async def _do(sd: Path, info: dict) -> str | None:
        try:
            name = info.get("name", sd.name)
            base_digest, act, touched, profile = await asyncio.gather(
                build_digest(sd, name),
                activity_summary(str(sd), days=7),
                concepts_touched(str(sd), days=7),
                asyncio.to_thread(load_profile, sd),
            )
            enrich = [f"\n## Week in Review — {date.today().strftime('%B %d, %Y')}"]
            if act:
                enrich.append("\n**Activity:**")
                for atype, cnt in sorted(act.items(), key=lambda x: -x[1]):
                    enrich.append(f"- {atype.replace('_', ' ').title()}: {cnt}")
            if touched:
                enrich.append(f"\n**Concepts:** {', '.join(touched[:8])}")
            combined = base_digest + "\n".join(enrich)
            if profile and profile.learner.background:
                combined = await engagement.render(
                    {"weekly_digest": combined}, profile.learner.background,
                    0, is_technical=profile.learner.is_technical,
                )
            if spec.notify_telegram:
                await send_telegram(cfg, combined, agent_id=spec.agent_id)
            return f"=== {name} ===\n{combined}"
        except Exception as exc:
            log.warning("weekly_digest_failed", space=str(sd), error=str(exc))
            return None

    outputs = await _run_per_space(_active_spaces(), _do)
    await _finish_run(spec, run, "\n\n".join(outputs) or "No spaces.", success=bool(outputs))


@register_handler("sarthak-workspace-analyse")
async def _run_workspace_analyse_agent(spec: AgentSpec) -> None:
    from sarthak.spaces.models import SpaceContext
    from sarthak.spaces.store import load_profile
    from sarthak.spaces.agents import WorkspaceAnalyserAgent, detect_platform
    run      = AgentRun(run_id=new_run_id(), agent_id=spec.agent_id)
    analyser = WorkspaceAnalyserAgent()

    async def _do(sd: Path, info: dict) -> str | None:
        if not _workspace_changed(sd):
            return None
        try:
            profile = await asyncio.to_thread(load_profile, sd)
            if not profile:
                return None
            ctx = SpaceContext(workspace_dir=str(sd), profile=profile, platform=detect_platform())
            content = await analyser.analyse(ctx)
            await asyncio.to_thread(analyser.write_optimal_learn, sd, content)
            await asyncio.to_thread(_write_recommendations_summary, sd, profile)
            return info.get("name", sd.name)
        except Exception as exc:
            log.warning("workspace_analyse_failed", space=str(sd), error=str(exc))
            return None

    updated = await _run_per_space(_active_spaces(), _do)
    await _finish_run(spec, run, f"Analysed: {', '.join(updated)}" if updated else "No changes.")


# ── Pure sync helpers (safe for asyncio.to_thread) ────────────────────────────

def _workspace_changed(space_dir: Path) -> bool:
    """True if any signal file is newer than Optimal_Learn.md (stat-only)."""
    import os
    optimal = space_dir / ".spaces" / "Optimal_Learn.md"
    if not optimal.exists():
        return True
    t = optimal.stat().st_mtime
    for sig in [
        space_dir / ".spaces" / "sessions.jsonl",
        space_dir / ".spaces" / "notes_index.jsonl",
        space_dir / ".spaces" / "sarthak.db",
        space_dir / ".spaces" / "USER.md",
    ]:
        if sig.exists() and sig.stat().st_mtime > t:
            return True
    try:
        for entry in os.scandir(space_dir):
            if not entry.name.startswith(".") and entry.stat().st_mtime > t:
                return True
    except Exception:
        pass
    return False


def _load_roadmap_sync(space_dir: Path):
    """
    Load roadmap using stdlib sqlite3 — safe for asyncio.to_thread.
    No asyncio.Lock, no aiosqlite pool, opens/closes within this call.
    """
    import sqlite3
    from sarthak.spaces.roadmap.models import Roadmap
    db_path = space_dir / ".spaces" / "sarthak.db"
    if not db_path.exists():
        return None
    try:
        with sqlite3.connect(str(db_path), timeout=5, check_same_thread=False) as conn:
            conn.execute("PRAGMA journal_mode=WAL")
            conn.execute("PRAGMA synchronous=NORMAL")
            row = conn.execute("SELECT blob FROM roadmap WHERE id=1").fetchone()
        if not row:
            return None
        return Roadmap.model_validate_json(row[0]).sorted_by_order()
    except Exception as exc:
        log.debug("roadmap_sync_load_failed", space=str(space_dir), error=str(exc))
        return None


def _write_recommendations_summary(space_dir: Path, profile) -> None:
    """
    Write recommendations.md — top-3 next concepts, no LLM.
    Safe for asyncio.to_thread (stdlib sqlite3 only).
    """
    try:
        from sarthak.spaces.roadmap.recommend import recommend_with_reasons
        roadmap = _load_roadmap_sync(space_dir)
        if not roadmap:
            return
        lp   = profile.learner
        recs = recommend_with_reasons(
            roadmap, top_k=3,
            mastered=lp.mastered_concepts,
            struggling=lp.struggling_concepts,
            review_due=[],
        )
        if not recs:
            return
        lines = ["# Next Recommendations\n"]
        lines.extend(f"{i}. **{c.title}** — {r}" for i, (c, r) in enumerate(recs, 1))
        out = space_dir / ".spaces" / "recommendations.md"
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text("\n".join(lines), encoding="utf-8")
    except Exception as exc:
        log.debug("recommendations_summary_failed", error=str(exc))


# ── Main loop ──────────────────────────────────────────────────────────────────

async def run_scheduler_loop(interval_seconds: int = 60) -> None:
    ensure_builtin_agents()
    log.info("agent_scheduler_started", interval=interval_seconds)
    while True:
        try:
            triggered = await tick()
            if triggered:
                log.info("agents_triggered", count=len(triggered), ids=triggered)
        except Exception as exc:
            log.error("scheduler_tick_error", error=str(exc))
        await asyncio.sleep(interval_seconds)
