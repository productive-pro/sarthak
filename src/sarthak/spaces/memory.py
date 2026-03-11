"""
Sarthak Space Memory — per-space persistent agent memory.

Files written to <space>/.spaces/:
  SOUL.md      — agent identity + space goal. Created once at init, never overwritten.
  MEMORY.md    — behavioural patterns extracted after real LLM exchanges (not DB state).
                 extract_memory_from_exchange() appends bullets post-response.
                 distill_memory() rewrites cleanly every Sunday.
  HEARTBEAT.md — SRS due cards + streak. Updated at every session end.

Removed vs old design:
  - USER.md deleted. DB-field mirroring into Markdown is pointless.
  - Nightly sync_user_md removed from scheduler entirely.
  - Context injection no longer loads all files blindly on every question.

Context injection strategy:
  - Default (learning questions): SOUL + MEMORY only (~600 chars).
  - include_heartbeat=True: adds HEARTBEAT — only for SRS/streak/schedule questions.

Public API:
    init_space_memory(space_dir, profile)
    sync_heartbeat_md(space_dir, profile, due_cards)            — every session end
    append_daily_log(space_dir, session, profile, xp, badges)   — session end
    extract_memory_from_exchange(space_dir, q, reply, profile)  — post-LLM fire-and-forget
    distill_memory(space_dir, profile)                          — Sunday weekly
    read_context_block_async(space_dir, include_heartbeat, max_chars)
    read_context_block(space_dir, max_chars)                    — sync shim
"""
from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from pathlib import Path

import structlog

log = structlog.get_logger(__name__)

_MEMORY_SUBDIR = "memory"
_CONTEXT_CACHE_TTL = 120   # seconds
_MEMORY_MAX_LINES = 150    # trim oldest when exceeded


# ── I/O helpers ───────────────────────────────────────────────────────────────

def _write_atomic(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(content, encoding="utf-8")
    tmp.replace(path)

async def _write_async(path: Path, content: str) -> None:
    await asyncio.to_thread(_write_atomic, path, content)

def _spaces_dir(space_dir: Path) -> Path:
    d = space_dir / ".spaces"
    d.mkdir(parents=True, exist_ok=True)
    return d


# ── Renderers (pure, no I/O) ──────────────────────────────────────────────────

def _render_soul(profile: "SpaceProfile") -> str:
    lr = profile.learner
    return (
        f"# SOUL — {profile.domain}\n\n"
        f"Domain: {profile.domain}\n"
        f"Goal: {lr.goal or 'Mastery of ' + profile.domain}\n"
        f"Learner: {lr.name or 'Unknown'} | "
        f"Technical: {'yes' if lr.is_technical else 'no'} | "
        f"Style: {lr.preferred_style}\n"
        f"Background: {lr.background or 'not specified'}\n\n"
        f"Rules:\n"
        f"- 'What next?' → consult ZPD and struggling concepts first.\n"
        f"- Learner stuck → offer next hint before asking.\n"
        f"- Non-technical → lead with WHY, code is secondary.\n"
        f"- Specific praise only. No filler.\n\n"
        f"Initialized: {datetime.now(timezone.utc).strftime('%Y-%m-%d')}\n"
    )

def _render_heartbeat(profile: "SpaceProfile", due_cards: list[str] | None = None) -> str:
    lr = profile.learner
    lines = [
        f"# HEARTBEAT — {profile.domain}",
        f"Synced: {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')}",
        "",
    ]
    if due_cards:
        lines.append(f"SRS due ({len(due_cards)}):")
        lines.extend(f"- {c}" for c in due_cards[:8])
        lines.append("")
    lines.append(f"Streak: {lr.streak_days}d | Goal: {lr.daily_goal_minutes} min/day")
    lines.append(f"Level: {lr.skill_level.value} | Mastered: {len(lr.mastered_concepts)}")
    if lr.struggling_concepts:
        lines.append(f"Struggling: {', '.join(lr.struggling_concepts[:4])}")
    return "\n".join(lines) + "\n"

def _render_session_entry(
    session: "SpaceSession",
    profile: "SpaceProfile",
    xp_earned: int,
    badges_earned: list[str],
) -> str:
    sig = session.signals
    rep = session.self_report
    ts  = session.started_at.strftime("%H:%M")
    te  = session.ended_at.strftime("%H:%M") if session.ended_at else "ongoing"
    lines = [
        f"## {ts}–{te} — {session.concept}",
        f"- Done: {'yes' if rep.task_completed else 'no'} | "
        f"Understanding: {rep.understanding_rating}/5 | "
        f"Focus: {sig.focus_ratio:.0%} | Depth: {sig.depth_score:.2f}",
    ]
    if sig.lines_written:
        lines.append(f"- Lines: {sig.lines_written}")
    if rep.stuck_on:
        lines.append(f"- Stuck: {', '.join(rep.stuck_on)}")
    if rep.breakthrough:
        lines.append(f"- Breakthrough: {rep.breakthrough}")
    if xp_earned:
        lines.append(f"- XP: +{xp_earned}")
    if badges_earned:
        lines.append(f"- Badges: {', '.join(badges_earned)}")
    return "\n".join(lines)


# ── Cache helpers ─────────────────────────────────────────────────────────────

def _ctx_cache_key(space_dir: Path, include_heartbeat: bool = False) -> str:
    from sarthak.storage.factory import space_cache_key
    suffix = "mem_ctx_hb" if include_heartbeat else "mem_ctx"
    return space_cache_key(str(space_dir), suffix)

async def _invalidate_ctx_cache(space_dir: Path) -> None:
    try:
        from sarthak.storage.factory import get_cache
        cache = get_cache()
        await asyncio.gather(
            cache.delete(_ctx_cache_key(space_dir, False)),
            cache.delete(_ctx_cache_key(space_dir, True)),
            return_exceptions=True,
        )
    except Exception:
        pass

def _fire_invalidate(space_dir: Path) -> None:
    """Thread-safe fire-and-forget cache invalidation."""
    try:
        loop = asyncio.get_running_loop()
        loop.call_soon_threadsafe(loop.create_task, _invalidate_ctx_cache(space_dir))
    except RuntimeError:
        pass  # no running loop — TTL will expire it naturally


# ── Memory trim ───────────────────────────────────────────────────────────────

def _trim_memory_if_needed(path: Path) -> None:
    """Keep MEMORY.md under _MEMORY_MAX_LINES by dropping oldest content lines."""
    if not path.exists():
        return
    lines = path.read_text(encoding="utf-8").splitlines()
    if len(lines) <= _MEMORY_MAX_LINES:
        return
    # Preserve header (first line) + most recent lines
    trimmed = lines[:1] + lines[-(  _MEMORY_MAX_LINES - 1):]
    _write_atomic(path, "\n".join(trimmed) + "\n")


# ── Public write API ──────────────────────────────────────────────────────────

async def init_space_memory(space_dir: Path, profile: "SpaceProfile") -> None:
    """Create SOUL.md + scaffold MEMORY.md at space init. Idempotent."""
    sd = _spaces_dir(space_dir)
    soul_path = sd / "SOUL.md"
    mem_path  = sd / "MEMORY.md"
    tasks = []
    if not soul_path.exists():
        tasks.append(_write_async(soul_path, _render_soul(profile)))
    if not mem_path.exists():
        tasks.append(_write_async(mem_path, f"# MEMORY — {profile.domain}\n\n"))
    if tasks:
        await asyncio.gather(*tasks)
        await _invalidate_ctx_cache(space_dir)
    log.info("space_memory_initialized", space=str(space_dir))


def sync_heartbeat_md(
    space_dir: Path,
    profile: "SpaceProfile",
    due_cards: list[str] | None = None,
) -> None:
    """Refresh HEARTBEAT.md with current SRS due cards. Called at every session end."""
    _write_atomic(_spaces_dir(space_dir) / "HEARTBEAT.md", _render_heartbeat(profile, due_cards))
    _fire_invalidate(space_dir)
    log.debug("heartbeat_synced", space=str(space_dir))


async def append_daily_log(
    space_dir: Path,
    session: "SpaceSession",
    profile: "SpaceProfile",
    xp_earned: int = 0,
    badges_earned: list[str] | None = None,
) -> None:
    """Append session entry to memory/YYYY-MM-DD.md."""
    today   = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    mem_dir = _spaces_dir(space_dir) / _MEMORY_SUBDIR
    mem_dir.mkdir(parents=True, exist_ok=True)
    day_file = mem_dir / f"{today}.md"
    entry    = _render_session_entry(session, profile, xp_earned, badges_earned or [])

    def _do_append() -> None:
        if not day_file.exists():
            day_file.write_text(f"# {today} — {profile.domain}\n\n{entry}\n", encoding="utf-8")
        else:
            with day_file.open("a", encoding="utf-8") as f:
                f.write(f"\n{entry}\n")

    await asyncio.to_thread(_do_append)
    log.debug("daily_log_appended", space=str(space_dir), concept=session.concept)


async def extract_memory_from_exchange(
    space_dir: Path,
    question: str,
    reply: str,
    profile: "SpaceProfile",
) -> None:
    """
    Post-LLM hook: extract a behavioural insight from one exchange.
    Appends a single bullet to MEMORY.md if the exchange reveals something worth keeping.
    Designed to be called as fire-and-forget: asyncio.create_task(extract_memory_from_exchange(...))

    Only appends when the LLM returns a '- ...' bullet. Outputs 'SKIP' otherwise.
    """
    from sarthak.features.ai.agents._base import run_llm

    sd     = _spaces_dir(space_dir)
    mem_md = sd / "MEMORY.md"
    tail   = mem_md.read_text(encoding="utf-8")[-600:] if mem_md.exists() else ""

    system = (
        "You extract learner behavioural patterns from a single learning exchange.\n"
        "Output ONE bullet ('- ...') only if the exchange reveals:\n"
        "  - A persistent struggle or misconception\n"
        "  - A preferred explanation style (analogies, code-first, visual, etc.)\n"
        "  - A breakthrough or conceptual shift\n"
        "  - A recurring habit (avoids math, always wants examples first, etc.)\n"
        "If nothing worth keeping, output exactly: SKIP\n"
        "No headers, no explanation — just the bullet or SKIP."
    )
    prompt = (
        f"Domain: {profile.domain}\n"
        f"Recent memory:\n{tail}\n\n"
        f"Q: {question[:300]}\n"
        f"A: {reply[:400]}"
    )

    try:
        result = (await run_llm(system, prompt, agent="memory_extractor")).strip()
        if result and result != "SKIP" and result.startswith("- "):
            def _append() -> None:
                with mem_md.open("a", encoding="utf-8") as f:
                    f.write(f"{result}\n")
                _trim_memory_if_needed(mem_md)
            await asyncio.to_thread(_append)
            await _invalidate_ctx_cache(space_dir)
            log.debug("memory_extracted", space=str(space_dir))
    except Exception as exc:
        log.debug("memory_extract_skipped", error=str(exc))


async def distill_memory(space_dir: Path, profile: "SpaceProfile") -> None:
    """
    Weekly (Sunday): rewrite MEMORY.md as a clean deduplicated bullet list.
    Uses last 7 daily logs + current MEMORY.md as input.
    """
    from sarthak.features.ai.agents._base import run_llm

    sd      = _spaces_dir(space_dir)
    mem_dir = sd / _MEMORY_SUBDIR
    mem_md  = sd / "MEMORY.md"
    if not mem_dir.exists():
        return

    log_files = sorted(mem_dir.glob("*.md"), reverse=True)[:7]
    if not log_files:
        return

    contents = await asyncio.gather(*[
        asyncio.to_thread(lambda p: p.read_text(encoding="utf-8"), f) for f in log_files
    ])
    existing = mem_md.read_text(encoding="utf-8") if mem_md.exists() else ""

    system = (
        "You maintain a learner's long-term behavioural memory.\n"
        "Rewrite it as a clean, deduplicated bullet list.\n"
        "Keep only: struggle patterns, explanation style preferences, breakthroughs, recurring habits.\n"
        "Merge duplicates. Drop anything no longer relevant.\n"
        "Max 120 words. Output ONLY the bullet list, no headers, no preamble."
    )
    prompt = (
        f"Domain: {profile.domain}\n\n"
        f"CURRENT MEMORY:\n{existing}\n\n"
        f"LAST 7 DAYS SESSION LOGS:\n{chr(10).join(contents)[:3000]}"
    )

    try:
        distilled = (await run_llm(system, prompt, agent="memory_distiller")).strip()
        if distilled:
            def _rewrite() -> None:
                _write_atomic(mem_md, f"# MEMORY — {profile.domain}\n\n{distilled}\n")
            await asyncio.to_thread(_rewrite)
            await _invalidate_ctx_cache(space_dir)
            log.info("memory_distilled", space=str(space_dir))
    except Exception as exc:
        log.warning("memory_distill_failed", space=str(space_dir), error=str(exc))


# ── Read API ──────────────────────────────────────────────────────────────────

async def read_context_block_async(
    space_dir: Path,
    include_heartbeat: bool = False,
    max_chars: int = 1200,
) -> str:
    """
    Returns SOUL + MEMORY (always) + optionally HEARTBEAT.
    Pass include_heartbeat=True only for SRS/streak/schedule questions.
    Result cached for _CONTEXT_CACHE_TTL seconds.
    """
    key   = _ctx_cache_key(space_dir, include_heartbeat)
    cache = None
    try:
        from sarthak.storage.factory import get_cache
        cache = get_cache()
        cached = await cache.get(key)
        if cached is not None:
            return cached
    except Exception:
        pass

    result = await asyncio.to_thread(_read_sync, space_dir, include_heartbeat, max_chars)

    if cache is not None:
        try:
            await cache.set(key, result, ttl=_CONTEXT_CACHE_TTL)
        except Exception:
            pass
    return result


def _read_sync(space_dir: Path, include_heartbeat: bool, max_chars: int) -> str:
    try:
        sd    = _spaces_dir(space_dir)
        files = ["SOUL.md", "MEMORY.md"]
        if include_heartbeat:
            files.append("HEARTBEAT.md")
        parts = []
        for fname in files:
            p = sd / fname
            if p.exists():
                text = p.read_text(encoding="utf-8").strip()
                if text:
                    parts.append(text)
        combined = "\n\n".join(parts)
        if len(combined) > max_chars:
            combined = combined[:max_chars] + "\n…"
        return combined
    except Exception as exc:
        log.debug("context_read_failed", error=str(exc))
        return ""


def read_context_block(space_dir: Path, max_chars: int = 1200) -> str:
    """Sync shim. Prefer read_context_block_async() from async contexts."""
    return _read_sync(space_dir, include_heartbeat=False, max_chars=max_chars)
