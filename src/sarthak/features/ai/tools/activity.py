"""
Activity tools — fetch events, summaries, tips.

AGENT SAFETY RULE: Agents never receive raw table rows.
Every function returns either:
  - Statistical aggregates (counts, top-N, ratios)
  - Head (first 5) + tail (last 5) rows only
  - A pre-formatted Markdown digest
Raw data that is too large or irrelevant is ALWAYS excluded from the agent prompt.
"""
from __future__ import annotations

from typing import Any

from sarthak.core.logging import get_logger

log = get_logger(__name__)


async def tool_query_activity(pool: Any, days: int = 1, limit: int = 60) -> str:
    """Return a compact learning session digest for the agent."""
    try:
        from pathlib import Path
        from sarthak.spaces.store import list_spaces
        from sarthak.spaces.session_tracker import load_sessions

        lines: list[str] = []
        spaces = list_spaces()
        for space in spaces[:5]:
            d = Path(space.get("directory", ""))
            if not d.exists():
                continue
            sessions = load_sessions(d, limit=5)
            if sessions:
                s = sessions[-1]
                lines.append(
                    f"- {space.get('name', d.name)}: last session {s.concept}, "
                    f"{s.signals.active_seconds // 60} min active"
                )
        return "\n".join(lines) if lines else "No recent space sessions found."
    except Exception as exc:
        log.error("tool_query_activity", error=str(exc))
        return f"Failed to query activity: {exc}"


async def tool_get_summary(pool: Any, date_str: str | None = None) -> str:
    """Fetch the AI-generated daily summary text for a date (default: today)."""
    try:
        from datetime import date
        from sarthak.storage.helpers import get_daily_summary

        target = date.fromisoformat(date_str) if date_str else date.today()
        row = await get_daily_summary(target)
        if not row:
            return f"No summary found for {target}."
        return row.get("summary", "No summary text.")
    except Exception as exc:
        return f"Failed to fetch summary: {exc}"


async def tool_get_tips(pool: Any, limit: int = 3) -> str:
    """Fetch the most recent saved tips/recommendations (summary only — no raw rows)."""
    try:
        from sarthak.storage.helpers import get_saved_tips
        rows = await get_saved_tips(limit=limit)
        if not rows:
            return "No tips saved yet."
        return "\n\n".join(
            f"**[{str(r.get('ts') or '')[:16]}]** {r.get('tip', '')}" for r in rows
        )
    except Exception as exc:
        return f"Failed to fetch tips: {exc}"


async def tool_save_tip(pool: Any, tip: str) -> str:
    """Persist a new tip/recommendation to the database."""
    try:
        from sarthak.storage.helpers import save_tip
        await save_tip(tip)
        return "Tip saved."
    except Exception as exc:
        return f"Failed to save tip: {exc}"
