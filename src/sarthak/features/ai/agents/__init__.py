"""
Agent registry — single entry point for all pydantic-ai agents.

Patterns from pydantic-ai multi-agent docs:
  - Sub-agents share usage via ctx.usage so token tracking flows up
  - Agent cache keyed on (provider, model, tool_groups) — rebuilt on config change
  - Lazy builder loading — imports happen at first build, not at import time

Usage:
    from sarthak.features.ai.agents import get_agent, invalidate_cache
    agent = get_agent("orchestrator", tool_groups=frozenset({"activity", "web"}))
    agent = get_agent("vision", provider="openai", model_name="gpt-4o")
"""
from __future__ import annotations

from pydantic_ai import Agent

from sarthak.features.ai.agents._base import resolve_provider_model
from sarthak.core.logging import get_logger

log = get_logger(__name__)

# ── Lazy builder registry ─────────────────────────────────────────────────────
# Keys: agent name → callable(provider, model, **kwargs) → Agent
# Populated on first call to avoid circular imports at module load.

_BUILDERS: dict[str, object] = {}


def _builders() -> dict[str, object]:
    if not _BUILDERS:
        from sarthak.features.ai.agents import vision, summary, orchestrator
        _BUILDERS.update({
            "vision":            vision.build,
            "summary":           summary.build,
            "activity_insights": summary.build_activity_insights,
            "orchestrator":      orchestrator.build,
        })
    return _BUILDERS


# ── Per-agent cache: (provider, model[, groups]) → Agent ─────────────────────
_caches: dict[str, dict[tuple, Agent]] = {}


def get_agent(
    name: str,
    provider: str | None = None,
    model_name: str | None = None,
    tool_groups: "frozenset[str] | None" = None,
) -> Agent:
    """Return a cached agent, building on first access per (provider, model[, groups]).

    For the orchestrator, tool_groups is included in the cache key so lean
    intent-matched builds are cached separately from the full build.
    Sub-agents receive shared usage tracking via ctx.usage (pydantic-ai pattern).
    """
    builders = _builders()
    if name not in builders:
        raise ValueError(f"Unknown agent: {name!r}. Available: {list(builders)}")

    p, m = resolve_provider_model(provider, model_name)
    cache = _caches.setdefault(name, {})

    cache_key: tuple = (p, m, frozenset(tool_groups)) if (name == "orchestrator" and tool_groups) else (p, m)

    if cache_key not in cache:
        log.debug("agent_build", name=name, provider=p, model=m,
                  groups=sorted(tool_groups) if tool_groups else "all")
        builder = builders[name]
        if name == "orchestrator" and tool_groups is not None:
            cache[cache_key] = builder(p, m, tool_groups=tool_groups)
        else:
            cache[cache_key] = builder(p, m)

    return cache[cache_key]


def invalidate_cache(name: str | None = None) -> None:
    """Invalidate agent cache on model/config change.

    name=None clears all agents; name='orchestrator' clears only that agent.
    """
    if name is None:
        _caches.clear()
        _BUILDERS.clear()
        log.debug("agent_cache_cleared_all")
    else:
        _caches.pop(name, None)
        log.debug("agent_cache_cleared", name=name)


__all__ = ["get_agent", "invalidate_cache", "_caches"]
