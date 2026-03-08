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

from collections import OrderedDict

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

# ── LRU cache for analyze_activity ────────────────────────────────────────────
_INSIGHTS_CACHE: OrderedDict[str, ActivityInsights] = OrderedDict()
_INSIGHTS_CACHE_MAX = 8


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
    from sarthak.core.ai_utils.prompt_logger import log_prompt
    from sarthak.features.ai.agents._base import record_alert

    agent = get_agent("vision", provider=provider, model_name=model_name)
    ctx_block = f"\nRecent activity log context:\n{context}" if context else ""
    prompt = get_prompt("sarthak_agent", "snapshot_prompt").format(
        active_app=active_app, context_block=ctx_block
    )
    log.debug("snapshot_agent_run", app=active_app)
    log_prompt("snapshot_analysis", prompt)
    try:
        result = await agent.run(
            [prompt, BinaryContent(data=png_bytes, media_type="image/png")], deps=deps
        )
        return result.output
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
    from sarthak.core.ai_utils.prompt_logger import log_prompt
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
    log_prompt("daily_summary", prompt)
    try:
        result = await agent.run(prompt, deps=deps)
        return result.output
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
    from sarthak.core.ai_utils.prompt_logger import log_prompt

    key = sha256(context_str.encode("utf-8")).hexdigest()
    if key in _INSIGHTS_CACHE:
        _INSIGHTS_CACHE.move_to_end(key)
        return _INSIGHTS_CACHE[key]

    log_prompt("activity_insights", context_str)
    agent = get_agent("activity_insights")

    async with agent.run_stream(context_str) as stream:
        # Drain the stream; we only need the final structured output
        async for _ in stream.stream_output(debounce_by=0.05):
            pass
        result = await stream.get_output()

    # BUG-03 fix: use .output directly — pydantic-ai current API.
    # _agent_result_output raises a clear AttributeError instead of silently
    # returning None when the API changes.
    output: ActivityInsights = _agent_result_output(result)

    _INSIGHTS_CACHE[key] = output
    _INSIGHTS_CACHE.move_to_end(key)
    if len(_INSIGHTS_CACHE) > _INSIGHTS_CACHE_MAX:
        _INSIGHTS_CACHE.popitem(last=False)

    return output


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

    log.info(
        "agent_prompt",
        agent="orchestrator",
        provider=resolved_provider,
        model=resolved_model,
        prompt_len=len(question),
        # Only log full prompt for local/privacy-safe providers
        **({"prompt": question} if resolved_provider == "ollama" else {}),
    )

    try:
        result = await agent.run(question, deps=deps, message_history=history)
        output: OrchestratorResult = result.output

        log.info(
            "agent_response",
            agent="orchestrator",
            provider=resolved_provider,
            model=resolved_model,
            action=output.action_taken,
            response_len=len(output.reply or ""),
            **({"response": output.reply} if resolved_provider == "ollama" else {}),
        )
        return output

    except Exception as exc:
        error_text = str(exc) or repr(exc)
        log.error("orchestrator_failed", error=error_text, error_type=type(exc).__name__)
        reply = f"Agent error: {type(exc).__name__}: {error_text}"
        return OrchestratorResult(reply=reply, action_taken="error")
