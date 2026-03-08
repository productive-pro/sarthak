"""
Sarthak Agent Engine — scheduler.

Two agent classes managed here:
  - SYSTEM agents: global scope, run on cron, no space context
  - SPACE agents:  scoped to a space directory; get AW activity context injected

The orchestrator service calls `run_scheduler_loop()` every 60 seconds.
Each due agent fires in a background task. Concurrent duplicate runs are prevented.

Built-in system agents (auto-registered at startup):
  - sarthak-daily-digest  (0 8 * * *)  — digest for every registered space
  - sarthak-srs-push      (0 9 * * *)  — push SRS due cards via Telegram
  - sarthak-recommendations (0 * * * *) — hourly recommendation refresh per space
"""
from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from pathlib import Path

import structlog

from sarthak.agents.models import AgentRun, AgentScope, AgentSpec
from sarthak.agents.runner import compute_next_run, send_telegram
from sarthak.agents.store import list_agents, load_agent, new_run_id, save_agent, save_run, update_agent

log = structlog.get_logger(__name__)

# Track running tasks to avoid duplicate concurrent runs
_running: set[str] = set()


# ── Built-in system agents ────────────────────────────────────────────────────

_BUILTIN_AGENTS: list[dict] = [
    {
        "agent_id":        "sarthak-daily-digest",
        "name":            "Daily Digest",
        "description":     "Builds and sends daily learning digest for all active spaces via Telegram.",
        "prompt":          "Generate and send the daily learning digest for all registered Sarthak spaces. Include SRS reviews due, next recommended concepts (based on recent activity), and progress summary.",
        "schedule":        "0 8 * * *",
        "tools":           [],
        "notify_telegram": True,
        "scope":           AgentScope.GLOBAL,
    },
    {
        "agent_id":        "sarthak-srs-push",
        "name":            "SRS Review Push",
        "description":     "Checks all spaces for SRS cards due today and sends a Telegram reminder.",
        "prompt":          "Check all registered Sarthak spaces for spaced repetition cards due today. Send a concise Telegram message listing what needs review. Be specific: include concept names and the space they belong to.",
        "schedule":        "0 9 * * *",
        "tools":           [],
        "notify_telegram": True,
        "scope":           AgentScope.GLOBAL,
    },
    {
        "agent_id":        "sarthak-recommendations",
        "name":            "Hourly Recommendations",
        "description":     "Runs every hour. Analyzes Spaces session signals and updates next-concept recommendations for all active spaces.",
        "prompt":          "Analyze recent session signals (focus ratio, depth score, self-reports) and update the recommended next concepts for all registered spaces. Focus on adapting recommendations based on struggling concepts and session quality.",
        "schedule":        "0 * * * *",
        "tools":           [],
        "notify_telegram": False,
        "scope":           AgentScope.GLOBAL,
    },
    {
        "agent_id":        "sarthak-weekly-digest",
        "name":            "Weekly Digest",
        "description":     "Every Sunday at 9am: builds a week-in-review digest per space using all activity data (notes, audio, code, tests) and sends via Telegram.",
        "prompt":          "Generate and send the weekly learning review for all registered Sarthak spaces. Include total sessions, concepts mastered, spaced repetition performance, audio/video notes, code playground runs, test scores, and a personalised next-week focus using the EngagementAgent.",
        "schedule":        "0 9 * * 0",
        "tools":           [],
        "notify_telegram": True,
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


# ── Scheduler tick ────────────────────────────────────────────────────────────

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
    """Return True if the agent should run now according to its cron schedule."""
    if not spec.schedule:
        return False
    if spec.next_run_at:
        try:
            next_dt = datetime.fromisoformat(spec.next_run_at)
            if next_dt.tzinfo is None:
                next_dt = next_dt.replace(tzinfo=timezone.utc)
            if now < next_dt:
                return False
        except Exception:
            pass
    from croniter import croniter
    return croniter.match(spec.schedule, now)


# ── Activity-aware agent execution ───────────────────────────────────────────

async def _run_agent_with_context(spec: AgentSpec) -> None:
    """Route to special handlers for built-ins; run generic agents directly."""
    from sarthak.agents.runner import run_agent

    handlers = {
        "sarthak-daily-digest":    _run_digest_agent,
        "sarthak-srs-push":        _run_srs_push_agent,
        "sarthak-recommendations": _run_recommendations_agent,
        "sarthak-weekly-digest":   _run_weekly_digest_agent,
    }
    handler = handlers.get(spec.agent_id)
    if handler:
        await handler(spec)
        return

    await run_agent(spec)


# ── Built-in agent handlers ───────────────────────────────────────────────────

async def _finish_run(
    spec: AgentSpec,
    run: AgentRun,
    output: str,
    success: bool = True,
) -> None:
    """Persist a finished run and update next-run timestamps. Shared by all built-ins."""
    run.output = output
    run.success = success
    run.finished_at = datetime.now(timezone.utc).isoformat()
    save_run(spec, run)
    now_iso = datetime.now(timezone.utc).isoformat()
    update_agent(spec.agent_id, last_run_at=now_iso, next_run_at=compute_next_run(spec.schedule))


async def _get_telegram_cfg() -> dict:
    from sarthak.core.config import load_config
    return load_config()


async def _run_digest_agent(spec: AgentSpec) -> None:
    """Send daily digest for every registered space via Telegram."""
    from sarthak.spaces.store import list_spaces
    from sarthak.agents.roadmap_agents import build_digest

    run = AgentRun(run_id=new_run_id(), agent_id=spec.agent_id)
    outputs: list[str] = []
    cfg = await _get_telegram_cfg()

    for space_info in list_spaces():
        space_dir = Path(space_info.get("directory", ""))
        if not space_dir.exists():
            continue
        try:
            digest = await build_digest(space_dir, space_info.get("name", space_dir.name))
            outputs.append(f"=== {space_info.get('name', space_dir.name)} ===\n{digest}")
            if spec.notify_telegram:
                await send_telegram(cfg, digest, agent_id=spec.agent_id)
        except Exception as exc:
            log.warning("digest_failed", space=str(space_dir), error=str(exc))

    output = "\n\n".join(outputs) if outputs else "No spaces to digest."
    await _finish_run(spec, run, output, success=bool(outputs))
    log.info("digest_agent_done", spaces=len(outputs))


async def _run_srs_push_agent(spec: AgentSpec) -> None:
    """Push SRS due cards for all spaces via Telegram with per-card context."""
    from datetime import date
    from sarthak.spaces.store import list_spaces
    from sarthak.spaces.roadmap.srs import get_due

    run = AgentRun(run_id=new_run_id(), agent_id=spec.agent_id)
    sections: list[str] = ["SRS Review Due Today"]
    total_due = 0
    cfg = await _get_telegram_cfg()

    for space_info in list_spaces():
        space_dir = Path(space_info.get("directory", ""))
        if not space_dir.exists():
            continue
        try:
            db_path = str(space_dir / ".spaces" / "sarthak.db")
            due_cards = await get_due(db_path)
            if not due_cards:
                continue
            name = space_info.get("name", space_dir.name)
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
            sections.append("\n".join(card_lines))
            total_due += len(due_cards)
        except Exception as exc:
            log.warning("srs_push_failed", space=str(space_dir), error=str(exc))

    if total_due == 0:
        output = "No SRS cards due today."
    else:
        output = "\n\n".join(sections)
        if spec.notify_telegram:
            await send_telegram(cfg, output, agent_id=spec.agent_id)

    await _finish_run(spec, run, output, success=True)
    log.info("srs_push_done", total_due=total_due)


async def _run_recommendations_agent(spec: AgentSpec) -> None:
    """Refresh recommendations for all spaces using session signals."""
    from sarthak.spaces.models import SpaceContext
    from sarthak.spaces.store import list_spaces, load_profile
    from sarthak.spaces.sub_agents import WorkspaceAnalyserAgent, detect_platform

    run = AgentRun(run_id=new_run_id(), agent_id=spec.agent_id)
    analyser = WorkspaceAnalyserAgent()
    updated: list[str] = []

    for space_info in list_spaces():
        space_dir = Path(space_info.get("directory", ""))
        if not space_dir.exists():
            continue
        try:
            profile = load_profile(space_dir)
            if not profile:
                continue
            ctx = SpaceContext(
                workspace_dir=str(space_dir),
                profile=profile,
                platform=detect_platform(),
            )
            content = await analyser.analyse(ctx)
            analyser.write_optimal_learn(space_dir, content)
            updated.append(space_info.get("name", space_dir.name))
        except Exception as exc:
            log.warning("recommendations_refresh_failed", space=str(space_dir), error=str(exc))

    output = f"Updated recommendations for: {', '.join(updated)}" if updated else "No spaces updated."
    await _finish_run(spec, run, output, success=True)
    log.info("recommendations_done", spaces=len(updated))


async def _run_weekly_digest_agent(spec: AgentSpec) -> None:
    """Build a week-in-review digest per space, consuming all user_activity data."""
    from datetime import date
    from sarthak.spaces.store import list_spaces
    from sarthak.agents.roadmap_agents import build_digest
    from sarthak.storage.activity_store import activity_summary, concepts_touched
    from sarthak.spaces.sub_agents import EngagementAgent
    from sarthak.spaces.store import load_profile

    run = AgentRun(run_id=new_run_id(), agent_id=spec.agent_id)
    outputs: list[str] = []
    cfg = await _get_telegram_cfg()
    engagement = EngagementAgent()

    for space_info in list_spaces():
        space_dir = Path(space_info.get("directory", ""))
        if not space_dir.exists():
            continue
        try:
            name = space_info.get("name", space_dir.name)
            base_digest = await build_digest(space_dir, name)

            # Enrich with full-week activity breakdown
            act = await activity_summary(str(space_dir), days=7)
            touched = await concepts_touched(str(space_dir), days=7)

            enrich_lines = [f"\n## Week in Review — {date.today().strftime('%B %d, %Y')}"]
            if act:
                enrich_lines.append("\n**Activity breakdown:**")
                for atype, cnt in sorted(act.items(), key=lambda x: -x[1]):
                    enrich_lines.append(f"- {atype.replace('_', ' ').title()}: {cnt}")
            if touched:
                enrich_lines.append(f"\n**Concepts touched this week:** {', '.join(touched[:8])}")

            combined = base_digest + "\n".join(enrich_lines)

            # Render with EngagementAgent if background is known
            profile = load_profile(space_dir)
            if profile and profile.learner.background:
                combined = await engagement.render(
                    content={"weekly_digest": combined},
                    learner_background=profile.learner.background,
                    xp_earned=0,
                    is_technical=profile.learner.is_technical,
                )

            outputs.append(f"=== {name} ===\n{combined}")
            if spec.notify_telegram:
                await send_telegram(cfg, combined, agent_id=spec.agent_id)
        except Exception as exc:
            log.warning("weekly_digest_failed", space=str(space_dir), error=str(exc))

    output = "\n\n".join(outputs) if outputs else "No spaces to review."
    await _finish_run(spec, run, output, success=bool(outputs))
    log.info("weekly_digest_done", spaces=len(outputs))


# ── Main loop ─────────────────────────────────────────────────────────────────

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
