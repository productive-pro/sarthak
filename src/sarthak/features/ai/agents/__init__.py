"""
Agent registry — single entry point for all PydanticAI agents.

Usage
-----
    from sarthak.features.ai.agents import get_agent
    agent = get_agent("orchestrator")          # full capability
    agent = get_agent("vision", provider="openai", model_name="gpt-4o")

Available names: vision, summary, activity_insights, orchestrator

Architecture (pydantic-ai Agent Delegation pattern):
  orchestrator  ─── delegates to ──► vision  (snapshot analysis)
                                   ► summary (daily digest)
  activity_insights  – structured output: classification + extraction
"""
from __future__ import annotations

from pydantic_ai import Agent

from sarthak.features.ai.agents._base import resolve_provider_model
from sarthak.core.logging import get_logger

log = get_logger(__name__)

# ── Lazy builder registry ────────────────────────────────────────────────────

_BUILDERS: dict[str, object] = {}


def _get_builders() -> dict[str, object]:
    if not _BUILDERS:
        from sarthak.features.ai.agents import (
            vision, summary, orchestrator
        )
        _BUILDERS.update({
            "vision":       vision.build,
            "summary":      summary.build,
            "activity_insights": summary.build_activity_insights,
            "orchestrator": orchestrator.build,
        })
    return _BUILDERS


# ── Per-name cache (provider, model) → Agent ─────────────────────────────────

_caches: dict[str, dict[tuple[str, str], Agent]] = {
    "vision": {}, "summary": {}, "activity_insights": {}, "orchestrator": {},
}


def get_agent(
    name: str,
    provider: str | None = None,
    model_name: str | None = None,
) -> Agent:
    """
    Return a cached agent by name, building on first call per (provider, model).

    Parameters
    ----------
    name        : one of vision | summary | activity_insights | orchestrator
    provider    : override config default provider
    model_name  : override config default model
    """
    builders = _get_builders()
    if name not in builders:
        raise ValueError(f"Unknown agent: {name!r}. Choose from: {list(builders)}")
    p, m = resolve_provider_model(provider, model_name)
    cache = _caches.setdefault(name, {})
    if (p, m) not in cache:
        log.debug("agent_build", agent=name, provider=p, model=m)
        cache[(p, m)] = builders[name](p, m)
    return cache[(p, m)]


__all__ = ["get_agent"]
