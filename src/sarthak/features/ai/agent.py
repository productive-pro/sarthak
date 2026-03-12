"""
Sarthak AI — Public API.

All agent access goes through this module. The agents subpackage contains
the actual builders; this file re-exports the unified entry point and the
high-level async functions used by callers throughout the codebase.

Public surface
--------------
  get_agent(name, provider, model_name)  → Agent
  analyse_snapshot(...)                  → SarthakResult
  generate_daily_summary(...)            → SarthakResult
  classify_activity(events)             → ActivityClassification
  extract_concepts(context_str)         → ConceptExtraction
  ask_orchestrator(question, ...)       → OrchestratorResult
"""
from __future__ import annotations


# Re-export the single entry point
from sarthak.features.ai.agents import get_agent  # noqa: F401

# Re-export all shared types so callers only need one import
from sarthak.features.ai.deps import (  # noqa: F401
    AgentDeps,
    OrchestratorDeps,
    SarthakResult,
    OrchestratorResult,
    ActivityClassification,
    ConceptExtraction,
    ActivityInsights,
    ChatDeps,
    ChatResult,
)

from sarthak.core.constants import (
    DAILY_SUMMARY_CONTEXT_LIMIT,
    DAILY_SUMMARY_PREV_LIMIT,
    CLASSIFY_MAX_EVENTS,
)
from sarthak.core.logging import (
    enable_file_logging,
    get_logger,
    get_orchestration_log_path,
    setup_logging,
)
from sarthak.core.ai_utils.prompts import get_prompt

log = get_logger(__name__)

# Expose agent caches so Telegram bot can invalidate on model change
from sarthak.features.ai.agents import _caches  # noqa: F401



# ── Internal helpers ───────────────────────────────────────────────────────────

def _agent_result_output(result):
    """
    Extract structured output from a pydantic-ai RunResult.

    pydantic-ai uses result.output in current versions. Raises AttributeError
    with a clear message if neither attribute exists, instead of silently
    returning None (which was the previous hasattr/else anti-pattern).
    """
    try:
        return result.output
    except AttributeError:
        raise AttributeError(
            f"RunResult has no .output attribute. "
            f"Available attributes: {[a for a in dir(result) if not a.startswith('_')]}"
        )


# ══════════════════════════════════════════════════════════════════════════════
# High-level async functions
# ══════════════════════════════════════════════════════════════════════════════

async def analyse_snapshot(
    png_bytes: bytes,
    active_app: str,
    deps: AgentDeps,
    context: str | None = None,
    provider: str | None = None,
    model_name: str | None = None,
) -> SarthakResult:
    """Run snapshot analysis agent on a PNG screenshot."""
    from pydantic_ai import BinaryContent
    from sarthak.core.ai_utils.prompt_logger import log_llm_call
    from sarthak.features.ai.agents._base import record_alert

    agent = get_agent("vision", provider=provider, model_name=model_name)
    ctx_block = f"\nRecent activity log context:\n{context}" if context else ""
    prompt = get_prompt("sarthak_agent", "snapshot_prompt").format(
        active_app=active_app, context_block=ctx_block
    )
    log.debug("snapshot_agent_run", app=active_app)
    try:
        result = await agent.run(
            [prompt, BinaryContent(data=png_bytes, media_type="image/png")], deps=deps
        )
        output: SarthakResult = result.output
        log_llm_call(agent="vision", system="[vision]", prompt=prompt, response=output.summary)
        return output
    except Exception as exc:
        log.error("snapshot_agent_failed", error=str(exc))
        await record_alert(deps.pool, "error", "llm.snapshot", str(exc))
        return SarthakResult(
            summary="Snapshot analysis unavailable.", detailed="", recommendation=""
        )


async def generate_daily_summary(
    events_context: str,
    date_str: str,
    deps: AgentDeps,
    previous_summary: str | None = None,
    provider: str | None = None,
    model_name: str | None = None,
) -> SarthakResult:
    """Run the daily summary agent on an events context string."""
    from sarthak.core.ai_utils.prompt_logger import log_llm_call
    from sarthak.features.ai.agents._base import record_alert

    agent = get_agent("summary", provider=provider, model_name=model_name)
    context_snippet = events_context[:DAILY_SUMMARY_CONTEXT_LIMIT]
    prev_block = (
        f"Previous summary:\n{(previous_summary or '').strip()[:DAILY_SUMMARY_PREV_LIMIT]}\n\n"
        if previous_summary else ""
    )
    prompt = get_prompt("sarthak_agent", "daily_summary_prompt").format(
        date_str=date_str, prev_block=prev_block, context_snippet=context_snippet
    )
    log.debug("daily_summary_run", date=date_str, context_chars=len(context_snippet))
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
            detailed="",
            recommendation="",
        )


async def classify_activity(events: list[dict]) -> ActivityClassification:
    """Classify recent activity events (stats only, no raw rows)."""
    from sarthak.core.ai_utils.normalize import build_activity_csv

    context_str = build_activity_csv(events[-CLASSIFY_MAX_EVENTS:])
    if context_str.count("\n") < 1:
        return ActivityClassification(
            category="unknown", confidence=0.0, reasoning="no events"
        )
    try:
        return (await analyze_activity(context_str)).classification
    except Exception as exc:
        log.warning("classification_failed", error=str(exc))
        return ActivityClassification(category="unknown", confidence=0.0, reasoning=str(exc))


async def extract_concepts(context_str: str) -> ConceptExtraction:
    """Extract tags and intent from a context string."""
    if not context_str.strip():
        return ConceptExtraction()
    try:
        return (await analyze_activity(context_str)).extraction
    except Exception as exc:
        log.warning("extraction_failed", error=str(exc))
        return ConceptExtraction()


async def analyze_activity(context_str: str) -> ActivityInsights:
    """
    Single structured agent call: classification + extraction.

    Results are cached by SHA-256 of the input (LRU, max 8 entries).
    Streaming via run_stream + stream_output so partial results are
    available for the TUI without blocking.
    """
    from hashlib import sha256
    from sarthak.core.ai_utils.prompt_logger import log_llm_call
    from sarthak.storage.factory import cached

    key = sha256(context_str.encode("utf-8")).hexdigest()

    async def _compute() -> dict:
        agent = get_agent("activity_insights")
        result = await agent.run(context_str)
        output: ActivityInsights = _agent_result_output(result)
        log_llm_call(agent="activity_insights", system="[activity_insights]", prompt=context_str, response=str(output.model_dump()))
        return output.model_dump()

    data = await cached(f"activity_insights:{key}", _compute, ttl=300)
    return ActivityInsights.model_validate(data)


def _is_spaces_action(action_taken: str | None) -> bool:
    """True if the orchestrator did something learning-related worth remembering."""
    if not action_taken:
        return False
    prefixes = ("Taught:", "Evaluated:", "QuickTest:", "Session", "spaces")
    return any(action_taken.startswith(p) or p in action_taken for p in prefixes)


async def ask_orchestrator(
    question: str,
    pool: object | None = None,
    allow_web: bool = True,
    allow_shell: bool = True,
    cwd: str = "",
    provider: str | None = None,
    model_name: str | None = None,
    message_history: list | None = None,
) -> OrchestratorResult:
    """Ask the orchestrator agent. Returns a structured OrchestratorResult."""
    from sarthak.core.config import load_config
    from sarthak.features.ai.agents._base import resolve_provider_model

    cfg = load_config()
    enable_file_logging(get_orchestration_log_path())
    setup_logging(cfg)

    resolved_provider, resolved_model = resolve_provider_model(provider, model_name)
    agent = get_agent("orchestrator", provider=provider, model_name=model_name)
    deps  = OrchestratorDeps(
        pool=pool, cwd=cwd, allow_web=allow_web, allow_shell=allow_shell
    )
    history = message_history or []

    try:
        result = await agent.run(question, deps=deps, message_history=history)
        output: OrchestratorResult = result.output
        from sarthak.core.ai_utils.prompt_logger import log_llm_call

        # Collect the full system prompt from pydantic-ai message history
        _system_parts: list[str] = [f"provider={resolved_provider} model={resolved_model}"]
        try:
            from pydantic_ai.messages import ModelRequest, SystemPromptPart
            for msg in result.all_messages():
                if isinstance(msg, ModelRequest):
                    for part in msg.parts:
                        if isinstance(part, SystemPromptPart):
                            _system_parts.append(part.content)
        except Exception:
            pass

        log_llm_call(
            agent="orchestrator",
            system="\n\n".join(_system_parts),
            prompt=question,
            response=f"[action={output.action_taken}]\n\n{output.reply or ''}",
        )
        log.info(
            "orchestrator_result",
            action=output.action_taken,
            reply_len=len(output.reply or ""),
            provider=resolved_provider,
            model=resolved_model,
        )

        # Fire-and-forget: extract behavioural pattern if this was a spaces learning exchange
        if cwd and output.reply and _is_spaces_action(output.action_taken):
            import asyncio as _aio
            from pathlib import Path as _Path
            from sarthak.spaces.store import load_profile as _load_profile
            from sarthak.spaces.memory import extract_memory_from_exchange as _extract
            _space_dir = _Path(cwd)
            _profile = _load_profile(_space_dir)
            if _profile:
                _aio.create_task(
                    _extract(_space_dir, question, output.reply, _profile)
                )

        return output

    except Exception as exc:
        error_text = str(exc) or repr(exc)
        log.error("orchestrator_failed", error=error_text, error_type=type(exc).__name__)
        reply = f"Agent error: {type(exc).__name__}: {error_text}"
        return OrchestratorResult(reply=reply, action_taken="error")
