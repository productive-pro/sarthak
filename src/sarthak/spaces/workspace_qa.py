"""
Sarthak Spaces — Workspace Q&A via pydantic-ai agent.

Fully agent + tools + skills based. No rule-based intent routing.
The LLM decides which tools to call based on tool docstrings and user skills.

Public API:
    answer_workspace_question(space_dir, question, history) -> str
"""
from __future__ import annotations

import asyncio
import urllib.parse
from pathlib import Path

from pydantic_ai import Agent, RunContext

from sarthak.core.logging import get_logger

log = get_logger(__name__)
_SQL_KEYWORDS_BLOCKLIST = ("ATTACH", "PRAGMA", "LOAD_EXTENSION", "VACUUM")
_SQL_MAX_LENGTH = 4000


# ── Build the agent lazily (so model config is read at runtime) ────────────────

_agent: Agent | None = None


def _get_agent() -> Agent:
    global _agent
    if _agent is not None:
        return _agent

    from sarthak.features.ai.agents._base import build_pydantic_model, resolve_provider_model
    from sarthak.features.ai.skills import build_context_block, list_skills

    provider, model_name = resolve_provider_model()
    model = build_pydantic_model(provider, model_name)

    skills_block = build_context_block(list_skills())
    system = _BASE_SYSTEM
    if skills_block:
        system = f"{system}\n\n{skills_block}"

    agent: Agent[Path, str] = Agent(
        model,
        output_type=str,
        deps_type=Path,          # space_dir passed as deps
        system_prompt=system,
        retries=1,
    )

    # ── Register tools ─────────────────────────────────────────────────────────

    @agent.tool
    async def sql_query(ctx: RunContext[Path], sql: str) -> str:
        """
        Execute a read-only SELECT query on the space's sarthak.db.
        Tables: notes, quicktests, roadmap, digest_cache.
        Always SELECT — never mutate.
        """
        import aiosqlite
        db_path = ctx.deps / ".spaces" / "sarthak.db"
        if not db_path.exists():
            return "No sarthak.db found — space may not be initialised."
        sql = sql.strip()
        if not sql:
            return "SQL query is empty."
        if len(sql) > _SQL_MAX_LENGTH:
            return f"SQL query too long ({_SQL_MAX_LENGTH} chars max)."
        upper_sql = sql.upper()
        if not upper_sql.startswith("SELECT"):
            return "Only SELECT queries are allowed."
        if ";" in sql.rstrip(";"):
            return "Only single-statement SELECT queries are allowed."
        if any(keyword in upper_sql for keyword in _SQL_KEYWORDS_BLOCKLIST):
            return "That SQL feature is not allowed."
        try:
            read_only_uri = f"file:{urllib.parse.quote(str(db_path))}?mode=ro"
            async with aiosqlite.connect(read_only_uri, uri=True) as db:
                db.row_factory = aiosqlite.Row
                async with db.execute(sql) as cur:
                    rows = await cur.fetchmany(50)
                if not rows:
                    return f"No rows returned.\nSQL: `{sql}`"
                cols = [d[0] for d in cur.description]
                lines = [" | ".join(cols), "-" * 40]
                lines += [
                    " | ".join(str(row[c])[:500] for c in cols)
                    for row in rows
                ]
                return "```\n" + "\n".join(lines) + "\n```"
        except Exception as exc:
            return f"SQL error: {exc}"

    @agent.tool
    async def get_notes(ctx: RunContext[Path], concept_filter: str = "", limit: int = 20) -> str:
        """
        List notes from the space DB. Optionally filter by concept title/id.
        Returns titles, types, and body excerpts.
        """
        try:
            from sarthak.spaces.roadmap.db import RoadmapDB
            db = RoadmapDB(ctx.deps)
            await db.init()
            notes = await db.list_notes()
        except Exception as exc:
            return f"Could not read notes: {exc}"
        if not notes:
            return "No notes in this space yet."
        if concept_filter:
            cf = concept_filter.lower()
            notes = [n for n in notes if cf in (n.title or "").lower()
                     or cf in (n.concept_id or "").lower()
                     or cf in (n.body_md or "").lower()]
        if not notes:
            return f"No notes matching '{concept_filter}'."
        lines = [f"**{len(notes)} note(s)**:"]
        for n in notes[:limit]:
            snippet = (n.body_md or "")[:100].replace("\n", " ")
            lines.append(f"- **{n.title}** [{n.type}] — {snippet}…")
        return "\n".join(lines)

    @agent.tool
    async def rag_search(ctx: RunContext[Path], query: str, top_k: int = 5) -> str:
        """
        Semantic search over indexed workspace files.
        Returns file:line references with relevant text excerpts.
        """
        from sarthak.spaces.rag import search_space
        return await search_space(ctx.deps, query, top_k=top_k)

    @agent.tool
    async def get_sessions(ctx: RunContext[Path], days: int = 14) -> str:
        """
        Return session history and summary (streak, recent concepts, depth scores).
        """
        try:
            from sarthak.spaces.session_tracker import load_sessions
            sessions = load_sessions(ctx.deps, limit=50)
        except Exception as exc:
            return f"Could not read sessions: {exc}"
        if not sessions:
            return "No session history found."
        from datetime import datetime, timedelta, timezone
        cutoff = datetime.now(timezone.utc) - timedelta(days=days)
        recent = [s for s in sessions if hasattr(s, "started_at") and
                  s.started_at.replace(tzinfo=timezone.utc) >= cutoff]
        lines = [f"**{len(recent)} sessions in last {days} days** (of {len(sessions)} total):"]
        for s in recent[:15]:
            mins = round(getattr(s, "active_seconds", getattr(s.signals, "active_seconds", 0)) / 60, 1) if hasattr(s, "signals") else "?"
            depth = getattr(s.signals, "depth_score", "?") if hasattr(s, "signals") else "?"
            lines.append(f"- {getattr(s, 'started_at', '?')} | {getattr(s, 'concept', '?')} | {mins}min | depth {depth}")
        return "\n".join(lines)

    @agent.tool
    async def get_concepts(ctx: RunContext[Path]) -> str:
        """
        Return learner's concept mastery: mastered list, struggling list, XP, level, streak.
        """
        from sarthak.spaces.store import load_profile
        profile = await asyncio.to_thread(load_profile, ctx.deps)
        if not profile:
            return "No profile found."
        lp = profile.learner
        lines = [
            f"**Domain:** {profile.domain}",
            f"**Level:** {lp.skill_level.value} | **XP:** {lp.xp} | **Streak:** {lp.streak_days}d",
            f"**Mastered ({len(lp.mastered_concepts)}):** {', '.join(lp.mastered_concepts[-10:]) or 'none'}",
            f"**Struggling ({len(lp.struggling_concepts)}):** {', '.join(lp.struggling_concepts[:10]) or 'none'}",
        ]
        return "\n".join(lines)

    @agent.tool
    async def get_srs_due(ctx: RunContext[Path]) -> str:
        """Return SRS cards currently due for review."""
        try:
            from sarthak.spaces.roadmap.srs import get_due
            db_path = str(ctx.deps / ".spaces" / "sarthak.db")
            due = await get_due(db_path)
        except Exception as exc:
            return f"Could not read SRS: {exc}"
        if not due:
            return "No SRS cards due right now. All caught up!"
        lines = [f"**{len(due)} card(s) due:**"]
        for card in due[:20]:
            label = getattr(card, "concept", None) or getattr(card, "card_id", "?")
            lines.append(f"- {label}")
        return "\n".join(lines)

    @agent.tool
    async def get_activity(ctx: RunContext[Path], days: int = 30) -> str:
        """Return activity summary: code runs, tests, quicktests, notes from last N days."""
        try:
            from sarthak.storage.activity_store import query_activity
            rows = await query_activity(space_dir=str(ctx.deps), days=days, limit=200)
        except Exception as exc:
            return f"Could not read activity: {exc}"
        if not rows:
            return f"No activity in last {days} days."
        from collections import Counter
        type_counts = Counter(r.get("activity_type", "?") for r in rows)
        concepts = [r.get("concept_title", "") for r in rows if r.get("concept_title")]
        lines = [f"**Activity ({len(rows)} events, last {days}d):**"]
        for atype, count in sorted(type_counts.items(), key=lambda x: -x[1]):
            lines.append(f"  - {atype}: {count}")
        if concepts:
            top = Counter(concepts).most_common(5)
            lines.append("**Most active concepts:**")
            for c, n in top:
                lines.append(f"  - {c}: {n}")
        return "\n".join(lines)

    @agent.tool
    async def get_insights(ctx: RunContext[Path]) -> str:
        """
        Read the latest Optimal_Learn.md and recommendations.md.
        These contain the workspace analyser's current recommendations and focus areas.
        """
        parts = []
        optimal = ctx.deps / ".spaces" / "Optimal_Learn.md"
        if optimal.exists():
            parts.append(optimal.read_text(encoding="utf-8")[:3000])
        recs = ctx.deps / ".spaces" / "recommendations.md"
        if recs.exists():
            parts.append(recs.read_text(encoding="utf-8"))
        if not parts:
            return "No workspace insights yet. The workspace analyser runs every 30 minutes."
        return "\n\n---\n\n".join(parts)

    _agent = agent
    return _agent


_BASE_SYSTEM = """You are a Sarthak workspace assistant with direct access to the learner's workspace data.

Use the available tools to answer questions about sessions, notes, concepts, SRS cards, activity, and workspace insights.
Never guess or make up data — always query via tools.
Be concise, specific, and format responses in Markdown."""


async def answer_workspace_question(
    space_dir: Path,
    question: str,
    history: list[dict] | None = None,
) -> str:
    """Run the workspace Q&A agent. Fully agent+tools+skills based — no intent routing."""
    space_dir = Path(space_dir)
    if not (space_dir / ".spaces").exists():
        return (
            "No Sarthak Space found at this directory. "
            "Run `sarthak spaces init` to initialise one."
        )

    # Rebuild agent each call so skills changes are picked up immediately
    global _agent
    _agent = None
    agent = _get_agent()

    try:
        result = await agent.run(question, deps=space_dir)
        return result.output
    except Exception as exc:
        log.warning("workspace_qa_agent_failed", error=str(exc))
        return f"Could not answer: {exc}"
