"""
Sarthak AI — Telegram Bot with streaming responses.

Streaming: send placeholder → stream tokens via stream_dispatch() →
edit message every _STREAM_EDIT_INTERVAL seconds → final edit.

Menu tree
---------------------------------------------------------------------------
/start
  +-- Today              (dashboard: sessions today, SRS due, notes written)
  +-- Ask Sarthak        (free-text → streaming orchestrator)
  +-- Learn
  |     +-- New session / QuickTest / Evaluate / Daily digest
  +-- Progress
  |     +-- Learner status / Weak concepts / My notes / Roadmap / SRS due
  +-- Spaces
  |     +-- List / Activate / Init / Setup env
  +-- Skills
  |     +-- List / Read / New / Delete
  +-- Agents
  |     +-- List / Create / Run / Logs / Enable-Disable
  +-- Config
        +-- Change model / Edit constant / Bot info / Service status
---------------------------------------------------------------------------
"""
from __future__ import annotations

import asyncio
import time
import uuid
import warnings
from pathlib import Path
from typing import Any, Callable

import tomlkit
from telegram import (
    BotCommand,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    MenuButtonCommands,
    Update,
)
from telegram.error import BadRequest, RetryAfter
from telegram.ext import (
    Application,
    CallbackQueryHandler,
    CommandHandler,
    ContextTypes,
    ConversationHandler,
    MessageHandler,
    filters,
)

from sarthak.core.constants import TELEGRAM_MESSAGE_LIMIT
from sarthak.core.logging import get_logger
from sarthak.core.config import load_config

log = get_logger(__name__)


async def send_message(text: str) -> None:
    """Standalone sender — used by scheduler/digest to push without an active session."""
    cfg = load_config()
    tg = cfg.get("telegram", {})
    if not tg.get("enabled"):
        return
    from sarthak.storage.encrypt import decrypt_string
    raw_token = tg.get("bot_token", "")
    if not raw_token:
        return
    token = decrypt_string(raw_token) if raw_token.startswith("ENC:") else raw_token
    raw_id = tg.get("allowed_user_id")
    if not raw_id:
        return
    chat_id = int(str(raw_id).strip())
    from telegram import Bot
    async with Bot(token=token) as bot:
        for chunk_start in range(0, len(text), TELEGRAM_MESSAGE_LIMIT):
            chunk = text[chunk_start:chunk_start + TELEGRAM_MESSAGE_LIMIT]
            try:
                await bot.send_message(chat_id=chat_id, text=chunk, parse_mode="Markdown")
            except BadRequest:
                # Markdown parse failed — send as plain text
                try:
                    await bot.send_message(chat_id=chat_id, text=chunk)
                except Exception as exc:
                    log.warning("send_message_chunk_failed", error=str(exc))
            except Exception as exc:
                log.warning("send_message_chunk_failed", error=str(exc))


# ── Config ────────────────────────────────────────────────────────────────────
_STREAM_EDIT_INTERVAL = 3.0

# ── Conversation states ───────────────────────────────────────────────────────
(
    ST_IDLE,
    ST_FREE_TEXT,
    ST_SKILL_READ_NAME,
    ST_SKILL_DEL_NAME,
    ST_SKILL_NEW_NAME,
    ST_SKILL_NEW_DESC,
    ST_SKILL_NEW_CONTENT,
    ST_CONST_VALUE,
    ST_SP_STATUS_DIR,
    ST_SP_INIT_DIR,
    ST_SP_INIT_TYPE,
    ST_SP_INIT_BG,
    ST_SP_INIT_NAME,
    ST_SP_ACTIVATE_DIR,
    ST_SP_EVAL_CONCEPT,
    ST_SP_EVAL_SUBMISSION,
    ST_SP_SETUP_DIR,
    ST_AG_CREATE_DESC,
    ST_AG_RUN_ID,
    ST_AG_LOGS_ID,
    ST_AG_TOGGLE_ID,
    ST_NOTE_CONCEPT,
    ST_NOTE_CONTENT,
) = range(23)

_K_SKILL_NAME    = "skill_name"
_K_SKILL_DESC    = "skill_desc"
_K_CONST_NAME    = "const_name"
_K_CHAT_SESSION  = "chat_session_id"
_K_SP_DIR        = "sp_dir"
_K_SP_TYPE       = "sp_type"
_K_SP_BG         = "sp_bg"
_K_SP_CHOICES    = "sp_choices"
_K_SP_EVAL_CONC  = "sp_eval_concept"
_K_MODEL_CHOICES = "model_choices"
_K_NOTE_CONCEPT  = "note_concept"


# ═════════════════════════════════════════════════════════════════════════════
# Utilities
# ═════════════════════════════════════════════════════════════════════════════

def _is_allowed(update: Update, allowed_id: int) -> bool:
    return update.effective_user is not None and update.effective_user.id == allowed_id


async def _deny(update: Update) -> None:
    if update.effective_message:
        await update.effective_message.reply_text("Unauthorized.")


def _trunc(text: str, limit: int = TELEGRAM_MESSAGE_LIMIT) -> str:
    return text if len(text) <= limit else text[: limit - 3] + "..."


async def _safe_edit(query, text: str, **kwargs) -> None:
    try:
        await query.edit_message_text(text, **kwargs)
    except BadRequest as exc:
        if "Message is not modified" not in str(exc):
            raise


def _new_session(ctx: ContextTypes.DEFAULT_TYPE) -> str:
    sid = str(uuid.uuid4())
    ctx.user_data[_K_CHAT_SESSION] = sid
    return sid


def _current_model(ctx: ContextTypes.DEFAULT_TYPE) -> str:
    cfg      = ctx.bot_data.get("cfg", {})
    ai       = cfg.get("ai", {})
    provider = ai.get("default_provider", "github")
    pc       = ai.get(provider, {})
    model    = (
        (pc.get("text_model") or pc.get("model") if isinstance(pc, dict) else None)
        or ai.get("default_model", "gpt-4o-mini")
    )
    return f"{provider}/{model}"


def _active_space_dir(ctx: ContextTypes.DEFAULT_TYPE) -> str:
    """Return stored space dir, or fall back to the global active space."""
    sp_dir = ctx.user_data.get(_K_SP_DIR, "")
    if sp_dir:
        return sp_dir
    try:
        from sarthak.spaces.store import get_active_space
        active = get_active_space()
        return active.get("directory", "") if active else ""
    except Exception:
        return ""


# ═════════════════════════════════════════════════════════════════════════════
# Streaming chat
# ═════════════════════════════════════════════════════════════════════════════

async def _stream_reply(
    question: str,
    ctx: ContextTypes.DEFAULT_TYPE,
    placeholder_message,
) -> str:
    from sarthak.features.channels import stream_dispatch, load_history_messages, save_chat_turn

    sid = ctx.user_data.get(_K_CHAT_SESSION)
    if not sid:
        try:
            from sarthak.storage.helpers import get_latest_chat_session_id
            sid = await get_latest_chat_session_id()
        except Exception:
            pass
    if not sid:
        sid = str(uuid.uuid4())
    ctx.user_data[_K_CHAT_SESSION] = sid

    history = await load_history_messages(sid)
    last_edit: float = 0.0
    final_reply: str = ""
    cursor_suffix    = " ▍"

    try:
        async for partial in stream_dispatch(question, session_id=sid, message_history=history):
            final_reply = partial
            now = time.monotonic()
            if now - last_edit >= _STREAM_EDIT_INTERVAL:
                try:
                    # No parse_mode during streaming — partial chunks have unclosed
                    # Markdown spans that Telegram rejects with BadRequest.
                    await placeholder_message.edit_text(
                        _trunc(final_reply + cursor_suffix))
                    last_edit = now
                except (BadRequest, RetryAfter):
                    pass
    except Exception as exc:
        log.error("stream_dispatch_failed", error=str(exc))
        final_reply = f"Error: {exc}"

    await save_chat_turn(sid, question, final_reply)

    # Final message: try Markdown, fall back to plain text
    try:
        await placeholder_message.edit_text(_trunc(final_reply), parse_mode="Markdown")
    except BadRequest:
        try:
            await placeholder_message.edit_text(_trunc(final_reply))
        except Exception:
            pass
    return final_reply


async def _handle_question(question: str, update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    if not question:
        return
    placeholder = await update.effective_message.reply_text("Thinking...")
    typing_task = asyncio.create_task(_typing_loop(update))
    try:
        await _stream_reply(question, ctx, placeholder)
    finally:
        typing_task.cancel()


async def _typing_loop(update: Update) -> None:
    while True:
        try:
            await update.effective_chat.send_action(action="typing")
        except Exception:
            pass
        await asyncio.sleep(4)


# ═════════════════════════════════════════════════════════════════════════════
# Learning context helpers  (the real data sources)
# ═════════════════════════════════════════════════════════════════════════════

async def _get_learner_context(sp_dir: str):
    """Build LearnerContext for sp_dir. Returns None if not possible."""
    from sarthak.spaces.learner_context import build_learner_context
    from sarthak.spaces.store import load_profile
    d = Path(sp_dir) if sp_dir else None
    if not d or not d.exists():
        return None
    try:
        profile = load_profile(d)
        if not profile:
            return None
        return await build_learner_context(d, profile, days=14)
    except Exception as exc:
        log.warning("learner_context_failed", error=str(exc))
        return None


async def _get_all_spaces_with_dirs() -> list[dict]:
    from sarthak.spaces.store import list_spaces
    return [s for s in list_spaces() if Path(s.get("directory", "")).exists()]


# ═════════════════════════════════════════════════════════════════════════════
# Run handlers  — learning-context based
# ═════════════════════════════════════════════════════════════════════════════

async def _run_today(pool: Any, ctx: ContextTypes.DEFAULT_TYPE | None = None) -> str:
    """
    Today's dashboard: sessions, SRS due, notes written, current concept.
    Pulls from LearnerContext + SRS table.
    """
    from datetime import date, datetime, timezone, timedelta
    from sarthak.spaces.roadmap.srs import get_due
    from sarthak.spaces.session_tracker import load_sessions

    sp_dir = ctx.user_data.get(_K_SP_DIR, "") if ctx else ""
    if not sp_dir:
        try:
            from sarthak.spaces.store import get_active_space
            active = get_active_space()
            sp_dir = active.get("directory", "") if active else ""
        except Exception:
            pass

    spaces = await _get_all_spaces_with_dirs()
    if not spaces:
        return "No spaces registered. Use Init space to start."

    today = date.today()
    today_start = datetime(today.year, today.month, today.day, tzinfo=timezone.utc)
    lines: list[str] = [f"*Today — {today.strftime('%A, %B %d')}*\n"]

    for s in spaces:
        d = Path(s["directory"])
        name = s.get("name", d.name)
        section: list[str] = [f"*{name}*"]

        # Sessions today
        try:
            sessions = load_sessions(d, limit=50)
            today_sessions = [
                ss for ss in sessions
                if (
                    ss.started_at.replace(tzinfo=timezone.utc) >= today_start
                    if ss.started_at.tzinfo is None
                    else ss.started_at >= today_start
                )
            ]
            if today_sessions:
                concepts = list(dict.fromkeys(ss.concept for ss in today_sessions if ss.concept))
                total_active = sum(ss.signals.active_seconds for ss in today_sessions)
                section.append(
                    f"  Sessions: {len(today_sessions)} "
                    f"({total_active // 60} min active)"
                )
                if concepts:
                    section.append(f"  Studying: {', '.join(concepts[:4])}")
            else:
                section.append("  No sessions today yet.")
        except Exception:
            pass

        # SRS due
        try:
            db_path = str(d / ".spaces" / "sarthak.db")
            due = await get_due(db_path)
            if due:
                section.append(f"  SRS due: {len(due)} card(s)")
        except Exception:
            pass

        # Notes written today
        try:
            from sarthak.spaces.notes import load_all_notes
            today_notes = [
                n for n in load_all_notes(d, since_days=1)
            ]
            if today_notes:
                concepts_noted = list(dict.fromkeys(n.concept for n in today_notes))
                section.append(
                    f"  Notes: {len(today_notes)} written "
                    f"({', '.join(concepts_noted[:3])})"
                )
        except Exception:
            pass

        lines.append("\n".join(section))

    return "\n\n".join(lines)


async def _run_learner_status(pool: Any, ctx: ContextTypes.DEFAULT_TYPE | None = None) -> str:
    """Full LearnerContext snapshot: mastery confidence per concept, strong/weak/in-progress."""
    sp_dir = ctx.user_data.get(_K_SP_DIR, "") if ctx else ""
    if not sp_dir:
        try:
            from sarthak.spaces.store import get_active_space
            active = get_active_space()
            sp_dir = active.get("directory", "") if active else ""
        except Exception:
            pass

    if not sp_dir:
        spaces = await _get_all_spaces_with_dirs()
        if spaces:
            sp_dir = spaces[0]["directory"]

    if not sp_dir:
        return "No active space. Use Spaces > Activate."

    lc = await _get_learner_context(sp_dir)
    if not lc:
        return "No learner data yet. Run a session first."

    lines = [f"*Learner Status* (last {lc.days_window} days)\n"]

    if lc.strong_concepts:
        lines.append(f"*Strong ({len(lc.strong_concepts)}):*")
        for c in lc.strong_concepts[:6]:
            ev = lc.concept_evidence.get(c)
            conf = f"{ev.mastery_confidence:.0%}" if ev else ""
            lines.append(f"  + {c} {conf}")

    if lc.in_progress_concepts:
        lines.append(f"\n*In Progress ({len(lc.in_progress_concepts)}):*")
        for c in lc.in_progress_concepts[:6]:
            ev = lc.concept_evidence.get(c)
            conf = f"{ev.mastery_confidence:.0%}" if ev else ""
            lines.append(f"  ~ {c} {conf}")

    if lc.weak_concepts:
        lines.append(f"\n*Needs Work ({len(lc.weak_concepts)}):*")
        for c in lc.weak_concepts[:6]:
            ev = lc.concept_evidence.get(c)
            parts = []
            if ev:
                if ev.times_stuck >= 2: parts.append(f"stuck {ev.times_stuck}x")
                if ev.test_attempts and ev.test_percent < 50: parts.append(f"{ev.test_percent:.0f}% tests")
                if ev.note_count == 0: parts.append("no notes")
            detail = f" ({', '.join(parts)})" if parts else ""
            lines.append(f"  - {c}{detail}")

    if lc.srs_due_by_evidence:
        lines.append(f"\n*Review Due:* {', '.join(lc.srs_due_by_evidence[:5])}")

    lines.append(f"\nNotes written: {lc.notes_written_total}")
    if lc.most_productive_time:
        lines.append(f"Most productive: {lc.most_productive_time}")
    if lc.avg_session_depth:
        lines.append(f"Avg depth score: {lc.avg_session_depth:.2f}")

    return "\n".join(lines)


async def _run_weak_concepts(pool: Any, ctx: ContextTypes.DEFAULT_TYPE | None = None) -> str:
    """Weak and stuck concepts with full evidence breakdown."""
    sp_dir = ctx.user_data.get(_K_SP_DIR, "") if ctx else ""
    if not sp_dir:
        try:
            from sarthak.spaces.store import get_active_space
            active = get_active_space()
            sp_dir = active.get("directory", "") if active else ""
        except Exception:
            pass

    lc = await _get_learner_context(sp_dir)
    if not lc:
        return "No learner data. Run a session first."

    if not lc.weak_concepts and not lc.srs_due_by_evidence:
        return "No weak concepts found. Keep going!"

    lines = ["*Weak Concepts — Fix First*\n"]
    shown: set[str] = set()

    for c in lc.weak_concepts[:8]:
        shown.add(c)
        ev = lc.concept_evidence.get(c)
        lines.append(f"*{c}*")
        if ev:
            if ev.times_stuck >= 1: lines.append(f"  Stuck: {ev.times_stuck}x")
            if ev.test_attempts: lines.append(f"  Test score: {ev.test_percent:.0f}% ({ev.test_attempts} attempts)")
            if ev.note_count == 0: lines.append("  No notes written")
            elif ev.note_count: lines.append(f"  Notes: {ev.note_count}")
            if ev.understanding_ratings:
                avg = sum(ev.understanding_ratings) / len(ev.understanding_ratings)
                lines.append(f"  Self-rating: {avg:.1f}/5")
            lines.append(f"  Confidence: {ev.mastery_confidence:.0%}")

    for c in lc.srs_due_by_evidence:
        if c not in shown:
            lines.append(f"*{c}* (review due)")

    return "\n".join(lines)


async def _run_my_notes(pool: Any, ctx: ContextTypes.DEFAULT_TYPE | None = None) -> str:
    """Recent notes across the active space."""
    sp_dir = ctx.user_data.get(_K_SP_DIR, "") if ctx else ""
    if not sp_dir:
        try:
            from sarthak.spaces.store import get_active_space
            active = get_active_space()
            sp_dir = active.get("directory", "") if active else ""
        except Exception:
            pass

    if not sp_dir:
        return "No active space."

    try:
        from sarthak.spaces.notes import load_all_notes
        notes = load_all_notes(Path(sp_dir), since_days=14)
        if not notes:
            return "No notes in the last 14 days."
        lines = [f"*Recent Notes* (last 14 days — {len(notes)} total)\n"]
        for n in reversed(notes[-10:]):
            date_str = n.created_at[:10] if n.created_at else ""
            snippet = n.content_md.strip()[:120].replace("\n", " ")
            lines.append(f"[{n.concept}] {date_str}")
            lines.append(f"  {snippet}…")
        return "\n".join(lines)
    except Exception as exc:
        return f"Notes failed: {exc}"


async def _run_roadmap(pool: Any, ctx: ContextTypes.DEFAULT_TYPE | None = None) -> str:
    """Roadmap progress tree for the active space."""
    sp_dir = ctx.user_data.get(_K_SP_DIR, "") if ctx else ""
    if not sp_dir:
        try:
            from sarthak.spaces.store import get_active_space
            active = get_active_space()
            sp_dir = active.get("directory", "") if active else ""
        except Exception:
            pass

    if not sp_dir:
        return "No active space."

    try:
        from sarthak.spaces.roadmap.db import RoadmapDB
        db = RoadmapDB(Path(sp_dir))
        await db.init()
        roadmap = await db.load_roadmap()
        if not roadmap:
            return "No roadmap yet. Run a session to generate one."

        roadmap = roadmap.compute_all_progress()
        lines = [f"*Roadmap: {roadmap.space}*\n"]
        for ch in roadmap.chapters:
            status_icon = "✓" if ch.progress_pct >= 100 else ("~" if ch.progress_pct > 0 else " ")
            lines.append(f"[{status_icon}] *{ch.title}* — {ch.progress_pct:.0f}%")
            for tp in ch.topics:
                done = sum(1 for cn in tp.concepts if cn.status.value == "completed")
                total = len(tp.concepts)
                tp_icon = "✓" if done == total and total > 0 else ("~" if done > 0 else " ")
                lines.append(f"  [{tp_icon}] {tp.title} ({done}/{total})")
        return "\n".join(lines)
    except Exception as exc:
        return f"Roadmap failed: {exc}"


async def _run_srs_due(pool: Any, ctx: ContextTypes.DEFAULT_TYPE | None = None) -> str:
    """SRS cards due today across all spaces — with concept and reason."""
    from datetime import date
    from sarthak.spaces.roadmap.srs import get_due

    spaces = await _get_all_spaces_with_dirs()
    if not spaces:
        return "No spaces registered."

    sections: list[str] = []
    for s in spaces:
        d = Path(s["directory"])
        db_path = str(d / ".spaces" / "sarthak.db")
        try:
            due = await get_due(db_path)
            if not due:
                continue
            name = s.get("name", d.name)
            card_lines = [f"*{name}* — {len(due)} due"]
            for card in due[:8]:
                label = card.concept or card.card_id
                reason = f" ({card.reason})" if card.reason else ""
                try:
                    overdue_days = (date.today() - date.fromisoformat(card.next_due)).days
                    overdue_str = f" [{overdue_days}d overdue]" if overdue_days > 0 else ""
                except Exception:
                    overdue_str = ""
                card_lines.append(f"  - {label}{reason}{overdue_str}")
            if len(due) > 8:
                card_lines.append(f"  ... and {len(due) - 8} more")
            sections.append("\n".join(card_lines))
        except Exception:
            pass
    return "\n\n".join(sections) if sections else "No SRS cards due today."


async def _run_digest(pool: Any, ctx: ContextTypes.DEFAULT_TYPE | None = None) -> str:
    """Build daily digest for all spaces."""
    from sarthak.agents.roadmap_agents import build_digest

    spaces = await _get_all_spaces_with_dirs()
    if not spaces:
        return "No spaces registered."

    parts: list[str] = []
    for s in spaces:
        d = Path(s["directory"])
        try:
            parts.append(await build_digest(d, s.get("name", d.name)))
        except Exception as exc:
            parts.append(f"{s.get('name', d.name)}: failed ({exc})")
    return "\n\n---\n\n".join(parts) if parts else "No spaces with data."


async def _run_tips(pool: Any) -> str:
    from sarthak.features.ai.tools.activity import tool_get_tips
    return await tool_get_tips(pool, limit=3)


async def _run_skills_list(pool: Any) -> str:
    from sarthak.features.ai.skills import tool_list_skills
    return tool_list_skills()


async def _run_status(pool: Any) -> str:
    from sarthak.features.ai.tools.system import tool_service_status
    return await tool_service_status()


# ── Context-aware wrapper: injects ctx into handlers that need it ─────────────

def _ctx_handler(fn: Callable) -> Callable:
    """Wrap a handler that accepts (pool, ctx) so it fits the (pool,) signature slot
    for handlers that don't need ctx, while also being callable with ctx."""
    return fn


# ── Handler registry ──────────────────────────────────────────────────────────

# Handlers that need ctx are NOT in _RUN_HANDLERS (called directly in on_callback).
# Handlers here only need pool.
_RUN_HANDLERS: dict[str, Callable] = {
    "tips":        _run_tips,
    "skills_list": _run_skills_list,
    "status":      _run_status,
    "digest":      _run_digest,
    "srs_due":     _run_srs_due,
}

# Handlers that need ctx — called separately
_CTX_HANDLERS: dict[str, Callable] = {
    "today":          _run_today,
    "learner_status": _run_learner_status,
    "weak_concepts":  _run_weak_concepts,
    "my_notes":       _run_my_notes,
    "roadmap":        _run_roadmap,
}

_RUN_LABELS: dict[str, str] = {
    "today":          "Today's learning dashboard",
    "learner_status": "Mastery status across concepts",
    "weak_concepts":  "Weak / stuck concepts",
    "my_notes":       "Recent notes (14 days)",
    "roadmap":        "Roadmap progress tree",
    "srs_due":        "SRS cards due today",
    "digest":         "Full daily digest (all spaces)",
    "tips":           "Saved tips (last 3)",
    "skills_list":    "List all saved skills",
    "status":         "Service status",
}


# ═════════════════════════════════════════════════════════════════════════════
# Keyboards
# ═════════════════════════════════════════════════════════════════════════════

def _btn(label: str, data: str) -> InlineKeyboardButton:
    return InlineKeyboardButton(label, callback_data=data)


def _back(target: str = "menu:main") -> list[InlineKeyboardButton]:
    return [_btn("← Back", target)]


def _kb_main() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [_btn("Today",    "run:today"),    _btn("Ask Sarthak", "menu:ask")],
        [_btn("Learn",    "menu:learn"),   _btn("Progress",    "menu:progress")],
        [_btn("Spaces",   "menu:spaces"),  _btn("Skills",      "menu:skills")],
        [_btn("Agents",   "menu:agents"),  _btn("Config",      "menu:config")],
    ])


def _kb_learn() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [_btn("New session",  "sp:session"),  _btn("QuickTest",    "sp:quick")],
        [_btn("Evaluate",     "sp:eval"),     _btn("Daily digest", "run:digest")],
        [_btn("Add note",     "note:add"),    _btn("SRS due",      "run:srs_due")],
        _back(),
    ])


def _kb_progress() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [_btn("Learner status", "run:learner_status"), _btn("Weak concepts", "run:weak_concepts")],
        [_btn("My notes",       "run:my_notes"),       _btn("Roadmap",       "run:roadmap")],
        [_btn("SRS due",        "run:srs_due"),         _btn("Daily digest",  "run:digest")],
        _back(),
    ])


def _kb_spaces() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [_btn("List spaces", "sp:list"),   _btn("Activate",  "sp:activate")],
        [_btn("Space status","sp:status"), _btn("Setup env", "sp:setup")],
        [_btn("Init space",  "sp:init")],
        _back(),
    ])


def _kb_skills() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [_btn("List skills", "run:skills_list"), _btn("Read skill",   "skill:read")],
        [_btn("New skill",   "skill:new"),        _btn("Delete skill", "skill:delete")],
        _back(),
    ])


def _kb_agents() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [_btn("List agents",    "ag:list"),   _btn("Create agent", "ag:create")],
        [_btn("Run agent",      "ag:run"),    _btn("Agent logs",   "ag:logs")],
        [_btn("Enable/Disable", "ag:toggle")],
        _back(),
    ])


def _kb_config(ctx: ContextTypes.DEFAULT_TYPE) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [_btn("Change model",   "cfg:model"),  _btn("Service status", "run:status")],
        [_btn("Edit constant",  "cfg:const"),  _btn("Bot info",       "cfg:info")],
        [_btn("Tips",           "run:tips")],
        _back(),
    ])


def _kb_model_list(ctx: ContextTypes.DEFAULT_TYPE) -> InlineKeyboardMarkup:
    cfg              = ctx.bot_data.get("cfg", {})
    ai               = cfg.get("ai", {})
    default_provider = ai.get("default_provider", "")
    default_model    = ai.get("default_model", "gpt-4o-mini")
    main_providers   = ["github", "openai", "anthropic", "gemini", "groq", "ollama", "openrouter"]
    configured       = [p for p, v in ai.items() if isinstance(v, dict)]
    ordered          = list(dict.fromkeys([default_provider] + main_providers + configured))
    top              = [p for p in ordered if p in main_providers or p == default_provider]
    others           = [p for p in ordered if p not in top]

    rows: list[list[InlineKeyboardButton]] = []
    choices: list[tuple[str, str]] = []
    current = _current_model(ctx)

    def _add_provider(provider: str) -> None:
        section    = ai.get(provider, {})
        model_name = (
            (section.get("text_model") or section.get("model") or default_model)
            if isinstance(section, dict) else default_model
        )
        marker = "[*] " if f"{provider}/{model_name}" == current else "    "
        choices.append((provider, model_name))
        rows.append([_btn(f"{marker}{provider} / {model_name}",
                          f"cfg:set_model_idx:{len(choices)-1}")])

    for p in top:
        _add_provider(p)
    if others:
        rows.append([_btn("— other providers —", "noop")])
        for p in others:
            _add_provider(p)

    rows.append(_back("menu:config"))
    ctx.user_data[_K_MODEL_CHOICES] = choices
    return InlineKeyboardMarkup(rows)


def _kb_constants() -> InlineKeyboardMarkup:
    from sarthak.core import constants as C
    editable = [
        ("SHELL_TIMEOUT_SECONDS",       f"Shell timeout: {C.SHELL_TIMEOUT_SECONDS} s"),
        ("SHELL_OUTPUT_MAX_CHARS",      f"Shell output cap: {C.SHELL_OUTPUT_MAX_CHARS}"),
        ("WEB_SEARCH_TIMEOUT",          f"Web timeout: {C.WEB_SEARCH_TIMEOUT} s"),
        ("ACTIVITY_HEAD_TAIL",          f"Activity head/tail: {C.ACTIVITY_HEAD_TAIL}"),
        ("DAILY_SUMMARY_CONTEXT_LIMIT", f"Summary ctx: {C.DAILY_SUMMARY_CONTEXT_LIMIT}"),
        ("AGENT_RETRIES",               f"Agent retries: {C.AGENT_RETRIES}"),
        ("RULE_BASED_TREND_DAYS",       f"Trend days: {C.RULE_BASED_TREND_DAYS}"),
        ("TELEGRAM_MESSAGE_LIMIT",      f"Msg limit: {C.TELEGRAM_MESSAGE_LIMIT}"),
    ]
    rows = [[_btn(label, f"const:pick:{name}")] for name, label in editable]
    rows.append(_back("menu:config"))
    return InlineKeyboardMarkup(rows)


def _kb_space_type() -> InlineKeyboardMarkup:
    types = [
        ("data_science",   "Data Science"),
        ("ai_engineering", "AI Engineering"),
        ("medicine",       "Medicine"),
        ("education",      "Education"),
        ("exam_prep",      "Exam Prep"),
        ("business",       "Business"),
        ("research",       "Research"),
        ("custom",         "Custom"),
    ]
    rows = [[_btn(label, f"sp:init_type:{val}")] for val, label in types]
    rows.append(_back("menu:spaces"))
    return InlineKeyboardMarkup(rows)


# ═════════════════════════════════════════════════════════════════════════════
# /start and command shortcuts
# ═════════════════════════════════════════════════════════════════════════════

async def cmd_start(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> int:
    if not _is_allowed(update, ctx.bot_data["allowed_id"]):
        await _deny(update)
        return ST_IDLE
    await update.message.reply_text(
        f"Sarthak AI\nModel: `{_current_model(ctx)}`\n\n"
        "Choose a section or send any message to ask a question.",
        parse_mode="Markdown",
        reply_markup=_kb_main(),
    )
    return ST_IDLE


def _make_cmd(run_key: str):
    """Factory for direct /command shortcuts that call a run handler."""
    async def _handler(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> int:
        if not _is_allowed(update, ctx.bot_data["allowed_id"]):
            await _deny(update)
            return ST_IDLE
        pool = ctx.bot_data.get("pool")
        msg  = await update.message.reply_text("Running...")
        reply = ""
        try:
            if run_key in _CTX_HANDLERS:
                reply = await _CTX_HANDLERS[run_key](pool, ctx)
            else:
                reply = await _RUN_HANDLERS[run_key](pool)
            await msg.edit_text(_trunc(reply), parse_mode="Markdown")
        except BadRequest:
            await msg.edit_text(_trunc(reply) or "(empty reply)")
        except Exception as exc:
            await msg.edit_text(f"Error: {exc}")
        return ST_IDLE
    _handler.__name__ = f"cmd_{run_key}"
    return _handler


async def cmd_help(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> int:
    if not _is_allowed(update, ctx.bot_data["allowed_id"]):
        await _deny(update)
        return ST_IDLE
    lines = [f"/{k}  — {label}" for k, label in _RUN_LABELS.items()]
    lines += [
        "/skills  — skills menu",
        "/spaces  — spaces menu",
        "/learn   — learning menu",
        "/config  — config menu",
        "/help    — this message",
        "/start   — main menu",
        "/cancel  — cancel current action",
    ]
    await update.message.reply_text(
        "*Sarthak AI — Commands*\n\n" + "\n".join(lines)
        + "\n\nOr send any question directly (streamed response).",
        parse_mode="Markdown",
    )
    return ST_IDLE


async def cmd_config(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> int:
    if not _is_allowed(update, ctx.bot_data["allowed_id"]):
        await _deny(update)
        return ST_IDLE
    await update.message.reply_text(
        f"*Configuration*\nCurrent model: `{_current_model(ctx)}`",
        parse_mode="Markdown",
        reply_markup=_kb_config(ctx),
    )
    return ST_IDLE


async def cmd_skills(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> int:
    if not _is_allowed(update, ctx.bot_data["allowed_id"]):
        await _deny(update)
        return ST_IDLE
    await update.message.reply_text("*Skills*", parse_mode="Markdown", reply_markup=_kb_skills())
    return ST_IDLE


async def cmd_spaces(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> int:
    if not _is_allowed(update, ctx.bot_data["allowed_id"]):
        await _deny(update)
        return ST_IDLE
    await update.message.reply_text(
        "*Spaces*\nMastery learning engine.",
        parse_mode="Markdown",
        reply_markup=_kb_spaces(),
    )
    return ST_IDLE


async def cmd_learn(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> int:
    if not _is_allowed(update, ctx.bot_data["allowed_id"]):
        await _deny(update)
        return ST_IDLE
    sp_dir = _active_space_dir(ctx)
    name = Path(sp_dir).name if sp_dir else "none"
    await update.message.reply_text(
        f"*Learn*\nActive space: `{name}`",
        parse_mode="Markdown",
        reply_markup=_kb_learn(),
    )
    return ST_IDLE


# ═════════════════════════════════════════════════════════════════════════════
# Callback query handler
# ═════════════════════════════════════════════════════════════════════════════

async def on_callback(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> int:  # noqa: C901
    query = update.callback_query
    try:
        await query.answer()
    except BadRequest as exc:
        log.debug("callback_answer_failed", error=str(exc))

    if not _is_allowed(update, ctx.bot_data["allowed_id"]):
        await query.edit_message_text("Unauthorized.")
        return ST_IDLE

    data: str = query.data or ""

    # ── Menu navigation ───────────────────────────────────────────────────────

    if data == "menu:main":
        await _safe_edit(query,
            f"Sarthak AI\nModel: `{_current_model(ctx)}`\n\nChoose a section:",
            parse_mode="Markdown", reply_markup=_kb_main())
        return ST_IDLE

    if data == "menu:learn":
        sp_dir = _active_space_dir(ctx)
        name = Path(sp_dir).name if sp_dir else "none"
        await _safe_edit(query, f"*Learn* — active space: `{name}`",
                         parse_mode="Markdown", reply_markup=_kb_learn())
        return ST_IDLE

    if data == "menu:progress":
        await _safe_edit(query, "*Progress* — your learning data:",
                         parse_mode="Markdown", reply_markup=_kb_progress())
        return ST_IDLE

    if data == "menu:spaces":
        await _safe_edit(query, "*Spaces* — mastery learning engine:",
                         parse_mode="Markdown", reply_markup=_kb_spaces())
        return ST_IDLE

    if data == "menu:config":
        await _safe_edit(query,
            f"*Configuration*\nCurrent model: `{_current_model(ctx)}`",
            parse_mode="Markdown", reply_markup=_kb_config(ctx))
        return ST_IDLE

    if data == "menu:agents":
        await _safe_edit(query, "*Agents* — scheduled automation:",
                         parse_mode="Markdown", reply_markup=_kb_agents())
        return ST_IDLE

    if data == "menu:skills":
        await _safe_edit(query, "*Skills* — manage your knowledge base:",
                         parse_mode="Markdown", reply_markup=_kb_skills())
        return ST_IDLE

    if data == "menu:ask":
        await _safe_edit(query, "Send your question (streamed response).")
        return ST_FREE_TEXT

    if data == "noop":
        return ST_IDLE

    if data == "chat:new":
        sid = _new_session(ctx)
        await _safe_edit(query, f"New session: `{sid.split('-')[0]}`", parse_mode="Markdown")
        return ST_FREE_TEXT

    # ── Quick-run (pool-only handlers) ────────────────────────────────────────

    if data.startswith("run:"):
        run_key = data[4:]
        pool    = ctx.bot_data.get("pool")
        await _safe_edit(query, "Running...")
        reply = ""
        try:
            if run_key in _CTX_HANDLERS:
                reply = await _CTX_HANDLERS[run_key](pool, ctx)
            elif run_key in _RUN_HANDLERS:
                reply = await _RUN_HANDLERS[run_key](pool)
            else:
                await _safe_edit(query, f"Unknown action: {run_key}")
                return ST_IDLE
            await _safe_edit(query, _trunc(reply), parse_mode="Markdown")
        except BadRequest:
            await _safe_edit(query, _trunc(reply) or "(empty reply)")
        except Exception as exc:
            await _safe_edit(query, f"Error: {exc}")
        return ST_IDLE

    # ── Note taking ───────────────────────────────────────────────────────────

    if data == "note:add":
        await _safe_edit(query, "Enter concept name for this note:")
        return ST_NOTE_CONCEPT

    # ── Spaces ────────────────────────────────────────────────────────────────

    if data == "sp:list":
        from sarthak.features.ai.tools.spaces import tool_spaces_list
        result = tool_spaces_list()
        items  = _parse_space_list(result)
        if not items:
            await _safe_edit(query, result or "No spaces found. Use Init space.")
            return ST_IDLE
        ctx.user_data[_K_SP_CHOICES] = items
        rows = [
            [_btn(f"{i.get('name','?')}  {i.get('directory','')}"[:62],
                  f"sp:activate_idx:{idx}")]
            for idx, i in enumerate(items[:20])
        ]
        rows.append(_back("menu:spaces"))
        await _safe_edit(query, "*Spaces* — select one to activate:",
                         parse_mode="Markdown", reply_markup=InlineKeyboardMarkup(rows))
        return ST_IDLE

    if data == "sp:status":
        sp_dir = _active_space_dir(ctx)
        if sp_dir:
            from sarthak.features.ai.tools.spaces import tool_spaces_status
            await _safe_edit(query, _trunc(tool_spaces_status(sp_dir)), parse_mode="Markdown")
            return ST_IDLE
        await _safe_edit(query, "Send the space directory path:")
        return ST_SP_STATUS_DIR

    if data == "sp:session":
        sp_dir = _active_space_dir(ctx)
        await _safe_edit(query, "Starting learning session…")
        from sarthak.features.ai.tools.spaces import tool_spaces_session
        result = await asyncio.to_thread(tool_spaces_session, sp_dir)
        await _safe_edit(query, _trunc(result), parse_mode="Markdown")
        return ST_IDLE

    if data == "sp:quick":
        sp_dir = _active_space_dir(ctx)
        await _safe_edit(query, "Generating quicktest…")
        from sarthak.features.ai.tools.spaces import tool_spaces_quick
        result = await asyncio.to_thread(tool_spaces_quick, sp_dir)
        await _safe_edit(query, _trunc(result), parse_mode="Markdown")
        return ST_IDLE

    if data == "sp:eval":
        await _safe_edit(query, "Enter the concept name you are submitting work for:")
        return ST_SP_EVAL_CONCEPT

    if data == "sp:setup":
        sp_dir = _active_space_dir(ctx)
        if sp_dir:
            await _safe_edit(query, "Scanning environment…")
            from sarthak.features.ai.tools.spaces import tool_spaces_setup
            result = await asyncio.to_thread(tool_spaces_setup, sp_dir)
            await _safe_edit(query, _trunc(result), parse_mode="Markdown")
            return ST_IDLE
        await _safe_edit(query, "Send the space directory path:")
        return ST_SP_SETUP_DIR

    if data == "sp:init":
        await _safe_edit(query, "Step 1 of 4 — send the target directory path:")
        return ST_SP_INIT_DIR

    if data == "sp:activate":
        items = ctx.user_data.get(_K_SP_CHOICES)
        if not items:
            await _safe_edit(query, "Send the space directory path to activate:")
            return ST_SP_ACTIVATE_DIR
        rows = [
            [_btn(f"{i.get('name','?')}  {i.get('directory','')}"[:62],
                  f"sp:activate_idx:{idx}")]
            for idx, i in enumerate(items[:20])
        ]
        rows.append(_back("menu:spaces"))
        await _safe_edit(query, "*Activate space* — select one:",
                         parse_mode="Markdown", reply_markup=InlineKeyboardMarkup(rows))
        return ST_IDLE

    if data.startswith("sp:activate_idx:"):
        try:
            idx = int(data.split(":", 2)[2])
        except ValueError:
            await _safe_edit(query, "Invalid selection.")
            return ST_IDLE
        items = ctx.user_data.get(_K_SP_CHOICES, [])
        if not (0 <= idx < len(items)):
            await _safe_edit(query, "List expired. Use List spaces again.")
            return ST_IDLE
        directory = items[idx].get("directory", "")
        if not directory:
            await _safe_edit(query, "Missing directory.")
            return ST_IDLE
        from sarthak.spaces.store import set_active_space
        try:
            set_active_space(Path(directory))
            ctx.user_data[_K_SP_DIR] = directory
            name = items[idx].get("name", "space")
            await _safe_edit(query, f"Active space: *{name}*\n`{directory}`",
                             parse_mode="Markdown")
        except Exception as exc:
            await _safe_edit(query, f"Activate failed: {exc}")
        return ST_IDLE

    if data.startswith("sp:init_type:"):
        sp_type = data[len("sp:init_type:"):]
        ctx.user_data[_K_SP_TYPE] = sp_type
        await _safe_edit(query,
            "Step 3 of 4 — your background (e.g. 'doctor').\nSend - to skip.")
        return ST_SP_INIT_BG

    # ── Skills ────────────────────────────────────────────────────────────────

    if data == "skill:read":
        await _safe_edit(query, "Enter the skill name to read:")
        return ST_SKILL_READ_NAME

    if data == "skill:new":
        await _safe_edit(query, "*New Skill — Step 1 of 3*\nEnter the skill name:",
                         parse_mode="Markdown")
        return ST_SKILL_NEW_NAME

    if data == "skill:delete":
        await _safe_edit(query, "Enter the skill name to delete:")
        return ST_SKILL_DEL_NAME

    # ── Config ────────────────────────────────────────────────────────────────

    if data == "cfg:model":
        await _safe_edit(query,
            f"*Select Model*\nCurrent: `{_current_model(ctx)}`",
            parse_mode="Markdown", reply_markup=_kb_model_list(ctx))
        return ST_IDLE

    if data.startswith("cfg:set_model_idx:"):
        try:
            idx = int(data.split(":", 2)[2])
        except ValueError:
            await _safe_edit(query, "Invalid model selection.")
            return ST_IDLE
        choices = ctx.user_data.get(_K_MODEL_CHOICES, [])
        if not (0 <= idx < len(choices)):
            await _safe_edit(query, "Model list expired. Open Change model again.")
            return ST_IDLE
        provider, model_name = choices[idx]
        _apply_model_change(ctx, provider, model_name)
        await _safe_edit(query, f"Model set to `{provider}/{model_name}`.", parse_mode="Markdown")
        return ST_IDLE

    if data == "cfg:const":
        await _safe_edit(query, "*Edit Constants* — select one:",
                         parse_mode="Markdown", reply_markup=_kb_constants())
        return ST_IDLE

    if data.startswith("const:pick:"):
        const_name = data[len("const:pick:"):]
        ctx.user_data[_K_CONST_NAME] = const_name
        from sarthak.core import constants as C
        current_val = getattr(C, const_name, "?")
        await _safe_edit(query,
            f"*{const_name}*\nCurrent: `{current_val}`\n\nSend the new value:",
            parse_mode="Markdown")
        return ST_CONST_VALUE

    if data == "cfg:info":
        import platform, sys
        await _safe_edit(query,
            f"*Sarthak AI Bot*\n\n"
            f"Model: `{_current_model(ctx)}`\n"
            f"Python: `{sys.version.split()[0]}`\n"
            f"Platform: `{platform.system()} {platform.release()}`",
            parse_mode="Markdown")
        return ST_IDLE

    # ── Agents ────────────────────────────────────────────────────────────────

    if data == "ag:list":
        from sarthak.agents.store import list_agents
        specs = list_agents()
        if not specs:
            await _safe_edit(query, "No agents configured yet.")
            return ST_IDLE
        lines = ["*Agents*\n"]
        for s in specs:
            icon = "+" if s.enabled else "-"
            lines.append(f"[{icon}] `{s.agent_id}` *{s.name}*\nSchedule: {s.schedule}")
        await _safe_edit(query, _trunc("\n".join(lines)), parse_mode="Markdown")
        return ST_IDLE

    if data == "ag:create":
        await _safe_edit(query, "Describe the agent (what it should do, how often, tools needed):")
        return ST_AG_CREATE_DESC

    if data == "ag:run":
        await _safe_edit(query, "Enter agent ID to run now:")
        return ST_AG_RUN_ID

    if data == "ag:logs":
        await _safe_edit(query, "Enter agent ID to view logs:")
        return ST_AG_LOGS_ID

    if data == "ag:toggle":
        await _safe_edit(query, "Enter agent ID to enable/disable:")
        return ST_AG_TOGGLE_ID

    log.warning("unhandled_callback", data=data)
    return ST_IDLE


# ═════════════════════════════════════════════════════════════════════════════
# Message handlers
# ═════════════════════════════════════════════════════════════════════════════

async def on_free_text(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> int:
    if not _is_allowed(update, ctx.bot_data["allowed_id"]):
        await _deny(update)
        return ST_IDLE
    question = (update.message.text or "").strip()
    if not question:
        return ST_FREE_TEXT
    await _handle_question(question, update, ctx)
    return ST_IDLE


async def on_plain_message(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> int:
    if not _is_allowed(update, ctx.bot_data["allowed_id"]):
        await _deny(update)
        return ST_IDLE
    question = (update.message.text or "").strip()
    if not question:
        return ST_IDLE
    await _handle_question(question, update, ctx)
    return ST_IDLE


# ── Note wizard ───────────────────────────────────────────────────────────────

async def on_note_concept(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> int:
    if not _is_allowed(update, ctx.bot_data["allowed_id"]): return ST_IDLE
    concept = (update.message.text or "").strip()
    if not concept:
        await update.message.reply_text("Enter a concept name.")
        return ST_NOTE_CONCEPT
    ctx.user_data[_K_NOTE_CONCEPT] = concept
    await update.message.reply_text(
        f"Concept: *{concept}*\nNow send the note content (Markdown):",
        parse_mode="Markdown")
    return ST_NOTE_CONTENT


async def on_note_content(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> int:
    if not _is_allowed(update, ctx.bot_data["allowed_id"]): return ST_IDLE
    concept = ctx.user_data.pop(_K_NOTE_CONCEPT, "")
    content = (update.message.text or "").strip()
    if not concept or not content:
        await update.message.reply_text("Missing concept or content.")
        return ST_IDLE
    sp_dir = _active_space_dir(ctx)
    if not sp_dir:
        await update.message.reply_text("No active space. Activate a space first.")
        return ST_IDLE
    try:
        from sarthak.spaces.notes import take_concept_note
        record = await take_concept_note(Path(sp_dir), concept, content, source="telegram")
        await update.message.reply_text(
            f"Note saved for *{concept}*\nID: `{record.note_id}`",
            parse_mode="Markdown")
    except Exception as exc:
        await update.message.reply_text(f"Failed to save note: {exc}")
    return ST_IDLE


# ── Skill wizard ──────────────────────────────────────────────────────────────

async def on_skill_read_name(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> int:
    if not _is_allowed(update, ctx.bot_data["allowed_id"]): return ST_IDLE
    from sarthak.features.ai.tools.skills import tool_read_skill
    await update.message.reply_text(_trunc(tool_read_skill((update.message.text or "").strip())))
    return ST_IDLE


async def on_skill_del_name(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> int:
    if not _is_allowed(update, ctx.bot_data["allowed_id"]): return ST_IDLE
    from sarthak.features.ai.tools.skills import tool_delete_skill
    await update.message.reply_text(tool_delete_skill((update.message.text or "").strip()))
    return ST_IDLE


async def on_skill_new_name(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> int:
    if not _is_allowed(update, ctx.bot_data["allowed_id"]): return ST_IDLE
    ctx.user_data[_K_SKILL_NAME] = (update.message.text or "").strip()
    await update.message.reply_text("*Step 2 of 3* — enter a short description:",
                                    parse_mode="Markdown")
    return ST_SKILL_NEW_DESC


async def on_skill_new_desc(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> int:
    if not _is_allowed(update, ctx.bot_data["allowed_id"]): return ST_IDLE
    ctx.user_data[_K_SKILL_DESC] = (update.message.text or "").strip()
    await update.message.reply_text("*Step 3 of 3* — send the skill content (Markdown):",
                                    parse_mode="Markdown")
    return ST_SKILL_NEW_CONTENT


async def on_skill_new_content(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> int:
    if not _is_allowed(update, ctx.bot_data["allowed_id"]): return ST_IDLE
    from sarthak.features.ai.tools.skills import tool_save_skill
    name    = ctx.user_data.pop(_K_SKILL_NAME, "untitled")
    desc    = ctx.user_data.pop(_K_SKILL_DESC, "")
    content = (update.message.text or "").strip()
    await update.message.reply_text(tool_save_skill(name, desc, content))
    return ST_IDLE


# ── Spaces wizards ────────────────────────────────────────────────────────────

async def on_sp_status_dir(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> int:
    if not _is_allowed(update, ctx.bot_data["allowed_id"]): return ST_IDLE
    from sarthak.features.ai.tools.spaces import tool_spaces_status
    sp_dir = (update.message.text or "").strip()
    if not sp_dir:
        await update.message.reply_text("Provide a directory path.")
        return ST_SP_STATUS_DIR
    ctx.user_data[_K_SP_DIR] = sp_dir
    await update.message.reply_text(_trunc(tool_spaces_status(sp_dir)), parse_mode="Markdown")
    return ST_IDLE


async def on_sp_activate_dir(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> int:
    if not _is_allowed(update, ctx.bot_data["allowed_id"]): return ST_IDLE
    from sarthak.spaces.store import set_active_space
    sp_dir = (update.message.text or "").strip()
    if not sp_dir:
        await update.message.reply_text("Provide a directory path.")
        return ST_SP_ACTIVATE_DIR
    try:
        ws = set_active_space(Path(sp_dir))
        ctx.user_data[_K_SP_DIR] = sp_dir
        await update.message.reply_text(
            f"Active space: *{ws.get('name','space')}*", parse_mode="Markdown")
    except Exception as exc:
        await update.message.reply_text(f"Activate failed: {exc}")
    return ST_IDLE


async def on_sp_setup_dir(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> int:
    if not _is_allowed(update, ctx.bot_data["allowed_id"]): return ST_IDLE
    from sarthak.features.ai.tools.spaces import tool_spaces_setup
    sp_dir = (update.message.text or "").strip()
    if not sp_dir:
        await update.message.reply_text("Provide a directory path.")
        return ST_SP_SETUP_DIR
    ctx.user_data[_K_SP_DIR] = sp_dir
    msg    = await update.message.reply_text("Scanning environment…")
    result = await asyncio.to_thread(tool_spaces_setup, sp_dir)
    await msg.edit_text(_trunc(result), parse_mode="Markdown")
    return ST_IDLE


async def on_sp_eval_concept(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> int:
    if not _is_allowed(update, ctx.bot_data["allowed_id"]): return ST_IDLE
    concept = (update.message.text or "").strip()
    if not concept:
        await update.message.reply_text("Enter the concept name.")
        return ST_SP_EVAL_CONCEPT
    ctx.user_data[_K_SP_EVAL_CONC] = concept
    await update.message.reply_text("Now paste your submission (code or explanation):")
    return ST_SP_EVAL_SUBMISSION


async def on_sp_eval_submission(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> int:
    if not _is_allowed(update, ctx.bot_data["allowed_id"]): return ST_IDLE
    import functools
    from sarthak.features.ai.tools.spaces import tool_spaces_evaluate
    concept    = ctx.user_data.pop(_K_SP_EVAL_CONC, "")
    submission = (update.message.text or "").strip()
    sp_dir     = _active_space_dir(ctx)
    if not concept:
        await update.message.reply_text("Missing concept. Start the evaluate flow again.")
        return ST_IDLE
    msg    = await update.message.reply_text("Evaluating…")
    result = await asyncio.to_thread(
        functools.partial(tool_spaces_evaluate, concept, submission, sp_dir))
    await msg.edit_text(_trunc(result), parse_mode="Markdown")
    return ST_IDLE


async def on_sp_init_dir(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> int:
    if not _is_allowed(update, ctx.bot_data["allowed_id"]): return ST_IDLE
    sp_dir = (update.message.text or "").strip()
    if not sp_dir:
        await update.message.reply_text("Provide a directory path.")
        return ST_SP_INIT_DIR
    ctx.user_data[_K_SP_DIR] = sp_dir
    await update.message.reply_text("Step 2 of 4 — select the space type:",
                                    reply_markup=_kb_space_type())
    return ST_SP_INIT_TYPE


async def on_sp_init_type_text(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> int:
    if not _is_allowed(update, ctx.bot_data["allowed_id"]): return ST_IDLE
    sp_type = (update.message.text or "").strip().lower().replace(" ", "_")
    valid   = {"data_science","ai_engineering","medicine","education",
               "exam_prep","business","research","custom"}
    if sp_type not in valid:
        await update.message.reply_text(f"Unknown type. Valid: {', '.join(sorted(valid))}")
        return ST_SP_INIT_TYPE
    ctx.user_data[_K_SP_TYPE] = sp_type
    await update.message.reply_text("Step 3 of 4 — your background (e.g. 'doctor'). Send - to skip.")
    return ST_SP_INIT_BG


async def on_sp_init_bg(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> int:
    if not _is_allowed(update, ctx.bot_data["allowed_id"]): return ST_IDLE
    raw = (update.message.text or "").strip()
    ctx.user_data[_K_SP_BG] = "" if raw == "-" else raw
    await update.message.reply_text("Step 4 of 4 — your name (or - to skip):")
    return ST_SP_INIT_NAME


async def on_sp_init_name(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> int:
    if not _is_allowed(update, ctx.bot_data["allowed_id"]): return ST_IDLE
    import functools
    from sarthak.features.ai.tools.spaces import tool_spaces_init
    raw          = (update.message.text or "").strip()
    learner_name = "" if raw == "-" else raw
    sp_dir       = ctx.user_data.get(_K_SP_DIR, "")
    sp_type      = ctx.user_data.get(_K_SP_TYPE, "data_science")
    background   = ctx.user_data.get(_K_SP_BG, "")
    if not sp_dir:
        await update.message.reply_text("Missing directory. Start the init flow again.")
        return ST_IDLE
    msg    = await update.message.reply_text("Initializing space…")
    result = await asyncio.to_thread(
        functools.partial(tool_spaces_init, sp_dir, sp_type, background, learner_name))
    await msg.edit_text(_trunc(result), parse_mode="Markdown")
    return ST_IDLE


# ── Constants wizard ──────────────────────────────────────────────────────────

async def on_const_value(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> int:
    if not _is_allowed(update, ctx.bot_data["allowed_id"]): return ST_IDLE
    const_name = ctx.user_data.pop(_K_CONST_NAME, "")
    raw_value  = (update.message.text or "").strip()
    if not const_name:
        await update.message.reply_text("No constant selected.")
        return ST_IDLE
    await update.message.reply_text(
        _apply_constant_change(const_name, raw_value), parse_mode="Markdown")
    return ST_IDLE


async def on_cancel(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> int:
    await update.message.reply_text("Cancelled.")
    return ST_IDLE


# ── Agents wizards ────────────────────────────────────────────────────────────

async def on_ag_create_desc(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> int:
    if not _is_allowed(update, ctx.bot_data["allowed_id"]): return ST_IDLE
    description = (update.message.text or "").strip()
    if not description:
        await update.message.reply_text("Describe the agent.")
        return ST_AG_CREATE_DESC
    sp_dir = _active_space_dir(ctx)
    msg = await update.message.reply_text("Creating agent…")
    try:
        from sarthak.agents.creator import create_agent_from_description
        spec      = await create_agent_from_description(
            description, space_dir=Path(sp_dir) if sp_dir else None)
        tools_str = ", ".join(t.value for t in spec.tools) or "none"
        next_run  = spec.next_run_at[:19] if spec.next_run_at else "unknown"
        text = (
            f"*Agent created: {spec.name}*\n"
            f"ID: `{spec.agent_id}`\nSchedule: `{spec.schedule}`\n"
            f"Tools: {tools_str}\nTelegram: {spec.notify_telegram}\n"
            f"Next run: {next_run}"
        )
        if spec.space_dir:
            text += f"\nSpace: `{spec.space_dir}`"
        await msg.edit_text(_trunc(text), parse_mode="Markdown")
    except Exception as exc:
        await msg.edit_text(f"Failed: {exc}")
    return ST_IDLE


async def on_ag_run_id(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> int:
    if not _is_allowed(update, ctx.bot_data["allowed_id"]): return ST_IDLE
    agent_id = (update.message.text or "").strip()
    if not agent_id:
        await update.message.reply_text("Provide an agent ID.")
        return ST_AG_RUN_ID
    from sarthak.agents.store import load_agent
    spec = load_agent(agent_id)
    if not spec:
        await update.message.reply_text(f"Agent not found: `{agent_id}`", parse_mode="Markdown")
        return ST_IDLE
    msg = await update.message.reply_text(f"Running '{spec.name}'…")
    try:
        from sarthak.agents.runner import run_agent
        run = await run_agent(spec)
        if run.success:
            await msg.edit_text(_trunc(f"*Done*\n\n{run.output}"), parse_mode="Markdown")
        else:
            await msg.edit_text(f"Agent failed: {run.error}")
    except Exception as exc:
        await msg.edit_text(f"Error: {exc}")
    return ST_IDLE


async def on_ag_logs_id(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> int:
    if not _is_allowed(update, ctx.bot_data["allowed_id"]): return ST_IDLE
    agent_id = (update.message.text or "").strip()
    if not agent_id:
        await update.message.reply_text("Provide an agent ID.")
        return ST_AG_LOGS_ID
    from sarthak.agents.store import load_agent, load_runs
    spec = load_agent(agent_id)
    if not spec:
        await update.message.reply_text(f"Agent not found: `{agent_id}`", parse_mode="Markdown")
        return ST_IDLE
    runs = load_runs(agent_id, limit=3)
    if not runs:
        await update.message.reply_text("No runs yet.")
        return ST_IDLE
    lines = [f"*Agent logs: {spec.name}*\n"]
    for r in runs:
        icon = "+" if r.success else "-"
        lines.append(f"[{icon}] `{r.run_id}` {r.started_at[:19]}")
        if r.output:
            lines.append(r.output[:300])
        if r.error:
            lines.append(f"Error: {r.error[:100]}")
        lines.append("")
    await update.message.reply_text(_trunc("\n".join(lines)), parse_mode="Markdown")
    return ST_IDLE


async def on_ag_toggle_id(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> int:
    if not _is_allowed(update, ctx.bot_data["allowed_id"]): return ST_IDLE
    agent_id = (update.message.text or "").strip()
    if not agent_id:
        await update.message.reply_text("Provide an agent ID.")
        return ST_AG_TOGGLE_ID
    from sarthak.agents.store import load_agent, update_agent
    spec = load_agent(agent_id)
    if not spec:
        await update.message.reply_text(f"Agent not found: `{agent_id}`", parse_mode="Markdown")
        return ST_IDLE
    new_state = not spec.enabled
    update_agent(agent_id, enabled=new_state)
    status = "enabled" if new_state else "disabled"
    await update.message.reply_text(
        f"Agent `{agent_id}` is now *{status}*.", parse_mode="Markdown")
    return ST_IDLE


# ═════════════════════════════════════════════════════════════════════════════
# Config helpers
# ═════════════════════════════════════════════════════════════════════════════

def _apply_model_change(ctx: ContextTypes.DEFAULT_TYPE, provider: str, model_name: str) -> None:
    cfg = ctx.bot_data.get("cfg", {})
    ai  = cfg.setdefault("ai", {})
    ai["default_provider"] = provider
    pc = ai.setdefault(provider, {})
    pc["text_model"] = model_name
    pc["model"]      = model_name
    from sarthak.core.ai_utils.multi_provider import invalidate_agent_cache
    invalidate_agent_cache()
    log.info("model_changed", provider=provider, model=model_name)
    _persist_model_change(provider, model_name)


def _persist_model_change(provider: str, model_name: str) -> None:
    from sarthak.core.config import get_config_path
    config_path = get_config_path()
    try:
        toml_data = tomlkit.parse(config_path.read_text())
    except FileNotFoundError:
        return
    ai = toml_data.setdefault("ai", tomlkit.table())
    ai["default_provider"] = provider
    ai["default_model"]    = model_name
    pc = ai.setdefault(provider, tomlkit.table())
    pc["text_model"] = model_name
    pc["model"]      = model_name
    config_path.write_text(tomlkit.dumps(toml_data))


def _apply_constant_change(name: str, raw: str) -> str:
    from sarthak.core import constants as C
    if not hasattr(C, name):
        return f"Unknown constant: {name}"
    current = getattr(C, name)
    try:
        if isinstance(current, int):
            new_val: Any = int(raw)
        elif isinstance(current, float):
            new_val = float(raw)
        elif isinstance(current, str):
            new_val = raw
        else:
            return f"Cannot edit constant of type {type(current).__name__}."
        setattr(C, name, new_val)
        log.info("constant_changed", name=name, value=new_val)
        return (f"`{name}` set to `{new_val}`\n"
                "_(Runtime only — restart to persist)_")
    except ValueError:
        return f"Invalid value `{raw}` for `{name}` (expected {type(current).__name__})."


def _parse_space_list(text: str) -> list[dict]:
    import re
    items: list[dict] = []
    for line in text.splitlines():
        m = re.match(r"-\s+\*\*(.+?)\*\*\s+`(.+?)`", line.strip())
        if m:
            items.append({"name": m.group(1), "directory": m.group(2)})
    return items


# ═════════════════════════════════════════════════════════════════════════════
# Bot setup
# ═════════════════════════════════════════════════════════════════════════════

async def _set_online(app: Application) -> None:
    try:
        await app.bot.get_me()
        log.info("telegram_bot_online")
    except Exception as exc:
        log.warning("telegram_online_check_failed", error=str(exc))


async def _set_commands(app: Application) -> None:
    commands = [
        BotCommand("start",          "Main menu"),
        BotCommand("today",          "Today's learning dashboard"),
        BotCommand("learn",          "Learning menu"),
        BotCommand("learner_status", "Mastery status"),
        BotCommand("weak_concepts",  "Weak / stuck concepts"),
        BotCommand("roadmap",        "Roadmap progress"),
        BotCommand("my_notes",       "Recent notes"),
        BotCommand("srs_due",        "SRS cards due today"),
        BotCommand("digest",         "Daily learning digest"),
        BotCommand("spaces",         "Spaces menu"),
        BotCommand("skills",         "Skills menu"),
        BotCommand("status",         "Service status"),
        BotCommand("config",         "Config and model"),
        BotCommand("help",           "List all commands"),
        BotCommand("cancel",         "Cancel current action"),
    ]
    await app.bot.set_my_commands(commands)
    await app.bot.set_chat_menu_button(menu_button=MenuButtonCommands())


async def run_bot(cfg: dict[str, Any]) -> None:
    tg = cfg.get("telegram", {})
    if not tg.get("enabled", False):
        log.warning("telegram_disabled", hint="Set [telegram] enabled=true in config.toml")
        return

    from sarthak.storage.encrypt import decrypt_string
    raw_token = tg.get("bot_token", "")
    if not raw_token:
        raise ValueError("telegram.bot_token not set")
    token = decrypt_string(raw_token) if raw_token.startswith("ENC:") else raw_token

    raw_id = tg.get("allowed_user_id")
    if isinstance(raw_id, str):
        raw_id = raw_id.strip()
    if not raw_id:
        raise ValueError("telegram.allowed_user_id not set")
    allowed_id = int(raw_id)

    from telegram.request import HTTPXRequest
    timeout_s = int(tg.get("timeout_seconds", 60))
    request   = HTTPXRequest(
        connect_timeout=timeout_s, read_timeout=timeout_s,
        write_timeout=timeout_s,   pool_timeout=timeout_s,
    )

    app = (
        Application.builder()
        .token(token)
        .request(request)
        .post_init(_set_online)
        .build()
    )
    app.bot_data.update({"allowed_id": allowed_id, "pool": None, "cfg": cfg})

    text_only = filters.TEXT & ~filters.COMMAND

    all_run_keys = list(_CTX_HANDLERS.keys()) + list(_RUN_HANDLERS.keys())

    # per_message=False is intentional (state tracked per-user/chat, not per-message).
    # Suppress the PTB noise about CallbackQueryHandler not being tracked per-message.
    warnings.filterwarnings(
        "ignore",
        message=".*per_message=False.*CallbackQueryHandler.*",
        category=UserWarning,
    )
    conv = ConversationHandler(
        entry_points=[
            CommandHandler("start",   cmd_start),
            CommandHandler("help",    cmd_help),
            CommandHandler("config",  cmd_config),
            CommandHandler("skills",  cmd_skills),
            CommandHandler("spaces",  cmd_spaces),
            CommandHandler("learn",   cmd_learn),
            *[CommandHandler(k, _make_cmd(k)) for k in all_run_keys],
            CallbackQueryHandler(on_callback),
            MessageHandler(text_only, on_plain_message),
        ],
        states={
            ST_IDLE: [
                CommandHandler("help",   cmd_help),
                CommandHandler("start",  cmd_start),
                CommandHandler("config", cmd_config),
                CommandHandler("skills", cmd_skills),
                CommandHandler("spaces", cmd_spaces),
                CommandHandler("learn",  cmd_learn),
                *[CommandHandler(k, _make_cmd(k)) for k in all_run_keys],
                CallbackQueryHandler(on_callback),
                MessageHandler(text_only, on_plain_message),
            ],
            ST_FREE_TEXT: [
                MessageHandler(text_only, on_free_text),
                CallbackQueryHandler(on_callback),
            ],
            ST_SKILL_READ_NAME:    [MessageHandler(text_only, on_skill_read_name)],
            ST_SKILL_DEL_NAME:     [MessageHandler(text_only, on_skill_del_name)],
            ST_SKILL_NEW_NAME:     [MessageHandler(text_only, on_skill_new_name)],
            ST_SKILL_NEW_DESC:     [MessageHandler(text_only, on_skill_new_desc)],
            ST_SKILL_NEW_CONTENT:  [MessageHandler(text_only, on_skill_new_content)],
            ST_CONST_VALUE:        [MessageHandler(text_only, on_const_value)],
            ST_SP_STATUS_DIR:      [MessageHandler(text_only, on_sp_status_dir)],
            ST_SP_INIT_DIR:        [MessageHandler(text_only, on_sp_init_dir)],
            ST_SP_INIT_TYPE: [
                CallbackQueryHandler(on_callback),
                MessageHandler(text_only, on_sp_init_type_text),
            ],
            ST_SP_INIT_BG:         [MessageHandler(text_only, on_sp_init_bg)],
            ST_SP_INIT_NAME:       [MessageHandler(text_only, on_sp_init_name)],
            ST_SP_ACTIVATE_DIR:    [MessageHandler(text_only, on_sp_activate_dir)],
            ST_SP_EVAL_CONCEPT:    [MessageHandler(text_only, on_sp_eval_concept)],
            ST_SP_EVAL_SUBMISSION: [MessageHandler(text_only, on_sp_eval_submission)],
            ST_SP_SETUP_DIR:       [MessageHandler(text_only, on_sp_setup_dir)],
            ST_AG_CREATE_DESC:     [MessageHandler(text_only, on_ag_create_desc)],
            ST_AG_RUN_ID:          [MessageHandler(text_only, on_ag_run_id)],
            ST_AG_LOGS_ID:         [MessageHandler(text_only, on_ag_logs_id)],
            ST_AG_TOGGLE_ID:       [MessageHandler(text_only, on_ag_toggle_id)],
            ST_NOTE_CONCEPT:       [MessageHandler(text_only, on_note_concept)],
            ST_NOTE_CONTENT:       [MessageHandler(text_only, on_note_content)],
        },
        fallbacks=[
            CommandHandler("cancel", on_cancel),
            CommandHandler("help",   cmd_help),
        ],
        per_user=True,
        per_chat=True,
        per_message=False,
        allow_reentry=True,
    )

    app.add_handler(conv)
    log.info("telegram_bot_starting", allowed_user_id=allowed_id)

    async with app:
        await _set_commands(app)
        await app.start()
        await app.updater.start_polling(drop_pending_updates=True)
        log.info("telegram_bot_running")
        try:
            await asyncio.Event().wait()
        except asyncio.CancelledError:
            pass
        finally:
            await app.updater.stop()
            await app.stop()
            log.info("telegram_bot_stopped")
