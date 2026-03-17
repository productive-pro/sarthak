"""
Sarthak AI — Public API & Context Budget Management.

All agent access goes through this module.

Public surface:
  get_agent / invalidate_cache  — agent registry (re-exported)
  ask_orchestrator(question, …) — intent-classified, history-compacted, logged
  stream_orchestrator(…)        — streaming variant used by all channels
  analyse_snapshot / generate_daily_summary / classify_activity / extract_concepts

Context budget (OpenCode / Claude Code style):
  _classify_intent   — keyword → minimal tool_groups (<1 ms, zero LLM cost)
  _compact_history   — summarise old turns when history > COMPACT_THRESHOLD
  Both ask_orchestrator AND stream_orchestrator apply compaction before the call.
"""
from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator

from sarthak.features.ai.agents import get_agent, invalidate_cache        # noqa: F401
from sarthak.features.ai.agents import _caches                             # noqa: F401
from sarthak.features.ai.deps import (                                     # noqa: F401
    AgentDeps, OrchestratorDeps, SarthakResult, OrchestratorResult,
    ActivityClassification, ConceptExtraction, ActivityInsights,
    ChatDeps, ChatResult,
)
from sarthak.core.constants import (
    DAILY_SUMMARY_CONTEXT_LIMIT, DAILY_SUMMARY_PREV_LIMIT, CLASSIFY_MAX_EVENTS,
)
from sarthak.core.logging import (
    enable_file_logging, get_logger, get_orchestration_log_path, setup_logging,
)
from sarthak.core.ai_utils.prompts import get_prompt

log = get_logger(__name__)

# ── Context budget constants ──────────────────────────────────────────────────
_MAX_HISTORY       = 40   # hard cap: 20 pairs × 2 messages
_COMPACT_THRESHOLD = 32   # compact when history exceeds this many messages

# ── Intent pre-classifier ─────────────────────────────────────────────────────
# Zero LLM cost keyword → tool_groups mapping. <1 ms per call.

_KW: dict[str, frozenset[str]] = {
    "delegation": frozenset({"screenshot", "snapshot", "vision", "what's on screen",
                             "daily summary", "daily digest"}),
    "spaces":     frozenset({"learn", "study", "session", "concept", "roadmap", "srs",
                             "review", "space", "teach", "explain", "understand", "practice",
                             "task", "quiz", "evaluate", "mastery", "progress", "skill level",
                             "what next", "next concept", "cards", "streak", "xp", "badge"}),
    "activity":   frozenset({"activity", "worked on", "what did i do", "summary", "digest",
                             "today", "yesterday", "this week", "tip", "tips", "log"}),
    "system":     frozenset({"service", "restart", "status", "health", "server", "running",
                             "memory usage", "cpu", "process"}),
    "shell":      frozenset({"run", "execute", "shell", "command", "bash", "terminal",
                             "script", "list files", "ls ", "pwd", "git "}),
    "rag":        frozenset({"search files", "find in files", "rag", "index", "re-index",
                             "search workspace", "search notes", "find notes"}),
    "workspace":  frozenset({"workspace", "analyse workspace", "optimal learn",
                             "sessions this week", "what are my notes", "struggling with"}),
    "skills":     frozenset({"skill", "save skill", "list skills", "read skill", "delete skill"}),
}

_DEFAULT_GROUPS = frozenset({"activity", "spaces", "skills", "web"})


def _classify_intent(
    question: str, allow_web: bool = True, allow_shell: bool = True
) -> frozenset[str]:
    """Return minimal tool groups for this question (zero LLM cost)."""
    q = question.lower()
    groups: set[str] = set()
    for group, kws in _KW.items():
        if group == "shell" and not allow_shell:
            continue
        if any(kw in q for kw in kws):
            groups.add(group)
    if "spaces" in groups:
        groups.add("rag")
    if "workspace" in groups:
        groups.add("spaces")
    if allow_web and (
        "search" in q or "latest" in q or "current" in q or "news" in q
        or "what is " in q or "how to " in q or not groups
    ):
        groups.add("web")
    return frozenset(groups) if groups else _DEFAULT_GROUPS


# ── Context compaction (OpenCode / Claude Code pattern) ───────────────────────

async def _compact_history(history: list) -> list:
    """
    Summarise old conversation turns when history exceeds _COMPACT_THRESHOLD.

    Strategy (mirrors OpenCode compaction.ts):
      - Keep the most recent _MAX_HISTORY messages intact.
      - Summarise everything older into one synthetic assistant message.
      - Uses the fast model (no deep reasoning needed for summarisation).
      - Never mutates the input list.
    Returns the (possibly shorter) history list.
    """
    if len(history) <= _COMPACT_THRESHOLD:
        return history

    from pydantic_ai.messages import ModelRequest, ModelResponse, UserPromptPart, TextPart
    from sarthak.features.ai.agents._base import run_llm

    keep_n   = _MAX_HISTORY
    old_msgs = history[:-keep_n]
    recent   = history[-keep_n:]

    lines: list[str] = []
    for msg in old_msgs:
        if isinstance(msg, ModelRequest):
            for p in msg.parts:
                if hasattr(p, "content"):
                    lines.append(f"User: {str(p.content)[:300]}")
        elif isinstance(msg, ModelResponse):
            for p in msg.parts:
                if hasattr(p, "content"):
                    lines.append(f"Assistant: {str(p.content)[:300]}")

    try:
        summary = await run_llm(
            system=(
                "Summarize this conversation history as compact bullet points. "
                "Preserve: decisions, facts established, concepts taught/learned. "
                "Drop: greetings, filler, tool call details. Max 200 words."
            ),
            user="\n".join(lines),
            tier="fast",
            agent="history_compactor",
        )
        log.info("history_compacted", old=len(old_msgs), kept=keep_n, chars=len(summary))
        return [ModelResponse(parts=[TextPart(
            content=f"[Conversation summary]\n{summary}"
        )])] + recent
    except Exception as exc:
        log.warning("history_compact_failed", error=str(exc))
        return recent  # fallback: just truncate


# ── Memory extraction helper ──────────────────────────────────────────────────

def _fire_memory_extraction(cwd: str, question: str, reply: str, action: str) -> None:
    """Fire-and-forget memory extraction after a learning exchange."""
    if not cwd or not reply:
        return
    if not any(p in (action or "") for p in ("Taught:", "Evaluated:", "QuickTest:", "Session", "spaces")):
        return
    try:
        from pathlib import Path as _P
        from sarthak.spaces.store import load_profile as _lp
        from sarthak.spaces.memory import extract_memory_from_exchange as _em
        profile = _lp(_P(cwd))
        if not profile:
            return
        try:
            loop = asyncio.get_running_loop()
            loop.create_task(_em(_P(cwd), question, reply, profile))
        except RuntimeError:
            pass  # no running event loop — skip fire-and-forget
    except Exception:
        pass


# ── Main orchestrator entry point ─────────────────────────────────────────────

async def ask_orchestrator(
    question: str,
    pool: object | None = None,
    allow_web: bool = True,
    allow_shell: bool = True,
    cwd: str = "",
    provider: str | None = None,
    model_name: str | None = None,
    message_history: list | None = None,
    tool_groups: "frozenset[str] | None" = None,
) -> OrchestratorResult:
    """
    Non-streaming orchestrator call. Returns OrchestratorResult.

    Pipeline:
      1. Intent classification → minimal tool_groups (30-50% token saving)
      2. History compaction   → never exceeds _COMPACT_THRESHOLD messages
      3. Agent.run()          → pydantic-ai tool loop
      4. Logging + memory     → fire-and-forget
    """
    from sarthak.core.config import load_config
    from sarthak.features.ai.agents._base import resolve_provider_model

    cfg = load_config()
    enable_file_logging(get_orchestration_log_path())
    setup_logging(cfg)

    p, m = resolve_provider_model(provider, model_name)
    groups = tool_groups or _classify_intent(question, allow_web=allow_web, allow_shell=allow_shell)
    log.debug("orchestrator_groups", groups=sorted(groups), q_len=len(question))

    history = message_history or []
    if len(history) > _COMPACT_THRESHOLD:
        history = await _compact_history(history)

    agent = get_agent("orchestrator", provider=p, model_name=m, tool_groups=groups)
    deps  = OrchestratorDeps(pool=pool, cwd=cwd, allow_web=allow_web,
                             allow_shell=allow_shell, question_hint=question)
    try:
        result = await agent.run(question, deps=deps, message_history=history)
        output: OrchestratorResult = result.output

        from sarthak.core.ai_utils.prompt_logger import log_llm_call
        from pydantic_ai.messages import ModelRequest, SystemPromptPart
        sys_parts = [f"provider={p} model={m}"]
        try:
            for msg in result.all_messages():
                if isinstance(msg, ModelRequest):
                    sys_parts.extend(
                        part.content for part in msg.parts
                        if isinstance(part, SystemPromptPart)
                    )
        except Exception:
            pass
        log_llm_call(agent="orchestrator", system="\n\n".join(sys_parts),
                     prompt=question,
                     response=f"[action={output.action_taken}]\n\n{output.reply or ''}")
        log.info("orchestrator_result", action=output.action_taken,
                 reply_len=len(output.reply or ""), provider=p, model=m)

        _fire_memory_extraction(cwd, question, output.reply or "", output.action_taken)
        return output

    except Exception as exc:
        log.error("orchestrator_failed", error=str(exc), type=type(exc).__name__)
        return OrchestratorResult(
            reply=f"Agent error: {type(exc).__name__}: {exc}", action_taken="error"
        )


# ── Streaming orchestrator ────────────────────────────────────────────────────

async def stream_orchestrator(
    question: str,
    pool: object | None = None,
    allow_web: bool = True,
    allow_shell: bool = True,
    cwd: str = "",
    provider: str | None = None,
    model_name: str | None = None,
    message_history: list | None = None,
    session_id: str | None = None,
) -> AsyncIterator[str]:
    """
    Streaming orchestrator — yields partial OrchestratorResult.reply strings.

    Applies the same intent classification and history compaction as
    ask_orchestrator before streaming. Caller is responsible for
    save_chat_turn after the stream completes.
    """
    from sarthak.features.ai.agents._base import resolve_provider_model
    from sarthak.features.ai.deps import OrchestratorDeps

    # Load history only if not already supplied — never load when message_history is passed
    history = message_history
    if history is None:
        if session_id:
            from sarthak.features.channels import load_history_messages
            history = await load_history_messages(session_id)
        else:
            history = []

    if len(history) > _COMPACT_THRESHOLD:
        history = await _compact_history(history)

    p, m  = resolve_provider_model(provider, model_name)
    groups = _classify_intent(question, allow_web=allow_web, allow_shell=allow_shell)
    log.debug("stream_orchestrator_groups", groups=sorted(groups), q_len=len(question))

    agent = get_agent("orchestrator", provider=p, model_name=m, tool_groups=groups)
    deps  = OrchestratorDeps(pool=pool, cwd=cwd, allow_web=allow_web,
                             allow_shell=allow_shell, question_hint=question)
    final_reply = ""
    try:
        async with agent.run_stream(question, deps=deps, message_history=history) as stream:
            async for partial in stream.stream_output(debounce_by=0.05):
                reply = partial.reply if partial.reply else ""
                if reply:
                    final_reply = reply
                    yield reply
    except Exception as exc:
        log.error("stream_orchestrator_failed", error=str(exc))
        raise

    _fire_memory_extraction(cwd, question, final_reply, "")


# ── Specialist agents ─────────────────────────────────────────────────────────

async def analyse_snapshot(
    png_bytes: bytes, active_app: str, deps: AgentDeps,
    context: str | None = None, provider: str | None = None, model_name: str | None = None,
) -> SarthakResult:
    from pydantic_ai import BinaryContent
    from sarthak.core.ai_utils.prompt_logger import log_llm_call
    from sarthak.features.ai.agents._base import record_alert
    agent  = get_agent("vision", provider=provider, model_name=model_name)
    ctx_block = f"\nRecent activity log context:\n{context}" if context else ""
    prompt = get_prompt("sarthak_agent", "snapshot_prompt").format(
        active_app=active_app, context_block=ctx_block)
    try:
        result = await agent.run([prompt, BinaryContent(data=png_bytes, media_type="image/png")], deps=deps)
        output: SarthakResult = result.output
        log_llm_call(agent="vision", system="[vision]", prompt=prompt, response=output.summary)
        return output
    except Exception as exc:
        log.error("snapshot_agent_failed", error=str(exc))
        await record_alert(deps.pool, "error", "llm.snapshot", str(exc))
        return SarthakResult(summary="Snapshot analysis unavailable.", detailed="", recommendation="")


async def generate_daily_summary(
    events_context: str, date_str: str, deps: AgentDeps,
    previous_summary: str | None = None, provider: str | None = None, model_name: str | None = None,
) -> SarthakResult:
    from sarthak.core.ai_utils.prompt_logger import log_llm_call
    from sarthak.features.ai.agents._base import record_alert
    agent = get_agent("summary", provider=provider, model_name=model_name)
    prev_block = (
        f"Previous summary:\n{(previous_summary or '').strip()[:DAILY_SUMMARY_PREV_LIMIT]}\n\n"
        if previous_summary else ""
    )
    prompt = get_prompt("sarthak_agent", "daily_summary_prompt").format(
        date_str=date_str, prev_block=prev_block,
        context_snippet=events_context[:DAILY_SUMMARY_CONTEXT_LIMIT])
    try:
        result = await agent.run(prompt, deps=deps)
        output: SarthakResult = result.output
        log_llm_call(agent="summary", system="[summary]", prompt=prompt, response=output.summary)
        return output
    except Exception as exc:
        log.error("daily_summary_failed", error=str(exc))
        await record_alert(deps.pool, "error", "llm.summary", str(exc), {"date": date_str})
        return SarthakResult(
            summary=previous_summary or f"Summary unavailable for {date_str}.",
            detailed="", recommendation="",
        )


async def classify_activity(events: list[dict]) -> ActivityClassification:
    from sarthak.core.ai_utils.normalize import build_activity_csv
    context_str = build_activity_csv(events[-CLASSIFY_MAX_EVENTS:])
    if context_str.count("\n") < 1:
        return ActivityClassification(category="unknown", confidence=0.0, reasoning="no events")
    try:
        return (await analyze_activity(context_str)).classification
    except Exception as exc:
        log.warning("classification_failed", error=str(exc))
        return ActivityClassification(category="unknown", confidence=0.0, reasoning=str(exc))


async def extract_concepts(context_str: str) -> ConceptExtraction:
    if not context_str.strip():
        return ConceptExtraction()
    try:
        return (await analyze_activity(context_str)).extraction
    except Exception as exc:
        log.warning("extraction_failed", error=str(exc))
        return ConceptExtraction()


async def analyze_activity(context_str: str) -> ActivityInsights:
    """Single structured call: classification + extraction. SHA-256 keyed cache."""
    from hashlib import sha256
    from sarthak.core.ai_utils.prompt_logger import log_llm_call
    from sarthak.storage.factory import cached
    key = sha256(context_str.encode()).hexdigest()

    async def _compute() -> dict:
        agent = get_agent("activity_insights")
        result = await agent.run(context_str)
        output: ActivityInsights = result.output
        log_llm_call(agent="activity_insights", system="[activity_insights]",
                     prompt=context_str, response=str(output.model_dump()))
        return output.model_dump()

    return ActivityInsights.model_validate(await cached(f"ai:{key}", _compute, ttl=300))
