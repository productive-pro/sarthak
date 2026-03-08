"""
Daily summary agent — text only, no tools.

Also provides structured text agent for classification + extraction.
Stateless global — built once per (provider, model) via the agent registry.
"""
from __future__ import annotations

from pydantic_ai import Agent

from sarthak.features.ai.deps import (
    AgentDeps,
    SarthakResult,
    ActivityInsights,
)
from sarthak.features.ai.agents._base import build_pydantic_model
from sarthak.core.ai_utils.prompts import get_prompt


def _build_structured(
    provider: str,
    model_name: str,
    output_type: type,
    system_prompt_key: str,
    deps_type: type | None = None,
) -> Agent:
    kwargs: dict[str, object] = {
        "output_type": output_type,
        "system_prompt": get_prompt(system_prompt_key),
    }
    if deps_type is not None:
        kwargs["deps_type"] = deps_type
    return Agent(
        build_pydantic_model(provider, model_name),
        **kwargs,
    )


def build(provider: str, model_name: str) -> Agent[AgentDeps, SarthakResult]:
    return _build_structured(
        provider,
        model_name,
        output_type=SarthakResult,
        system_prompt_key="sarthak_agent",
        deps_type=AgentDeps,
    )


def build_activity_insights(provider: str, model_name: str) -> Agent:
    return _build_structured(
        provider,
        model_name,
        output_type=ActivityInsights,
        system_prompt_key="activity_insights_agent",
    )
