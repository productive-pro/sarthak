"""
Sarthak AI — Shared dependency containers and result schemas for all agents.
Import from here to avoid circular imports between agents.py and tools modules.
"""
from __future__ import annotations
from typing import Literal
from pydantic import BaseModel, Field


# ── Shared utility ────────────────────────────────────────────────────────────

_SENSITIVE_KEYS = ("token", "secret", "password", "api_key", "bot_token", "key")


def is_sensitive_key(key: str) -> bool:
    return any(s in key.lower() for s in _SENSITIVE_KEYS)


def sanitize_args(value: object) -> object:
    if isinstance(value, dict):
        return {k: "[REDACTED]" if is_sensitive_key(k) else sanitize_args(v) for k, v in value.items()}
    if isinstance(value, list):
        return [sanitize_args(v) for v in value]
    return value


# ── Dependency containers ─────────────────────────────────────────────────────

class AgentDeps(BaseModel):
    """Runtime dependencies for snapshot / summary agents."""
    model_config = {"arbitrary_types_allowed": True}
    pool: object | None = None
    cwd: str = ""
    allow_web: bool = False
    allow_shell: bool = False


class ChatDeps(BaseModel):
    """Runtime dependencies for the interactive chat agent."""
    model_config = {"arbitrary_types_allowed": True}
    pool: object | None = None
    cwd: str = ""


class OrchestratorDeps(BaseModel):
    """Runtime deps injected into every orchestrator tool via RunContext."""
    model_config = {"arbitrary_types_allowed": True}
    pool: object | None = None
    cwd: str = ""
    allow_web: bool = True
    allow_shell: bool = True


# ── Result schemas ────────────────────────────────────────────────────────────

class SarthakResult(BaseModel):
    """Unified structured output for snapshot analysis and daily summaries."""
    summary: str
    """Short 2-sentence description of what the user is currently doing."""
    detailed: str = ""
    """Full detailed description of what is visible on screen (snapshots only)."""
    recommendation: str = ""
    """Populated ONLY when the agent spots something genuinely useful. Empty otherwise."""


class ChatResult(BaseModel):
    """Structured response for chat UI rendering."""
    normal_response: str
    dw_sql: str = ""
    answer: str = ""  # backward-compat alias


class OrchestratorResult(BaseModel):
    """Structured reply from the orchestrator agent."""
    reply: str
    """Markdown-formatted reply shown to the user."""
    action_taken: str = ""
    """Short one-line description of what the agent did (for logging)."""
    skill_created: str = ""
    """Non-empty if the agent created/updated a skill (skill name)."""


class ActivityClassification(BaseModel):
    category: Literal[
        "coding", "browsing", "reading", "communication",
        "design", "debugging", "research", "admin", "idle", "unknown"
    ]
    confidence: float = Field(ge=0.0, le=1.0)
    reasoning: str = Field(description="Brief explanation for this classification")


class ConceptExtraction(BaseModel):
    tags: list[str] = Field(default_factory=list)
    topic: str = ""
    intent: str = ""


class ActivityInsights(BaseModel):
    """Combined classification + extraction from a single structured agent call."""
    classification: ActivityClassification
    extraction: ConceptExtraction
