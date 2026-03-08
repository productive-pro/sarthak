"""
Sarthak AI — Storage helpers (read + write, SQLite).
Single module combining read.py and write.py.
Both modules remain as thin re-export shims for backwards compatibility.
"""
from __future__ import annotations

import json
from datetime import date as _date, datetime as _dt

from .db import connect


# ══════════════════════════════════════════════════════════════════════════════
# Read helpers
# ══════════════════════════════════════════════════════════════════════════════

async def get_chat_history(session_id: str, limit: int = 40) -> list[dict]:
    """Return messages for a session, oldest first."""
    async with connect() as db:
        async with db.execute(
            "SELECT session_id, ts, role, content FROM chat_history "
            "WHERE session_id=? ORDER BY ts ASC LIMIT ?",
            (session_id, limit),
        ) as cur:
            rows = await cur.fetchall()
    return [dict(r) for r in rows]


async def get_chat_sessions(limit: int = 20) -> list[dict]:
    """Return recent sessions ordered by last message time."""
    async with connect() as db:
        async with db.execute(
            """
            SELECT session_id,
                   MAX(ts)   AS last_ts,
                   COUNT(*)  AS msg_count
            FROM chat_history
            GROUP BY session_id
            ORDER BY last_ts DESC
            LIMIT ?
            """,
            (limit,),
        ) as cur:
            rows = await cur.fetchall()
    return [dict(r) for r in rows]


async def get_latest_chat_session_id() -> str | None:
    """Return the session_id with the most recent message, or None."""
    async with connect() as db:
        async with db.execute(
            "SELECT session_id FROM chat_history ORDER BY ts DESC LIMIT 1"
        ) as cur:
            row = await cur.fetchone()
    return row["session_id"] if row else None


async def get_daily_summary(target_date) -> dict | None:
    """Return the daily summary row for a date (YYYY-MM-DD)."""
    if hasattr(target_date, "isoformat"):
        date_str = target_date.isoformat()
    else:
        date_str = str(target_date)
    async with connect() as db:
        async with db.execute(
            """
            SELECT date, summary, top_apps, productive_mins, idle_mins,
                   model_used, generated_at
            FROM daily_summaries
            WHERE date=?
            """,
            (date_str,),
        ) as cur:
            row = await cur.fetchone()
    return dict(row) if row else None


async def list_daily_summaries(limit: int = 90) -> list[dict]:
    """Return recent daily summaries (newest first)."""
    async with connect() as db:
        async with db.execute(
            """
            SELECT date, summary, top_apps, productive_mins, idle_mins,
                   model_used, generated_at
            FROM daily_summaries
            ORDER BY date DESC
            LIMIT ?
            """,
            (limit,),
        ) as cur:
            rows = await cur.fetchall()
    return [dict(r) for r in rows]


async def get_saved_tips(limit: int = 100) -> list[dict]:
    """Return saved tips (newest first)."""
    async with connect() as db:
        async with db.execute(
            "SELECT id, ts, tip FROM saved_tips ORDER BY ts DESC LIMIT ?",
            (limit,),
        ) as cur:
            rows = await cur.fetchall()
    return [dict(r) for r in rows]


async def get_alerts(limit: int = 200) -> list[dict]:
    """Return recent alerts (newest first)."""
    async with connect() as db:
        async with db.execute(
            """
            SELECT id, ts, level, source, message, details, read
            FROM alerts
            ORDER BY ts DESC
            LIMIT ?
            """,
            (limit,),
        ) as cur:
            rows = await cur.fetchall()
    return [dict(r) for r in rows]


# ══════════════════════════════════════════════════════════════════════════════
# Write helpers
# ══════════════════════════════════════════════════════════════════════════════

async def write_chat_message(session_id: str, role: str, content: str) -> None:
    """Append a user/assistant chat message."""
    async with connect() as db:
        await db.execute(
            "INSERT INTO chat_history (session_id, role, content) VALUES (?, ?, ?)",
            (session_id, role, content),
        )
        await db.commit()


async def write_alert(level: str, source: str, message: str, details: dict | None = None) -> None:
    """Append an alert."""
    async with connect() as db:
        await db.execute(
            "INSERT INTO alerts (level, source, message, details) VALUES (?, ?, ?, ?)",
            (level, source, message, json.dumps(details or {})),
        )
        await db.commit()


async def write_daily_summary(
    date,
    summary: str,
    top_apps: list,
    productive_mins: int = 0,
    idle_mins: int = 0,
    model_used: str = "",
) -> None:
    """Upsert AI-generated daily summary."""
    if isinstance(date, str):
        date_str = date
    elif isinstance(date, _dt):
        date_str = date.date().isoformat()
    elif isinstance(date, _date):
        date_str = date.isoformat()
    else:
        date_str = str(date)

    async with connect() as db:
        await db.execute(
            """
            INSERT INTO daily_summaries
                (date, summary, top_apps, productive_mins, idle_mins, model_used,
                 generated_at)
            VALUES (?, ?, ?, ?, ?, ?, strftime('%Y-%m-%dT%H:%M:%fZ','now'))
            ON CONFLICT(date) DO UPDATE SET
                summary         = excluded.summary,
                top_apps        = excluded.top_apps,
                productive_mins = excluded.productive_mins,
                idle_mins       = excluded.idle_mins,
                model_used      = excluded.model_used,
                generated_at    = excluded.generated_at
            """,
            (date_str, summary, json.dumps(top_apps), productive_mins, idle_mins, model_used),
        )
        await db.commit()


async def save_tip(tip: str) -> None:
    """Insert a saved tip."""
    async with connect() as db:
        await db.execute(
            "INSERT INTO saved_tips (tip) VALUES (?)",
            (tip,),
        )
        await db.commit()


async def delete_tip(tip_id: int) -> None:
    """Delete a saved tip by id."""
    async with connect() as db:
        await db.execute("DELETE FROM saved_tips WHERE id=?", (tip_id,))
        await db.commit()
