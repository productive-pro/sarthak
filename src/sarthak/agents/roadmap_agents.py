"""
Sarthak Spaces — Roadmap LLM agents (all in one module).

Three agents, one shared `_make_agent()` helper:
  generate_roadmap()  → pydantic-ai structured output → Roadmap
  build_digest()      → str (Markdown daily digest)
  stream_explain()    → AsyncIterator[str] SSE tokens

All use resolve_provider_model() + build_pydantic_model() from features/ai/agents/_base.
Prompts live in agents/prompts/roadmap.py.
"""
from __future__ import annotations

from datetime import date, timedelta
from pathlib import Path
from typing import AsyncIterator

from pydantic import BaseModel, Field
from pydantic_ai import Agent

from sarthak.agents.prompts.roadmap import ROADMAP, DIGEST_WARMUP, EXPLAIN
from sarthak.core.logging import get_logger
from sarthak.features.ai.agents._base import resolve_provider_model, build_pydantic_model

if False:  # TYPE_CHECKING
    from sarthak.spaces.learner_context import LearnerContext
    from sarthak.spaces.roadmap.models import Roadmap

log = get_logger(__name__)


# ── Shared factory ────────────────────────────────────────────────────────────

def _make_agent(
    output_type,
    system_prompt: str,
    provider: str | None = None,
    model: str | None = None,
    retries: int = 2,
) -> Agent:
    p, m = resolve_provider_model(provider, model)
    return Agent(
        build_pydantic_model(p, m),
        output_type=output_type,
        system_prompt=system_prompt,
        retries=retries,
    )


# ── Roadmap generator ─────────────────────────────────────────────────────────

class _ConceptBlueprint(BaseModel):
    title: str
    description: str = ""
    tags: list[str] = Field(default_factory=list)


class _TopicBlueprint(BaseModel):
    title: str
    concepts: list[_ConceptBlueprint] = Field(default_factory=list)


class _ChapterBlueprint(BaseModel):
    title: str
    description: str = ""
    topics: list[_TopicBlueprint] = Field(default_factory=list)


class _RoadmapBlueprint(BaseModel):
    chapters: list[_ChapterBlueprint] = Field(default_factory=list)


async def generate_roadmap(
    space_name: str,
    domain: str,
    background: str = "",
    goal: str = "",
    provider: str | None = None,
    model: str | None = None,
) -> "Roadmap":
    """Call LLM to produce a full Roadmap ready for RoadmapDB persistence."""
    from sarthak.spaces.roadmap.models import (
        Roadmap, Chapter, Topic, Concept, RoadmapStatus,
    )

    agent = _make_agent(_RoadmapBlueprint, ROADMAP, provider, model, retries=3)
    result = await agent.run(
        f"Domain: {domain}\n"
        f"Learner background: {background or 'general learner'}\n"
        f"Goal: {goal or f'master {domain}'}\n"
        f"Space name: {space_name}\n\n"
        "Generate the full learning roadmap now."
    )
    bp = result.output

    chapters = [
        Chapter(
            title=ch.title,
            description=ch.description,
            order=ci,
            topics=[
                Topic(
                    title=tp.title,
                    order=ti,
                    status=RoadmapStatus.NOT_STARTED,
                    concepts=[
                        Concept(
                            title=cn.title,
                            description=cn.description,
                            order=ni,
                            tags=cn.tags,
                            status=RoadmapStatus.NOT_STARTED,
                        )
                        for ni, cn in enumerate(tp.concepts)
                    ],
                )
                for ti, tp in enumerate(ch.topics)
            ],
            progress_pct=0.0,
            status=RoadmapStatus.NOT_STARTED,
        )
        for ci, ch in enumerate(bp.chapters)
    ]
    roadmap = Roadmap(space=space_name, chapters=chapters)
    log.info("roadmap_generated", space=space_name, chapters=len(chapters))
    return roadmap


# ── Daily digest ──────────────────────────────────────────────────────────────

async def build_digest(space_dir: Path, space_name: str) -> str:
    """
    Build a Markdown daily digest grounded in real learner data.
    Sources (in priority order):
      1. LearnerContext — notes, test results, quicktests, stuck concepts
      2. Roadmap DB — concept completion progress
      3. SRS — evidence-based review queue (not just fixed intervals)
    One LLM call for the warm-up quicktest.
    After building, syncs evidence signals back into SRS cards.
    """
    from sarthak.spaces.roadmap.db import RoadmapDB
    from sarthak.spaces.roadmap.recommend import recommend_next
    from sarthak.spaces.learner_context import build_learner_context, learner_context_for_prompt
    from sarthak.spaces.store import load_profile

    db = RoadmapDB(space_dir)
    await db.init()
    roadmap = await db.load_roadmap()
    if roadmap is None:
        return f"# {space_name} — No roadmap yet\n\nRun `sarthak spaces init`."

    today = date.today()
    all_cn = roadmap.all_concepts()
    completed = [c for c in all_cn if c.status.value == "completed"]
    in_prog   = [c for c in all_cn if c.status.value == "in_progress"]

    # Build LearnerContext from real data
    profile = load_profile(space_dir)
    lc = None
    if profile:
        try:
            lc = await build_learner_context(space_dir, profile, days=7)
        except Exception as exc:
            log.warning("digest_learner_context_failed", error=str(exc))

    # SRS due: use evidence-based queue if available, else empty
    srs_due = lc.srs_due_by_evidence[:3] if lc else []

    # Next concepts: deprioritize weak if there are stuck items to fix
    next_concepts = recommend_next(roadmap, top_k=3)
    if lc and lc.weak_concepts:
        # Put weak concepts first in the up-next list
        weak_set = set(lc.weak_concepts[:2])
        next_titles = {cn.title for cn in next_concepts}
        extra_weak = [cn for cn in all_cn if cn.title in weak_set and cn.title not in next_titles]
        next_concepts = extra_weak + [cn for cn in next_concepts if cn.title not in weak_set]
        next_concepts = next_concepts[:3]

    # One LLM call for the warm-up quicktest
    warmup_md = ""
    if next_concepts:
        cn = next_concepts[0]
        # Include learner context so the quicktest is personalised
        lc_prompt = learner_context_for_prompt(lc) if lc else ""
        agent = _make_agent(str, DIGEST_WARMUP)
        result = await agent.run(
            f"Concept: {cn.title}\nDescription: {cn.description}\n\n{lc_prompt}"
        )
        warmup_md = result.output

    lines = [
        f"# Daily Digest — {today.strftime('%A, %B %d')}",
        f"**Space:** {space_name}", "",
        "## Progress",
        f"- **{len(completed)}** concepts completed "
        f"({len(in_prog)} in progress, {len(all_cn)} total)",
    ]

    # Notes + recordings activity
    if lc and lc.notes_written_total > 0:
        lines.append(
            f"- **{lc.notes_written_total}** notes/recordings covering: "
            f"{', '.join(lc.notes_concepts_covered[:5])}"
        )
    lines.append("")

    # Recent test performance
    if lc and lc.recent_test_results:
        lines.append("## Test Performance")
        for t in lc.recent_test_results[:3]:
            status = "PASS" if t["passed"] else "FAIL"
            weak_str = f" — needs work: {', '.join(t['weak'][:2])}" if t["weak"] else ""
            lines.append(f"- {t['date']} [{status}] {t['percent']:.0f}%{weak_str}")
        lines.append("")

    # Weak concepts to fix (from real evidence)
    if lc and lc.weak_concepts:
        lines.append("## Fix First")
        for c in lc.weak_concepts[:3]:
            ev = lc.concept_evidence.get(c)
            detail = ""
            if ev:
                parts = []
                if ev.times_stuck >= 2: parts.append(f"stuck {ev.times_stuck}×")
                if ev.test_percent < 50 and ev.test_attempts: parts.append(f"{ev.test_percent:.0f}% on tests")
                if ev.note_count == 0: parts.append("no notes")
                detail = f" ({'; '.join(parts)})" if parts else ""
            lines.append(f"- **{c}**{detail}")
        lines.append("")

    # Up Next
    if next_concepts:
        lines.append("## Up Next")
        for i, cn in enumerate(next_concepts, 1):
            tags = ", ".join(cn.tags[:4]) if cn.tags else ""
            lines.append(
                f"{i}. **{cn.title}** — {cn.description[:80]}…"
                + (f"  `{tags}`" if tags else "")
            )
        lines.append("")

    # Evidence-based SRS
    if srs_due:
        lines.append("## Review Due (evidence-based)")
        for concept in srs_due:
            ev = lc.concept_evidence.get(concept) if lc else None
            reason = ""
            if ev:
                if ev.note_count == 0: reason = " — no notes written"
                elif ev.test_percent < 50 and ev.test_attempts: reason = f" — {ev.test_percent:.0f}% on tests"
            lines.append(f"- **{concept}**{reason}")
        lines.append("")

    # Recent breakthroughs
    if lc and lc.recent_breakthroughs:
        lines.append("## Recent Breakthroughs")
        for b in lc.recent_breakthroughs[:2]:
            lines.append(f"- {b}")
        lines.append("")

    # Recent recordings (transcribed only)
    try:
        from sarthak.spaces.roadmap.db import RoadmapDB as _RDB
        _rdb = _RDB(space_dir)
        await _rdb.init()
        media_notes = await _rdb.list_all_media_notes()
        recent_media = [n for n in media_notes if n.body_md.strip()][:3]
        if recent_media:
            lines.append("## Recent Recordings")
            for n in recent_media:
                label = n.title or n.type
                snippet = n.body_md.strip()[:120].replace("\n", " ")
                lines.append(f"- **{label}**: {snippet}...")
            lines.append("")
    except Exception:
        pass

    if warmup_md:
        lines += ["## Warm-Up QuickTest", warmup_md]

    raw_digest = "\n".join(lines)

    # ── User activity signals (audio/video notes, code runs) ──────────────────
    try:
        from sarthak.storage.activity_store import activity_summary, recent_media_notes
        act_summary = await activity_summary(str(space_dir), days=7)
        if act_summary:
            lines.insert(-1, "")
            activity_lines = ["## Activity This Week"]
            for atype, cnt in sorted(act_summary.items(), key=lambda x: -x[1]):
                activity_lines.append(f"- {atype.replace('_', ' ').title()}: {cnt}")
            lines.insert(-1, "\n".join(activity_lines))
        media = await recent_media_notes(str(space_dir), days=7)
        transcribed = [m for m in media if m.get("content_text", "").strip()]
        if transcribed:
            lines.append("")
            lines.append("## Recent Audio/Video Notes")
            for m in transcribed[:3]:
                snippet = m["content_text"].strip()[:100].replace("\n", " ")
                lines.append(f"- [{m['concept_title'] or 'General'}] {snippet}...")
    except Exception:
        pass

    raw_digest = "\n".join(lines)

    # ── EngagementAgent: render the digest in learner's style ─────────────────
    if profile and profile.learner.background:
        try:
            from sarthak.spaces.sub_agents import EngagementAgent
            agent = EngagementAgent()
            raw_digest = await agent.render(
                content={"digest": raw_digest},
                learner_background=profile.learner.background,
                xp_earned=0,
                is_technical=profile.learner.is_technical,
            )
        except Exception:
            pass  # fall back to raw

    # Sync evidence signals back into SRS scheduler
    await _sync_digest_to_srs(space_dir, lc, roadmap)

    return raw_digest


async def _sync_digest_to_srs(
    space_dir: Path,
    lc: "LearnerContext | None",
    roadmap: "Roadmap | None",
) -> None:
    """
    Translate LearnerContext evidence into SRS card upserts.
    Called automatically after every build_digest().
    """
    from sarthak.spaces.roadmap.srs import DigestSignals, sync_from_digest

    db_path = str(space_dir / ".spaces" / "sarthak.db")

    if lc is None:
        return

    # Include media notes that have transcripts as note signal for SRS
    try:
        from sarthak.spaces.roadmap.db import RoadmapDB as _RDB
        _rdb = _RDB(space_dir)
        await _rdb.init()
        _roadmap = roadmap
        media_notes = await _rdb.list_all_media_notes()
        for n in media_notes:
            if n.concept_id and n.body_md.strip():
                concept = n.concept_id
                if _roadmap:
                    cn = _roadmap.get_concept(n.concept_id)
                    if cn:
                        concept = cn.title
                if concept not in lc.concept_evidence and concept not in lc.in_progress_concepts:
                    lc.in_progress_concepts.append(concept)
    except Exception:
        pass

    # Concepts with times_stuck >= 2
    stuck = [
        c for c, ev in lc.concept_evidence.items() if ev.times_stuck >= 2
    ]

    # Concepts that failed tests (< 50% score, at least 1 attempt)
    test_failed = [
        c for c, ev in lc.concept_evidence.items()
        if ev.test_attempts >= 1 and ev.test_percent < 50.0
        and c not in stuck
    ]

    # Concepts that are weak (low mastery confidence, not already categorised above)
    already = set(stuck) | set(test_failed)
    weak = [
        c for c in lc.weak_concepts
        if c not in already
    ]

    # Mastered-but-stale: in srs_due_by_evidence but no notes and not in weak already
    no_note = [
        c for c in lc.srs_due_by_evidence
        if c not in already and c not in weak
        and lc.concept_evidence.get(c) is not None
        and lc.concept_evidence[c].note_count == 0
    ]

    # Strong — create/maintain maintenance cards
    strong = lc.strong_concepts[:6]

    # Breakthroughs — extract concept names from "concept: detail" strings
    breakthroughs = [
        b.split(":")[0].strip() for b in lc.recent_breakthroughs if ":" in b
    ]

    signals = DigestSignals(
        weak_concepts=weak,
        stuck_concepts=stuck,
        no_note_concepts=no_note,
        test_failed_concepts=test_failed,
        strong_concepts=strong,
        recent_breakthroughs=breakthroughs,
    )

    try:
        count = await sync_from_digest(db_path, signals)
        log.info("digest_srs_synced", space=str(space_dir), cards=count)
    except Exception as exc:
        log.warning("digest_srs_sync_failed", error=str(exc))


async def send_digest_telegram(space_dir: Path, space_name: str) -> bool:
    """Push digest via the existing Telegram bot. Returns True on success."""
    try:
        from sarthak.features.channels.telegram.bot import send_message
    except ImportError:
        log.warning("telegram_not_available")
        return False
    try:
        await send_message(await build_digest(space_dir, space_name))
        log.info("digest_sent", space=space_name)
        return True
    except Exception as exc:
        log.warning("digest_send_failed", error=str(exc))
        return False


# ── Inline explainer (SSE) ────────────────────────────────────────────────────

async def stream_explain(
    concept_title: str,
    concept_description: str,
    chapter_title: str = "",
    topic_title: str = "",
    user_prompt: str = "",
    provider: str | None = None,
    model: str | None = None,
) -> AsyncIterator[str]:
    """
    Yield SSE data strings for streaming concept explanation.

    Yields  "data: <token>\\n\\n"  (\\n encoded as U+2028 within a frame)
    Ends    "data: [DONE]\\n\\n"
    """
    p, m = resolve_provider_model(provider, model)
    log.info("stream_explain_agent_start", concept=concept_title, provider=p, model=m)
    agent: Agent[None, str] = Agent(
        build_pydantic_model(p, m),
        output_type=str,
        system_prompt=EXPLAIN,
        retries=2,
    )
    ctx = f"Chapter: {chapter_title}" + (f" › {topic_title}" if topic_title else "") + "\n" if chapter_title else ""
    base_msg = f"{ctx}Concept: **{concept_title}**\n{concept_description}"
    user_msg = base_msg + (f"\n\nUser question: {user_prompt}" if user_prompt else "")
    try:
        async with agent.run_stream(user_msg) as stream:
            async for delta in stream.stream_text(delta=True):
                yield f"data: {delta.replace(chr(10), chr(0x2028))}\n\n"
        log.info("stream_explain_agent_done", concept=concept_title)
    except Exception as exc:
        log.error("stream_explain_agent_error", concept=concept_title, error=str(exc))
        raise
    yield "data: [DONE]\n\n"
