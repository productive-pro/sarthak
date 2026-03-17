"""
Sarthak Spaces — Spaced Repetition System.

SM-2 algorithm (pure Python, no LLM).

Card types:
  concept   — a roadmap concept unit (scheduled from digest evidence)
  note      — a specific saved note (scheduled when note is created)
  quicktest — a micro-task (original behaviour, kept for compat)

New table: srs_cards  (supersedes quicktest_srs for new cards)
Old table: quicktest_srs  (kept, migrated on first init)

Public API:
    get_due(db_path)                           → list[SRSCard]
    record_review(db_path, card_id, grade)     → SRSCard
    upsert_card(db_path, card_id, card_type,   → SRSCard
                concept, reason, initial_grade)
    card_status(db_path, card_id)              → SRSCard | None
    sync_from_digest(db_path, digest_signals)  → int  (cards upserted)
    sync_note_card(db_path, note_id, concept)  → SRSCard
"""

from __future__ import annotations

import asyncio as _asyncio
import math
from datetime import date, timedelta
from pathlib import Path
from typing import Literal

import aiosqlite

from sarthak.core.logging import get_logger

log = get_logger(__name__)

CardType = Literal["concept", "note", "quicktest"]

# ── Schema ─────────────────────────────────────────────────────────────────────

_SCHEMA = """
PRAGMA journal_mode=WAL;
PRAGMA synchronous=NORMAL;
PRAGMA foreign_keys=ON;

CREATE TABLE IF NOT EXISTS srs_cards (
    card_id      TEXT PRIMARY KEY,
    card_type    TEXT NOT NULL DEFAULT 'concept',
    concept      TEXT NOT NULL DEFAULT '',
    reason       TEXT NOT NULL DEFAULT '',   -- why this card exists
    easiness     REAL    NOT NULL DEFAULT 2.5,
    interval     INTEGER NOT NULL DEFAULT 1,
    repetitions  INTEGER NOT NULL DEFAULT 0,
    next_due     TEXT    NOT NULL,
    last_grade   INTEGER,
    total_reviews INTEGER NOT NULL DEFAULT 0,
    created_at   TEXT NOT NULL DEFAULT (date('now'))
);

CREATE INDEX IF NOT EXISTS srs_cards_due ON srs_cards(next_due);
CREATE INDEX IF NOT EXISTS srs_cards_due_order ON srs_cards(next_due, repetitions);
CREATE INDEX IF NOT EXISTS srs_cards_concept ON srs_cards(concept);

CREATE TABLE IF NOT EXISTS quicktest_srs (
    qt_id        TEXT PRIMARY KEY,
    easiness     REAL    NOT NULL DEFAULT 2.5,
    interval     INTEGER NOT NULL DEFAULT 1,
    repetitions  INTEGER NOT NULL DEFAULT 0,
    next_due     TEXT    NOT NULL,
    last_grade   INTEGER,
    total_reviews INTEGER NOT NULL DEFAULT 0
);
"""


# ── SRSCard ────────────────────────────────────────────────────────────────────


class SRSCard:
    __slots__ = (
        "card_id",
        "card_type",
        "concept",
        "reason",
        "easiness",
        "interval",
        "repetitions",
        "next_due",
        "last_grade",
        "total_reviews",
    )

    def __init__(
        self,
        card_id: str,
        card_type: str = "concept",
        concept: str = "",
        reason: str = "",
        easiness: float = 2.5,
        interval: int = 1,
        repetitions: int = 0,
        next_due: str = "",
        last_grade: int | None = None,
        total_reviews: int = 0,
        # legacy compat — old rows have qt_id instead of card_id
        qt_id: str | None = None,
        **_: object,
    ) -> None:
        self.card_id = card_id or qt_id or ""
        self.card_type = card_type
        self.concept = concept or self.card_id
        self.reason = reason
        self.easiness = easiness
        self.interval = interval
        self.repetitions = repetitions
        self.next_due = next_due or str(date.today())
        self.last_grade = last_grade
        self.total_reviews = total_reviews

    def to_dict(self) -> dict:
        return {
            "card_id": self.card_id,
            "card_type": self.card_type,
            "concept": self.concept,
            "reason": self.reason,
            "easiness": round(self.easiness, 3),
            "interval": self.interval,
            "repetitions": self.repetitions,
            "next_due": self.next_due,
            "last_grade": self.last_grade,
            "total_reviews": self.total_reviews,
        }


# ── SM-2 core ─────────────────────────────────────────────────────────────────


def _sm2(card: SRSCard, grade: int) -> SRSCard:
    g = max(0, min(5, grade))
    new_ef = card.easiness + (0.1 - (5 - g) * (0.08 + (5 - g) * 0.02))
    new_ef = max(1.3, new_ef)

    if g < 3:
        new_reps = 0
        new_interval = 1
    else:
        new_reps = card.repetitions + 1
        if new_reps == 1:
            new_interval = 1
        elif new_reps == 2:
            new_interval = 6
        else:
            new_interval = math.ceil(card.interval * new_ef)

    next_due = str(date.today() + timedelta(days=new_interval))
    return SRSCard(
        card_id=card.card_id,
        card_type=card.card_type,
        concept=card.concept,
        reason=card.reason,
        easiness=new_ef,
        interval=new_interval,
        repetitions=new_reps,
        next_due=next_due,
        last_grade=g,
        total_reviews=card.total_reviews + 1,
    )


def _initial_interval(initial_grade: int) -> int:
    """Starting interval based on evidence quality (0=unknown, 5=strong)."""
    if initial_grade >= 4:
        return 4  # already known well — review in 4 days
    if initial_grade == 3:
        return 2
    if initial_grade == 2:
        return 1
    return 1  # weak / unknown — review tomorrow


# ── DB helpers ─────────────────────────────────────────────────────────────────
#
# Connection pool: one persistent (conn, asyncio.Lock) per resolved db_path.
# Eliminates the critical bug where _open() opened a fresh connection every
# call and leaked it (callers never closed it — they used it as a ctx manager
# but aiosqlite.Connection.__aexit__ does NOT close the connection).

_POOL: dict[str, tuple[aiosqlite.Connection, _asyncio.Lock]] = {}
_POOL_LOCK: _asyncio.Lock | None = None   # lazy — created on first use inside event loop
_INIT_DONE: set[str] = set()


def _get_pool_lock() -> _asyncio.Lock:
    """Return the global pool lock, creating it lazily inside the running event loop."""
    global _POOL_LOCK
    if _POOL_LOCK is None:
        _POOL_LOCK = _asyncio.Lock()
    return _POOL_LOCK


async def _ensure_schema(db: aiosqlite.Connection) -> None:
    await db.executescript(_SCHEMA)
    await db.commit()


async def _migrate_quicktest_srs(db: aiosqlite.Connection) -> None:
    """Migrate old quicktest_srs rows into srs_cards as card_type='quicktest'."""
    async with db.execute("SELECT COUNT(*) FROM quicktest_srs") as cur:
        row = await cur.fetchone()
    if not row or row[0] == 0:
        return
    await db.execute("""
        INSERT OR IGNORE INTO srs_cards
            (card_id, card_type, concept, reason,
             easiness, interval, repetitions, next_due, last_grade, total_reviews)
        SELECT
            qt_id, 'quicktest', qt_id, 'migrated from quicktest_srs',
            easiness, interval, repetitions, next_due, last_grade, total_reviews
        FROM quicktest_srs
    """)
    await db.commit()


async def _get_conn(db_path: str) -> tuple[aiosqlite.Connection, _asyncio.Lock]:
    """Return the pooled connection and write lock for a database path."""
    norm_path = str(Path(db_path).resolve())

    async with _get_pool_lock():
        if norm_path not in _POOL:
            conn = await aiosqlite.connect(norm_path)
            conn.row_factory = aiosqlite.Row
            await conn.execute("PRAGMA journal_mode=WAL")
            await conn.execute("PRAGMA synchronous=NORMAL")
            await conn.execute("PRAGMA foreign_keys=ON")
            await conn.execute("PRAGMA cache_size=-8000")
            _POOL[norm_path] = (conn, _asyncio.Lock())

    conn, lock = _POOL[norm_path]

    if norm_path not in _INIT_DONE:
        async with lock:
            if norm_path not in _INIT_DONE:
                try:
                    await _ensure_schema(conn)
                    await _migrate_quicktest_srs(conn)
                    _INIT_DONE.add(norm_path)
                except Exception:
                    # Remove broken entry so next call retries
                    async with _get_pool_lock():
                        _POOL.pop(norm_path, None)
                    raise

    return conn, lock


# ── Public API ─────────────────────────────────────────────────────────────────


async def get_due(db_path: str) -> list[SRSCard]:
    """Return all cards due today or overdue, ordered by urgency."""
    today = str(date.today())
    db, _ = await _get_conn(db_path)
    async with db.execute(
        "SELECT * FROM srs_cards WHERE next_due <= ? ORDER BY next_due, repetitions",
        (today,),
    ) as cur:
        rows = await cur.fetchall()
    return [SRSCard(**dict(r)) for r in rows]


async def card_status(db_path: str, card_id: str) -> SRSCard | None:
    db, _ = await _get_conn(db_path)
    async with db.execute("SELECT * FROM srs_cards WHERE card_id=?", (card_id,)) as cur:
        row = await cur.fetchone()
    return SRSCard(**dict(row)) if row else None


async def record_review(db_path: str, card_id: str, grade: int) -> SRSCard:
    """Apply SM-2 to card_id. Grade 0-5 (0-2=fail, 3-5=pass). Upserts row."""
    existing = await card_status(db_path, card_id)
    card = existing or SRSCard(card_id=card_id)
    updated = _sm2(card, grade)
    db, lock = await _get_conn(db_path)
    async with lock:
        await db.execute(
            """
            INSERT INTO srs_cards
                 (card_id, card_type, concept, reason,
                  easiness, interval, repetitions, next_due, last_grade, total_reviews)
               VALUES (?,?,?,?,?,?,?,?,?,?)
               ON CONFLICT(card_id) DO UPDATE SET
                 easiness=excluded.easiness, interval=excluded.interval,
                 repetitions=excluded.repetitions, next_due=excluded.next_due,
                 last_grade=excluded.last_grade,
                 total_reviews=excluded.total_reviews
            """,
            (
                updated.card_id,
                updated.card_type,
                updated.concept,
                updated.reason,
                updated.easiness,
                updated.interval,
                updated.repetitions,
                updated.next_due,
                updated.last_grade,
                updated.total_reviews,
            ),
        )
        await db.commit()
    log.info(
        "srs_review_recorded",
        card_id=card_id,
        grade=grade,
        next_due=updated.next_due,
    )
    return updated


async def upsert_card(
    db_path: str,
    card_id: str,
    card_type: CardType,
    concept: str,
    reason: str = "",
    initial_grade: int = 0,
) -> SRSCard:
    """
    Create a new SRS card or reset an existing one.

    If the card exists and already has repetitions > 0, only reset
    (shorten the interval) when initial_grade indicates weakness (< 3).
    New cards start with an interval derived from initial_grade.
    """
    existing = await card_status(db_path, card_id)

    if existing and existing.repetitions > 0 and initial_grade >= 3:
        # Card exists and learner is not struggling — leave it alone
        return existing

    interval = _initial_interval(initial_grade)
    next_due = str(date.today() + timedelta(days=interval))

    if existing and initial_grade < 3:
        # Reset: weak evidence found — review soon
        new_card = SRSCard(
            card_id=card_id,
            card_type=card_type,
            concept=concept,
            reason=reason,
            easiness=max(1.3, existing.easiness - 0.2),
            interval=interval,
            repetitions=0,
            next_due=next_due,
            last_grade=existing.last_grade,
            total_reviews=existing.total_reviews,
        )
    else:
        new_card = SRSCard(
            card_id=card_id,
            card_type=card_type,
            concept=concept,
            reason=reason,
            easiness=2.5,
            interval=interval,
            repetitions=0,
            next_due=next_due,
        )

    db, lock = await _get_conn(db_path)
    async with lock:
        await db.execute(
            """INSERT INTO srs_cards
                 (card_id, card_type, concept, reason,
                  easiness, interval, repetitions, next_due, last_grade, total_reviews)
               VALUES (?,?,?,?,?,?,?,?,?,?)
               ON CONFLICT(card_id) DO UPDATE SET
                 card_type=excluded.card_type, concept=excluded.concept,
                 reason=excluded.reason,
                 easiness=excluded.easiness, interval=excluded.interval,
                 repetitions=excluded.repetitions, next_due=excluded.next_due,
                 total_reviews=excluded.total_reviews""",
            (
                new_card.card_id,
                new_card.card_type,
                new_card.concept,
                new_card.reason,
                new_card.easiness,
                new_card.interval,
                new_card.repetitions,
                new_card.next_due,
                new_card.last_grade,
                new_card.total_reviews,
            ),
        )
        await db.commit()

    log.info(
        "srs_card_upserted",
        card_id=card_id,
        card_type=card_type,
        concept=concept,
        interval=interval,
    )
    return new_card


async def sync_note_card(db_path: str, note_id: str, concept: str) -> SRSCard:
    """
    Called whenever a note is saved for a concept.
    Creates/resets the concept-level SRS card at a moderate interval
    (new note = learning happened = no need to review immediately).
    """
    card_id = f"concept:{concept}"
    return await upsert_card(
        db_path,
        card_id=card_id,
        card_type="concept",
        concept=concept,
        reason="note written",
        initial_grade=3,  # moderate: schedule review in 2 days
    )


class DigestSignals:
    """
    Distilled signals from a daily digest / LearnerContext that drive SRS scheduling.
    All fields are concept name strings.
    """

    __slots__ = (
        "weak_concepts",
        "stuck_concepts",
        "no_note_concepts",
        "test_failed_concepts",
        "strong_concepts",
        "recent_breakthroughs",
    )

    def __init__(
        self,
        weak_concepts: list[str] | None = None,
        stuck_concepts: list[str] | None = None,
        no_note_concepts: list[str] | None = None,
        test_failed_concepts: list[str] | None = None,
        strong_concepts: list[str] | None = None,
        recent_breakthroughs: list[str] | None = None,
    ) -> None:
        self.weak_concepts = weak_concepts or []
        self.stuck_concepts = stuck_concepts or []
        self.no_note_concepts = no_note_concepts or []
        self.test_failed_concepts = test_failed_concepts or []
        self.strong_concepts = strong_concepts or []
        self.recent_breakthroughs = recent_breakthroughs or []


async def sync_from_digest(db_path: str, signals: DigestSignals) -> int:
    """
    Upsert SRS cards based on digest evidence signals.

    Priority / initial_grade mapping:
      stuck (times_stuck >= 2)    → grade 0  (review tomorrow, reset easiness)
      test_failed (< 50%)         → grade 1  (review tomorrow)
      weak (confidence < 0.35)    → grade 1
      no_note (mastered but stale) → grade 2  (review in 1 day)
      strong (confidence >= 0.7)  → grade 4  (review in 4 days)
      breakthrough                → grade 4  (earned — review later)

    Returns count of cards upserted.
    """
    count = 0

    for concept in signals.stuck_concepts:
        await upsert_card(
            db_path,
            card_id=f"concept:{concept}",
            card_type="concept",
            concept=concept,
            reason="stuck in sessions",
            initial_grade=0,
        )
        count += 1

    for concept in signals.test_failed_concepts:
        if concept not in signals.stuck_concepts:
            await upsert_card(
                db_path,
                card_id=f"concept:{concept}",
                card_type="concept",
                concept=concept,
                reason="failed test",
                initial_grade=1,
            )
            count += 1

    for concept in signals.weak_concepts:
        if (
            concept not in signals.stuck_concepts
            and concept not in signals.test_failed_concepts
        ):
            await upsert_card(
                db_path,
                card_id=f"concept:{concept}",
                card_type="concept",
                concept=concept,
                reason="low mastery confidence",
                initial_grade=1,
            )
            count += 1

    for concept in signals.no_note_concepts:
        already = (
            concept in signals.stuck_concepts
            or concept in signals.test_failed_concepts
            or concept in signals.weak_concepts
        )
        if not already:
            await upsert_card(
                db_path,
                card_id=f"concept:{concept}",
                card_type="concept",
                concept=concept,
                reason="mastered but no notes",
                initial_grade=2,
            )
            count += 1

    for concept in signals.strong_concepts:
        await upsert_card(
            db_path,
            card_id=f"concept:{concept}",
            card_type="concept",
            concept=concept,
            reason="strong — spaced maintenance",
            initial_grade=4,
        )
        count += 1

    log.info("srs_digest_sync_done", cards_upserted=count)
    return count


# ── Legacy compat (quicktest_srs API) ─────────────────────────────────────────


async def srs_status(db_path: str, qt_id: str) -> SRSCard | None:
    """Legacy: look up by old quicktest ID. Falls back to srs_cards."""
    card = await card_status(db_path, qt_id)
    if card:
        return card
    # Check old quicktest_srs table
    db, _ = await _get_conn(db_path)
    async with db.execute("SELECT * FROM quicktest_srs WHERE qt_id=?", (qt_id,)) as cur:
        row = await cur.fetchone()
    if row:
        d = dict(row)
        return SRSCard(
            card_id=d["qt_id"],
            card_type="quicktest",
            concept=d["qt_id"],
            **d,
        )
    return None
