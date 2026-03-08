"""
Sarthak Spaces — Learner Context Aggregator.

Replaces weak proxy signals (focus_ratio, idle_sec, git_commits) with the
REAL signals: what the learner actually read, wrote, understood, and struggled with.

This is the single function called by:
  - SignalOptimizer      → recommendations
  - SpacedRepetitionAgent → what to review next
  - build_digest()       → daily summary
  - CurriculumAgent      → next concept selection

Data sources (priority order):
  1. Notes              — what the learner actually wrote down (.spaces/notes/)
  2. RAG index           — what files exist and were recently modified
  3. Practice tests      — objective concept scores (test_results.jsonl)
  4. Quicktests          — which micro-tasks were completed (sessions.jsonl, type=quicktest)
  5. Sessions            — self-report (understanding_rating, stuck_on, breakthrough)
  6. Roadmap             — which concepts are in progress / completed

Proxy signals (still collected but LOW weight):
  - focus_ratio, depth_score, git_commits  (from session_tracker)

Public API:
    build_learner_context(space_dir, profile, days)  → LearnerContext
    learner_context_for_prompt(ctx)                  → str  (inject into LLM prompts)
"""
from __future__ import annotations

import statistics
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path

from sarthak.core.logging import get_logger
from sarthak.spaces.models import SpaceProfile

log = get_logger(__name__)


# ── Data structures ────────────────────────────────────────────────────────────

@dataclass
class ConceptEvidence:
    """All evidence about a single concept across data sources."""
    concept: str
    # From notes
    note_count: int = 0
    note_chars: int = 0
    last_note_date: str = ""
    # From practice tests / quicktests
    test_attempts: int = 0
    test_correct: int = 0
    test_percent: float = 0.0   # avg % correct across attempts
    quicktest_attempts: int = 0
    quicktest_passed: int = 0
    # From sessions (self-report)
    times_studied: int = 0
    times_stuck: int = 0
    understanding_ratings: list[int] = field(default_factory=list)
    breakthroughs: list[str] = field(default_factory=list)
    # From RAG (files indexed about this concept)
    rag_file_count: int = 0
    # Computed
    avg_understanding: float = 0.0
    mastery_confidence: float = 0.0  # 0-1 composite

    def compute(self) -> None:
        if self.understanding_ratings:
            self.avg_understanding = statistics.mean(self.understanding_ratings)
        # Mastery confidence: 40% test score + 30% self-understanding + 20% notes + 10% quicktests
        test_score = self.test_percent / 100.0 if self.test_attempts else 0.0
        understand = (self.avg_understanding / 5.0) if self.understanding_ratings else 0.5
        note_signal = min(1.0, self.note_count * 0.25 + self.note_chars / 2000.0)
        qt_signal = (self.quicktest_passed / self.quicktest_attempts) if self.quicktest_attempts else 0.0
        self.mastery_confidence = (
            0.40 * test_score +
            0.30 * understand +
            0.20 * note_signal +
            0.10 * qt_signal
        )


@dataclass
class ReadingActivity:
    """What the learner has been reading/indexing — from RAG mtime data."""
    file_path: str
    concept_hint: str = ""
    modified_at: float = 0.0
    file_type: str = ""


@dataclass
class LearnerContext:
    """
    The full picture of what this learner actually knows and struggles with.
    Built fresh before every recommendation, digest, or SRS decision.
    """
    space_dir: str
    built_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    days_window: int = 14

    # Per-concept evidence (the primary signal)
    concept_evidence: dict[str, ConceptEvidence] = field(default_factory=dict)

    # Aggregated signals
    strong_concepts: list[str] = field(default_factory=list)      # confidence >= 0.7
    weak_concepts: list[str] = field(default_factory=list)         # confidence < 0.35 or stuck >= 2
    in_progress_concepts: list[str] = field(default_factory=list)  # studied but not strong
    untouched_concepts: list[str] = field(default_factory=list)    # no evidence at all

    # Recent activity summary
    recent_notes: list[dict] = field(default_factory=list)         # last 5 note snippets
    recent_test_results: list[dict] = field(default_factory=list)  # last 5 test summaries
    recent_breakthroughs: list[str] = field(default_factory=list)  # aha moments
    recent_reading: list[ReadingActivity] = field(default_factory=list)

    # Session statistics (low-weight proxy signals)
    total_sessions_in_window: int = 0
    avg_session_depth: float = 0.0
    most_productive_time: str = ""  # "morning" | "afternoon" | "evening"

    # Spaced repetition: concepts due for review based on actual evidence
    srs_due_by_evidence: list[str] = field(default_factory=list)

    # Notes written count
    notes_written_total: int = 0
    notes_concepts_covered: list[str] = field(default_factory=list)


# ── Builder ────────────────────────────────────────────────────────────────────

async def build_learner_context(
    space_dir: Path,
    profile: SpaceProfile,
    days: int = 14,
) -> LearnerContext:
    """
    Aggregate all real learning signals into a LearnerContext.
    Fast — reads JSONL files and note index only (no LLM calls).
    """
    space_dir = Path(space_dir)
    ctx = LearnerContext(space_dir=str(space_dir), days_window=days)
    cutoff = datetime.now(timezone.utc) - timedelta(days=days)

    evidence: dict[str, ConceptEvidence] = defaultdict(lambda: ConceptEvidence(concept=""))

    # ── 1. Notes (highest signal: what the learner wrote) ──────────────────────
    _ingest_notes(space_dir, evidence, cutoff, ctx)

    # ── 1b. Media notes: audio/video recordings with transcripts ──────────────
    await _ingest_media_notes(space_dir, evidence, cutoff)

    # ── 1c. Unified activity store: code runs, practice tests, quicktests ─────
    await _ingest_activity_store(space_dir, evidence, cutoff)

    # ── 2. Test results (objective concept scores) ─────────────────────────────
    _ingest_test_results(space_dir, evidence, cutoff, ctx)

    # ── 3. Sessions: self-report, quicktests, stuck_on ─────────────────────────
    _ingest_sessions(space_dir, evidence, cutoff, ctx)

    # ── 4. RAG index: what files exist and what concepts they hint at ──────────
    _ingest_rag_index(space_dir, evidence, ctx)

    # ── 5. Compute per-concept mastery confidence ──────────────────────────────
    for concept, ev in evidence.items():
        ev.concept = concept
        ev.compute()
    ctx.concept_evidence = dict(evidence)

    # ── 6. Classify concepts ───────────────────────────────────────────────────
    all_known = set(profile.learner.mastered_concepts) | set(evidence.keys())
    for concept in all_known:
        ev = evidence.get(concept)
        if ev is None:
            ctx.untouched_concepts.append(concept)
        elif ev.mastery_confidence >= 0.70:
            ctx.strong_concepts.append(concept)
        elif ev.mastery_confidence < 0.35 or ev.times_stuck >= 2:
            ctx.weak_concepts.append(concept)
        else:
            ctx.in_progress_concepts.append(concept)

    # Sort by confidence
    ctx.strong_concepts.sort(
        key=lambda c: evidence[c].mastery_confidence if c in evidence else 1.0, reverse=True
    )
    ctx.weak_concepts.sort(
        key=lambda c: evidence[c].mastery_confidence if c in evidence else 0.0
    )

    # ── 7. SRS due: evidence-based + failed code runs ─────────────────────────
    ctx.srs_due_by_evidence = _compute_srs_due(evidence, profile, cutoff)
    try:
        from sarthak.storage.activity_store import failed_code_run_concepts
        failed = await failed_code_run_concepts(str(space_dir), threshold=3, days=30)
        for c in failed:
            if c not in ctx.srs_due_by_evidence:
                ctx.srs_due_by_evidence.append(c)
        ctx.srs_due_by_evidence = ctx.srs_due_by_evidence[:8]
    except Exception:
        pass

    log.info(
        "learner_context_built",
        strong=len(ctx.strong_concepts),
        weak=len(ctx.weak_concepts),
        in_progress=len(ctx.in_progress_concepts),
        notes=ctx.notes_written_total,
    )
    return ctx


# ── Ingesters ──────────────────────────────────────────────────────────────────

async def _ingest_activity_store(
    space_dir: Path,
    evidence: dict[str, ConceptEvidence],
    cutoff: datetime,
) -> None:
    """Pull code runs, practice tests, quicktests, and transcripts from user_activity."""
    try:
        from sarthak.storage.activity_store import query_activity
        rows = await query_activity(space_dir=str(space_dir), days=30, limit=500)
    except Exception as exc:
        log.debug("activity_store_ingest_failed", error=str(exc))
        return

    for row in rows:
        concept = (row.get("concept_title") or "").strip()
        if not concept:
            continue
        atype = row.get("activity_type", "")
        ev = evidence[concept]

        if atype == "code_run":
            import json as _json
            meta = _json.loads(row.get("metadata") or "{}")
            if meta.get("success") is False:
                ev.times_stuck += 1
            else:
                ev.times_studied += 1
            # Count code in transcript chars too (signals active work)
            ev.note_chars += min(len(row.get("content_text", "")), 500)

        elif atype in ("audio_note", "video_note"):
            transcript = (row.get("content_text") or "").strip()
            if transcript:
                ev.note_count += 1
                ev.note_chars += len(transcript)
                ts = row.get("ts", "")
                if not ev.last_note_date or ts > ev.last_note_date:
                    ev.last_note_date = ts

        elif atype == "practice_test":
            import json as _json
            meta = _json.loads(row.get("metadata") or "{}")
            pct = float(meta.get("percent", 0))
            ev.test_percent = (
                (ev.test_percent * ev.test_attempts + pct) / (ev.test_attempts + 1)
            )
            ev.test_attempts += 1
            if pct >= 80:
                ev.test_correct += 1

        elif atype == "quicktest":
            ev.quicktest_attempts += 1
            ev.times_studied += 1

        elif atype == "note":
            ev.note_count += 1
            ev.note_chars += len(row.get("content_text", ""))


def _ingest_notes(
    space_dir: Path,
    evidence: dict[str, ConceptEvidence],
    cutoff: datetime,
    ctx: LearnerContext,
) -> None:
    """Read .spaces/notes_index.jsonl — highest signal."""
    import json
    index = space_dir / ".spaces" / "notes_index.jsonl"
    if not index.exists():
        return

    concepts_with_notes: set[str] = set()
    recent: list[dict] = []

    for line in index.read_text(encoding="utf-8").splitlines():
        try:
            d = json.loads(line)
            concept = d.get("concept", "").strip()
            if not concept:
                continue
            created_str = d.get("created_at", "")
            try:
                created = datetime.fromisoformat(created_str)
                if created.tzinfo is None:
                    created = created.replace(tzinfo=timezone.utc)
            except Exception:
                created = datetime.now(timezone.utc)

            content = d.get("content_md", "")
            ev = evidence[concept]
            ev.note_count += 1
            ev.note_chars += len(content)
            if not ev.last_note_date or created_str > ev.last_note_date:
                ev.last_note_date = created_str

            ctx.notes_written_total += 1
            concepts_with_notes.add(concept)

            if created >= cutoff:
                recent.append({
                    "concept": concept,
                    "date": created_str[:10],
                    "source": d.get("source", "manual"),
                    "snippet": content.strip()[:200],
                })
        except Exception:
            pass

    ctx.notes_concepts_covered = sorted(concepts_with_notes)
    # Keep last 5 most recent notes
    ctx.recent_notes = sorted(recent, key=lambda x: x["date"], reverse=True)[:5]


async def _ingest_media_notes(
    space_dir: Path,
    evidence: dict[str, ConceptEvidence],
    cutoff: datetime,
) -> None:
    """Ingest audio/video notes from DB. Transcribed content counts as note signal."""
    try:
        from sarthak.spaces.roadmap.db import RoadmapDB
        from sarthak.spaces.roadmap.srs import sync_note_card

        db = RoadmapDB(space_dir)
        await db.init()
        roadmap = await db.load_roadmap()
        media_notes = await db.list_all_media_notes()
        db_path = str(space_dir / ".spaces" / "sarthak.db")

        for note in media_notes:
            if not note.concept_id:
                continue
            # Resolve concept title from roadmap
            concept = note.concept_id
            if roadmap:
                cn = roadmap.get_concept(note.concept_id)
                if cn:
                    concept = cn.title

            transcript = (note.body_md or "").strip()
            ev = evidence[concept]

            # Recording itself counts as engagement (like a short note)
            ev.note_count += 1
            ev.note_chars += len(transcript)  # 0 if not transcribed yet

            # Update last_note_date
            if not ev.last_note_date or note.created_at > ev.last_note_date:
                ev.last_note_date = note.created_at

            # If transcript exists, ensure SRS card is scheduled
            if transcript:
                try:
                    await sync_note_card(db_path, note.id, concept)
                except Exception:
                    pass
    except Exception as exc:
        log.debug("media_notes_ingest_failed", error=str(exc))


def _ingest_test_results(
    space_dir: Path,
    evidence: dict[str, ConceptEvidence],
    cutoff: datetime,
    ctx: LearnerContext,
) -> None:
    """Read .spaces/test_results.jsonl — objective concept scores."""
    from sarthak.spaces.practice import load_test_results

    results = load_test_results(space_dir, limit=50)
    recent_summaries: list[dict] = []

    for r in results:
        try:
            finished = datetime.fromisoformat(r.finished_at or r.started_at)
            if finished.tzinfo is None:
                finished = finished.replace(tzinfo=timezone.utc)
        except Exception:
            finished = datetime.now(timezone.utc)

        is_recent = finished >= cutoff

        # Weak concepts from this test
        for concept in r.weak_concepts:
            ev = evidence[concept]
            ev.test_percent = (ev.test_percent * ev.test_attempts + 0) / (ev.test_attempts + 1)
            ev.test_attempts += 1

        # Strong concepts from this test
        for concept in r.strong_concepts:
            ev = evidence[concept]
            ev.test_percent = (ev.test_percent * ev.test_attempts + 100) / (ev.test_attempts + 1)
            ev.test_attempts += 1
            ev.test_correct += 1

        if is_recent:
            recent_summaries.append({
                "test_id":  r.test_id,
                "date":     r.finished_at[:10] if r.finished_at else "",
                "percent":  r.percent,
                "passed":   r.passed,
                "weak":     r.weak_concepts[:3],
                "strong":   r.strong_concepts[:3],
            })

    ctx.recent_test_results = sorted(
        recent_summaries, key=lambda x: x["date"], reverse=True
    )[:5]


def _ingest_sessions(
    space_dir: Path,
    evidence: dict[str, ConceptEvidence],
    cutoff: datetime,
    ctx: LearnerContext,
) -> None:
    """Read .spaces/sessions.jsonl — self-report, quicktests, stuck_on, breakthroughs."""
    from sarthak.spaces.session_tracker import load_sessions

    sessions = load_sessions(space_dir, limit=100)
    depth_scores: list[float] = []
    hour_depths: dict[str, list[float]] = defaultdict(list)

    for s in sessions:
        try:
            started = s.started_at
            if started.tzinfo is None:
                started = started.replace(tzinfo=timezone.utc)
        except Exception:
            continue

        is_recent = started >= cutoff
        concept = s.concept.strip()

        if concept:
            ev = evidence[concept]

            # Self-report
            if s.self_report.understanding_rating:
                ev.understanding_ratings.append(s.self_report.understanding_rating)
            if s.self_report.task_completed:
                ev.times_studied += 1
                if "quicktest" in s.task_id.lower() or s.signals.active_seconds < 600:
                    ev.quicktest_attempts += 1
                    if s.self_report.understanding_rating >= 3:
                        ev.quicktest_passed += 1
            for stuck in s.self_report.stuck_on:
                evidence[stuck].times_stuck += 1
            if s.self_report.breakthrough:
                ev.breakthroughs.append(s.self_report.breakthrough)
                if is_recent:
                    ctx.recent_breakthroughs.append(
                        f"{concept}: {s.self_report.breakthrough}"
                    )

        if is_recent:
            ctx.total_sessions_in_window += 1
            depth_scores.append(s.signals.depth_score)
            hour = started.hour
            bracket = (
                "morning" if 6 <= hour < 12 else
                "afternoon" if 12 <= hour < 18 else
                "evening" if 18 <= hour < 24 else "night"
            )
            hour_depths[bracket].append(s.signals.depth_score)

    if depth_scores:
        ctx.avg_session_depth = statistics.mean(depth_scores)
    if hour_depths:
        ctx.most_productive_time = max(
            hour_depths, key=lambda b: statistics.mean(hour_depths[b])
        )


def _ingest_rag_index(
    space_dir: Path,
    evidence: dict[str, ConceptEvidence],
    ctx: LearnerContext,
) -> None:
    """
    Read RAG mtimes.json to see what files exist and were recently touched.
    Maps file names to concepts via fuzzy matching (not expensive).
    """
    import json
    import time

    mtime_path = space_dir / ".sarthak_rag" / "mtimes.json"
    if not mtime_path.exists():
        mtime_path = space_dir / ".spaces" / "mtimes.json"
    if not mtime_path.exists():
        return

    try:
        mtimes = json.loads(mtime_path.read_text(encoding="utf-8", errors="replace"))
    except Exception:
        return

    recent_cutoff = time.time() - 14 * 86400
    all_concepts = set(evidence.keys())

    for rel_path, mtime in mtimes.items():
        # Try to infer which concept this file relates to
        path_lower = rel_path.lower().replace("/", " ").replace("_", " ").replace("-", " ")
        matched_concept = ""
        for concept in all_concepts:
            if concept.lower() in path_lower:
                matched_concept = concept
                break

        if matched_concept:
            evidence[matched_concept].rag_file_count += 1

        if mtime >= recent_cutoff:
            ext = Path(rel_path).suffix.lower()
            ctx.recent_reading.append(ReadingActivity(
                file_path=rel_path,
                concept_hint=matched_concept,
                modified_at=mtime,
                file_type=ext,
            ))

    # Sort by most recently modified
    ctx.recent_reading.sort(key=lambda r: r.modified_at, reverse=True)
    ctx.recent_reading = ctx.recent_reading[:10]


# ── SRS due computation ────────────────────────────────────────────────────────

def _compute_srs_due(
    evidence: dict[str, ConceptEvidence],
    profile: SpaceProfile,
    cutoff: datetime,
) -> list[str]:
    """
    Determine which concepts need review based on actual evidence quality.
    NOTE: call _append_failed_code_run_srs() after this for activity-store signals.
    """
    due: list[str] = []
    mastered = set(profile.learner.mastered_concepts)

    for concept in mastered:
        ev = evidence.get(concept)
        if ev is None:
            due.append(concept)
            continue

        has_recent_note = False
        if ev.last_note_date:
            try:
                note_date = datetime.fromisoformat(ev.last_note_date)
                if note_date.tzinfo is None:
                    note_date = note_date.replace(tzinfo=timezone.utc)
                has_recent_note = note_date >= cutoff
            except Exception:
                pass

        if ev.times_stuck >= 2:
            due.append(concept)
        elif ev.test_attempts >= 2 and ev.test_percent < 50:
            due.append(concept)
        elif not has_recent_note and ev.note_count < 2 and ev.times_studied < 2:
            due.append(concept)

    for concept in profile.learner.struggling_concepts:
        if concept not in due:
            due.append(concept)

    return due[:5]

# ── Prompt builder ─────────────────────────────────────────────────────────────

def learner_context_for_prompt(ctx: LearnerContext) -> str:
    """
    Compact Markdown summary of LearnerContext — inject directly into LLM prompts
    for curriculum planning, digest generation, and recommendations.
    """
    lines = [f"## Learner Context (last {ctx.days_window} days)", ""]

    if ctx.strong_concepts:
        lines.append(f"**Strong** (high confidence): {', '.join(ctx.strong_concepts[:6])}")
    if ctx.weak_concepts:
        lines.append(f"**Weak** (needs work): {', '.join(ctx.weak_concepts[:6])}")
    if ctx.in_progress_concepts:
        lines.append(f"**In Progress**: {', '.join(ctx.in_progress_concepts[:5])}")

    if ctx.srs_due_by_evidence:
        lines.append(f"**Review Due**: {', '.join(ctx.srs_due_by_evidence[:4])}")

    lines.append("")

    if ctx.recent_notes:
        lines.append(f"**Notes written this period**: {ctx.notes_written_total} "
                     f"({len(ctx.notes_concepts_covered)} concepts covered)")
        for note in ctx.recent_notes[:3]:
            lines.append(f"- [{note['concept']}] {note['date']}: {note['snippet'][:100]}…")
        lines.append("")

    if ctx.recent_test_results:
        lines.append("**Recent test performance**:")
        for t in ctx.recent_test_results[:3]:
            status = "PASS" if t["passed"] else "FAIL"
            lines.append(
                f"- {t['date']} [{status}] {t['percent']}%"
                + (f" — weak: {', '.join(t['weak'][:2])}" if t["weak"] else "")
                + (f" — strong: {', '.join(t['strong'][:2])}" if t["strong"] else "")
            )
        lines.append("")

    if ctx.recent_breakthroughs:
        lines.append("**Recent breakthroughs**:")
        for b in ctx.recent_breakthroughs[:3]:
            lines.append(f"- {b}")
        lines.append("")

    if ctx.most_productive_time:
        lines.append(f"**Most productive time**: {ctx.most_productive_time}")
    if ctx.avg_session_depth:
        lines.append(f"**Avg session depth**: {ctx.avg_session_depth:.2f}/1.0")

    if ctx.recent_reading:
        recently_read = [r.file_path for r in ctx.recent_reading[:5]]
        lines.append(f"**Recently accessed files**: {', '.join(recently_read)}")

    return "\n".join(lines)
