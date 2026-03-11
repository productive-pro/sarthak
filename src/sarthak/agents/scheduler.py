"""
Sarthak Agent Engine — scheduler.

Two agent classes managed here:
  - SYSTEM agents: global scope, run on cron, no space context
  - SPACE agents:  scoped to a space directory; get activity context injected

The orchestrator service calls `run_scheduler_loop()` every 60 seconds.
Each due agent fires in a background task. Concurrent duplicate runs are prevented.

Built-in system agents (auto-registered at startup):
  - sarthak-daily-digest       (0 8 * * *)   — daily digest for every registered space
  - sarthak-srs-push           (0 9 * * *)   — push SRS due cards via Telegram
  - sarthak-recommendations    (0 * * * *)   — hourly recommendation refresh per space
  - sarthak-weekly-digest      (0 9 * * 0)   — full week-in-review per space
  - sarthak-workspace-analyse  (*/30 * * * *) — smart workspace re-analysis every 30 min

Performance notes:
  - All per-space work in built-in handlers runs concurrently via asyncio.gather.
  - Heavy I/O (file writes, DB reads) is off-loaded to threads via asyncio.to_thread.
  - Cache invalidation is fire-and-forget (non-blocking).
"""
from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from pathlib import Path

import structlog

from sarthak.agents.models import AgentRun, AgentScope, AgentSpec
from sarthak.agents.store import compute_next_run
from sarthak.core.notify import send_telegram
from sarthak.agents.store import list_agents, load_agent, new_run_id, save_agent, save_run, update_agent

log = structlog.get_logger(__name__)

# Track running tasks to avoid duplicate concurrent runs
_running: set[str] = set()
_spaces_cache: list[tuple[Path, dict]] = []
_spaces_cache_at: float = 0.0
_SPACES_CACHE_TTL = 5.0
_spaces_cache_lock = asyncio.Lock()


# ── Built-in system agents ─────────────────────────────────────────────────────

_BUILTIN_AGENTS: list[dict] = [
    {
        "agent_id":        "sarthak-daily-digest",
        "name":            "Daily Digest",
        "description":     "Builds and sends daily learning digest for all active spaces via Telegram.",
        "prompt":          "Generate and send the daily learning digest for all registered Sarthak spaces. Include SRS reviews due, next recommended concepts, and progress summary.",
        "schedule":        "0 8 * * *",
        "tools":           [],
        "notify_telegram": True,
        "scope":           AgentScope.GLOBAL,
    },
    {
        "agent_id":        "sarthak-srs-push",
        "name":            "SRS Review Push",
        "description":     "Checks all spaces for SRS cards due today and sends a Telegram reminder.",
        "prompt":          "Check all registered Sarthak spaces for spaced repetition cards due today. Send a concise Telegram message listing what needs review.",
        "schedule":        "0 9 * * *",
        "tools":           [],
        "notify_telegram": True,
        "scope":           AgentScope.GLOBAL,
    },
    {
        "agent_id":        "sarthak-recommendations",
        "name":            "Hourly Recommendations",
        "description":     "Runs every hour. Analyzes session signals and updates next-concept recommendations for all active spaces.",
        "prompt":          "Analyze recent session signals and update recommended next concepts for all registered spaces.",
        "schedule":        "0 * * * *",
        "tools":           [],
        "notify_telegram": False,
        "scope":           AgentScope.GLOBAL,
    },
    {
        "agent_id":        "sarthak-weekly-digest",
        "name":            "Weekly Digest",
        "description":     "Every Sunday at 9am: full week-in-review per space via Telegram.",
        "prompt":          "Generate and send the weekly learning review for all registered Sarthak spaces.",
        "schedule":        "0 9 * * 0",
        "tools":           [],
        "notify_telegram": True,
        "scope":           AgentScope.GLOBAL,
    },
    {
        "agent_id":        "sarthak-workspace-analyse",
        "name":            "Workspace Analyser",
        "description":     (
            "Every 30 minutes: re-analyse all spaces and update Optimal_Learn.md + "
            "recommendations.md. Skips a space if nothing has changed since last run "
            "(no new sessions, notes, or file mtime changes). "
            "Also writes a lightweight recommendations.md for fast orchestrator reads."
        ),
        "prompt":          "Analyse all registered spaces and refresh Optimal_Learn.md with current learner signals, recommendations, and workspace state.",
        "schedule":        "*/30 * * * *",
        "tools":           [],
        "notify_telegram": False,
        "scope":           AgentScope.GLOBAL,
    },

]


def ensure_builtin_agents() -> None:
    """Register built-in system agents if they don't already exist."""
    for spec_dict in _BUILTIN_AGENTS:
        if load_agent(spec_dict["agent_id"]):
            continue
        spec = AgentSpec(**spec_dict)
        save_agent(spec)
        log.info("builtin_agent_registered", agent_id=spec.agent_id)


# ── Scheduler tick ─────────────────────────────────────────────────────────────

async def tick() -> list[str]:
    """Check all enabled agents and fire any that are due. Returns triggered agent IDs."""
    now = datetime.now(timezone.utc)
    triggered: list[str] = []

    for spec in list_agents():
        if not spec.enabled or spec.agent_id in _running or not _is_due(spec, now):
            continue

        triggered.append(spec.agent_id)
        _running.add(spec.agent_id)

        async def _run_and_cleanup(s: AgentSpec) -> None:
            try:
                await _run_agent_with_context(s)
            finally:
                _running.discard(s.agent_id)

        asyncio.create_task(_run_and_cleanup(spec))
        log.info("agent_scheduled_run", agent_id=spec.agent_id, scope=spec.scope)

    return triggered


def _is_due(spec: AgentSpec, now: datetime) -> bool:
    """
    Returns True if this agent should fire now.

    Primary: use next_run_at (set after each run by compute_next_run).
    Fallback: croniter.match for agents that have never run.
    This avoids the 60s tick-drift problem where croniter.match misses the
    exact minute when the scheduler fires 1-2s late.
    """
    if not spec.schedule:
        return False
    if spec.next_run_at:
        try:
            next_dt = datetime.fromisoformat(spec.next_run_at)
            if next_dt.tzinfo is None:
                next_dt = next_dt.replace(tzinfo=timezone.utc)
            return now >= next_dt
        except Exception:
            pass
    # No next_run_at yet (first ever run) — fall back to cron match
    try:
        from croniter import croniter
        return croniter.match(spec.schedule, now)
    except Exception:
        return False


# ── Activity-aware agent execution ─────────────────────────────────────────────

async def _run_agent_with_context(spec: AgentSpec) -> None:
    handlers = {
        "sarthak-daily-digest":      _run_digest_agent,
        "sarthak-srs-push":          _run_srs_push_agent,
        "sarthak-recommendations":   _run_recommendations_agent,
        "sarthak-weekly-digest":     _run_weekly_digest_agent,
        "sarthak-workspace-analyse": _run_workspace_analyse_agent,
    }
    handler = handlers.get(spec.agent_id)
    if handler:
        await handler(spec)
        return
    from sarthak.agents.runner import run_agent
    await run_agent(spec)


# ── Shared helpers ─────────────────────────────────────────────────────────────

async def _finish_run(spec: AgentSpec, run: AgentRun, output: str, success: bool = True) -> None:
    run.output = output
    run.success = success
    run.finished_at = datetime.now(timezone.utc).isoformat()
    save_run(spec, run)
    now_iso = datetime.now(timezone.utc).isoformat()
    update_agent(spec.agent_id, last_run_at=now_iso, next_run_at=compute_next_run(spec.schedule))


async def _get_telegram_cfg() -> dict:
    from sarthak.core.config import load_config
    return load_config()


def _valid_spaces() -> list[tuple[Path, dict]]:
    """Return (space_dir, space_info) for all registered spaces that exist on disk."""
    from sarthak.spaces.store import list_spaces
    global _spaces_cache, _spaces_cache_at
    now = datetime.now(timezone.utc).timestamp()
    if _spaces_cache and (now - _spaces_cache_at) < _SPACES_CACHE_TTL:
        return list(_spaces_cache)
    result: list[tuple[Path, dict]] = []
    for info in list_spaces():
        sd = Path(info.get("directory", ""))
        if sd.exists():
            result.append((sd, info))
    _spaces_cache = result
    _spaces_cache_at = now
    return result


async def _run_per_space(
    spaces: list[tuple[Path, dict]],
    worker,
) -> list:
    """Run a per-space worker concurrently and filter falsy results."""
    results = await asyncio.gather(*[worker(sd, info) for sd, info in spaces])
    return [r for r in results if r]


# ── Built-in handlers ──────────────────────────────────────────────────────────

async def _run_digest_agent(spec: AgentSpec) -> None:
    """Send daily digest for every registered space via Telegram — all spaces in parallel."""
    from sarthak.agents.roadmap_agents import build_digest

    run = AgentRun(run_id=new_run_id(), agent_id=spec.agent_id)
    cfg = await _get_telegram_cfg()
    spaces = _valid_spaces()

    async def _do_one(sd: Path, info: dict) -> str | None:
        try:
            digest = await build_digest(sd, info.get("name", sd.name))
            if spec.notify_telegram:
                await send_telegram(cfg, digest, agent_id=spec.agent_id)
            return f"=== {info.get('name', sd.name)} ===\n{digest}"
        except Exception as exc:
            log.warning("digest_failed", space=str(sd), error=str(exc))
            return None

    outputs = await _run_per_space(spaces, _do_one)
    output = "\n\n".join(outputs) if outputs else "No spaces to digest."
    await _finish_run(spec, run, output, success=bool(outputs))
    log.info("digest_agent_done", spaces=len(outputs))


async def _run_srs_push_agent(spec: AgentSpec) -> None:
    """Push SRS due cards for all spaces via Telegram — all spaces in parallel."""
    from datetime import date
    from sarthak.spaces.roadmap.srs import get_due

    run = AgentRun(run_id=new_run_id(), agent_id=spec.agent_id)
    cfg = await _get_telegram_cfg()
    spaces = _valid_spaces()

    async def _do_one(sd: Path, info: dict) -> tuple[str, int] | None:
        try:
            db_path = str(sd / ".spaces" / "sarthak.db")
            due_cards = await get_due(db_path)
            if not due_cards:
                return None
            name = info.get("name", sd.name)
            card_lines = [f"{name}: {len(due_cards)} card(s) due"]
            for card in due_cards[:6]:
                label = card.concept or card.card_id
                reason = f" ({card.reason})" if card.reason else ""
                try:
                    overdue_days = (date.today() - date.fromisoformat(card.next_due)).days
                    overdue_str = f" [{overdue_days}d overdue]" if overdue_days > 0 else ""
                except Exception:
                    overdue_str = ""
                card_lines.append(f"  - {label}{reason}{overdue_str}")
            if len(due_cards) > 6:
                card_lines.append(f"  ... and {len(due_cards) - 6} more")
            return "\n".join(card_lines), len(due_cards)
        except Exception as exc:
            log.warning("srs_push_failed", space=str(sd), error=str(exc))
            return None

    results = await _run_per_space(spaces, _do_one)
    sections = ["SRS Review Due Today"]
    total_due = 0
    for r in results:
        if r:
            text, cnt = r
            sections.append(text)
            total_due += cnt

    if total_due == 0:
        output = "No SRS cards due today."
    else:
        output = "\n\n".join(sections)
        if spec.notify_telegram:
            await send_telegram(cfg, output, agent_id=spec.agent_id)

    await _finish_run(spec, run, output, success=True)
    log.info("srs_push_done", total_due=total_due)


async def _run_recommendations_agent(spec: AgentSpec) -> None:
    """
    Refresh Optimal_Learn.md for all spaces in parallel.

    Improvements:
    - Passes real LearnerContext (weak/strong/SRS due) into WorkspaceAnalyserAgent.
    - Also writes a plain-text recommendations summary to .spaces/recommendations.md
      so the orchestrator can load them without re-parsing Optimal_Learn.md.
    """
    from sarthak.spaces.models import SpaceContext
    from sarthak.spaces.store import load_profile
    from sarthak.spaces.agents import WorkspaceAnalyserAgent, detect_platform

    run = AgentRun(run_id=new_run_id(), agent_id=spec.agent_id)
    analyser = WorkspaceAnalyserAgent()
    spaces = _valid_spaces()

    async def _do_one(sd: Path, info: dict) -> str | None:
        try:
            profile = await asyncio.to_thread(load_profile, sd)
            if not profile:
                return None
            ctx = SpaceContext(
                workspace_dir=str(sd),
                profile=profile,
                platform=detect_platform(),
            )
            # Full Optimal_Learn.md — includes LearnerContext + recommendations
            content = await analyser.analyse(ctx)
            await asyncio.to_thread(analyser.write_optimal_learn, sd, content)

            # Also write lightweight recommendations.md for fast orchestrator reads
            await asyncio.to_thread(_write_recommendations_summary, sd, profile)

            return info.get("name", sd.name)
        except Exception as exc:
            log.warning("recommendations_refresh_failed", space=str(sd), error=str(exc))
            return None

    updated = await _run_per_space(spaces, _do_one)
    output = f"Updated recommendations for: {', '.join(updated)}" if updated else "No spaces updated."
    await _finish_run(spec, run, output, success=True)
    log.info("recommendations_done", spaces=len(updated))


def _write_recommendations_summary(space_dir: Path, profile) -> None:
    """
    Write a fast-load recommendations.md with the top 3 next concepts + reasons.
    Uses recommend_with_reasons() — pure derived data, no LLM.
    """
    try:
        from sarthak.spaces.roadmap.db import RoadmapDB
        from sarthak.spaces.roadmap.recommend import recommend_with_reasons
        import asyncio as _asyncio

        async def _load():
            db = RoadmapDB(space_dir)
            await db.init()
            return await db.load_roadmap()

        try:
            # We're running in asyncio.to_thread, so there's no running event loop here.
            # Create a fresh loop for this blocking call.
            roadmap = _asyncio.run(_load())
        except RuntimeError:
            roadmap = None

        if not roadmap:
            return

        lp = profile.learner
        recs = recommend_with_reasons(
            roadmap,
            top_k=3,
            mastered=lp.mastered_concepts,
            struggling=lp.struggling_concepts,
            review_due=[],
        )
        if not recs:
            return

        lines = ["# Next Recommendations\n"]
        for i, (concept, reason) in enumerate(recs, 1):
            lines.append(f"{i}. **{concept.title}** — {reason}")

        out = space_dir / ".spaces" / "recommendations.md"
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text("\n".join(lines), encoding="utf-8")
    except Exception as exc:
        log.debug("recommendations_summary_failed", error=str(exc))


async def _run_weekly_digest_agent(spec: AgentSpec) -> None:
    """Build week-in-review per space in parallel."""
    from datetime import date
    from sarthak.agents.roadmap_agents import build_digest
    from sarthak.storage.activity_store import activity_summary, concepts_touched
    from sarthak.spaces.agents import EngagementAgent
    from sarthak.spaces.store import load_profile

    run = AgentRun(run_id=new_run_id(), agent_id=spec.agent_id)
    cfg = await _get_telegram_cfg()
    engagement = EngagementAgent()
    spaces = _valid_spaces()

    async def _do_one(sd: Path, info: dict) -> str | None:
        try:
            name = info.get("name", sd.name)
            base_digest, act, touched, profile = await asyncio.gather(
                build_digest(sd, name),
                activity_summary(str(sd), days=7),
                concepts_touched(str(sd), days=7),
                asyncio.to_thread(load_profile, sd),
            )
            enrich_lines = [f"\n## Week in Review — {date.today().strftime('%B %d, %Y')}"]
            if act:
                enrich_lines.append("\n**Activity breakdown:**")
                for atype, cnt in sorted(act.items(), key=lambda x: -x[1]):
                    enrich_lines.append(f"- {atype.replace('_', ' ').title()}: {cnt}")
            if touched:
                enrich_lines.append(f"\n**Concepts touched this week:** {', '.join(touched[:8])}")
            combined = base_digest + "\n".join(enrich_lines)
            if profile and profile.learner.background:
                combined = await engagement.render(
                    content={"weekly_digest": combined},
                    learner_background=profile.learner.background,
                    xp_earned=0,
                    is_technical=profile.learner.is_technical,
                )
            if spec.notify_telegram:
                await send_telegram(cfg, combined, agent_id=spec.agent_id)
            return f"=== {name} ===\n{combined}"
        except Exception as exc:
            log.warning("weekly_digest_failed", space=str(sd), error=str(exc))
            return None

    outputs = await _run_per_space(spaces, _do_one)
    output = "\n\n".join(outputs) if outputs else "No spaces to review."
    await _finish_run(spec, run, output, success=bool(outputs))
    log.info("weekly_digest_done", spaces=len(outputs))


async def _run_workspace_analyse_agent(spec: AgentSpec) -> None:
    """
    Every 30 minutes: re-analyse all spaces and update Optimal_Learn.md.

    Smart skip: each space is only re-analysed if something has actually changed
    since the last Optimal_Learn.md was written (new session, new note, or any
    file mtime change in the workspace). This avoids unnecessary LLM calls.
    """
    from sarthak.spaces.models import SpaceContext
    from sarthak.spaces.store import load_profile
    from sarthak.spaces.agents import WorkspaceAnalyserAgent, detect_platform

    run = AgentRun(run_id=new_run_id(), agent_id=spec.agent_id)
    analyser = WorkspaceAnalyserAgent()
    spaces = _valid_spaces()

    async def _do_one(sd: Path, info: dict) -> str | None:
        try:
            profile = await asyncio.to_thread(load_profile, sd)
            if not profile:
                return None

            # ── Smart skip: only re-run if workspace has changed ───────────────
            if not _workspace_changed_since_last_analyse(sd):
                log.debug("workspace_analyse_skipped_no_change", space=str(sd))
                return None

            ctx = SpaceContext(
                workspace_dir=str(sd),
                profile=profile,
                platform=detect_platform(),
            )
            content = await analyser.analyse(ctx)
            await asyncio.to_thread(analyser.write_optimal_learn, sd, content)

            # Also write fast-load recommendations.md
            await asyncio.to_thread(_write_recommendations_summary, sd, profile)

            log.info("workspace_analyse_done", space=info.get("name", sd.name))
            return info.get("name", sd.name)
        except Exception as exc:
            log.warning("workspace_analyse_failed", space=str(sd), error=str(exc))
            return None

    updated = await _run_per_space(spaces, _do_one)
    output = f"Analysed: {', '.join(updated)}" if updated else "No spaces needed re-analysis."
    await _finish_run(spec, run, output, success=True)
    log.info("workspace_analyse_agent_done", updated=len(updated), total=len(spaces))


def _workspace_changed_since_last_analyse(space_dir: Path) -> bool:
    """
    Returns True if the workspace needs a fresh Optimal_Learn.md.

    Checks:
    1. Optimal_Learn.md doesn't exist yet.
    2. Any .spaces file (sessions.jsonl, notes_index.jsonl, sarthak.db)
       is newer than the last Optimal_Learn.md write.
    3. Any workspace file mtime in the top-level dirs is newer.

    This is purely file-stat — no DB, no LLM, no I/O beyond stat() calls.
    """
    import os
    optimal = space_dir / ".spaces" / "Optimal_Learn.md"
    if not optimal.exists():
        return True

    last_analyse = optimal.stat().st_mtime

    # Check .spaces signal files
    signal_files = [
        space_dir / ".spaces" / "sessions.jsonl",
        space_dir / ".spaces" / "notes_index.jsonl",
        space_dir / ".spaces" / "sarthak.db",
        space_dir / ".spaces" / "USER.md",
    ]
    for f in signal_files:
        if f.exists() and f.stat().st_mtime > last_analyse:
            return True

    # Check top-level workspace dirs (depth-1 only — fast)
    try:
        for entry in os.scandir(space_dir):
            if entry.name.startswith("."):
                continue
            if entry.stat().st_mtime > last_analyse:
                return True
    except Exception:
        pass

    return False


# ── Main loop ──────────────────────────────────────────────────────────────────

async def run_scheduler_loop(interval_seconds: int = 60) -> None:
    """Long-running loop — called from orchestrator service."""
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
