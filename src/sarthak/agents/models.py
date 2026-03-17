"""
Sarthak Agent Engine — data models.

An Agent is a named, scheduled automation that:
- Receives a prompt/task description
- Can call tools (web search, shell, etc.)
- Saves its output to a run history file
- Optionally sends the result to Telegram

Agents can be scoped to a Space (stored in <space_dir>/.spaces/agents/)
or global (stored in ~/.sarthak_ai/agents/).
"""
from __future__ import annotations

from datetime import datetime, timezone
from enum import Enum
from typing import Any, Literal

from pydantic import BaseModel, Field


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


class AgentScope(str, Enum):
    GLOBAL = "global"    # ~/.sarthak_ai/agents/
    SPACE  = "space"     # <space_dir>/.spaces/agents/


class AgentTool(str, Enum):
    WEB_SEARCH  = "web_search"
    SHELL       = "shell"
    FILE_READ   = "file_read"
    FILE_WRITE  = "file_write"
    HTTP_FETCH  = "http_fetch"


# ── Model tier ────────────────────────────────────────────────────────────────
ModelTier = Literal["fast", "balanced", "powerful"]
"""
fast     → low-latency, low-cost  (haiku / gpt-4o-mini / gemini-flash)
balanced → default quality        (sonnet / gpt-4o)             [DEFAULT]
powerful → deep-reasoning tasks   (opus / gpt-4o)

Resolved in multi_provider.py via FAST_MODELS / DEFAULT_MODELS / LATEST_MODELS.
"""


class SandboxPolicy(BaseModel):
    """Per-agent overrides for sandbox resource limits and capability flags."""
    wall_timeout:  int | None  = None
    memory_cap:    int | None  = None
    cpu_seconds:   int | None  = None
    output_cap:    int | None  = None
    max_web_calls: int | None  = None
    allow_web:   bool | None = None
    allow_shell: bool | None = None


class AgentSpec(BaseModel):
    """Persistent definition of a custom agent."""
    agent_id: str
    name: str
    description: str = ""
    prompt: str
    schedule: str
    tools: list[AgentTool] = Field(default_factory=list)
    scope: AgentScope = AgentScope.GLOBAL
    space_dir: str = ""
    context_space_dirs: list[str] = Field(default_factory=list)
    notify_telegram: bool = False
    notify_whatsapp: bool = False
    enabled: bool = True
    created_at: str = Field(default_factory=_now)
    updated_at: str = Field(default_factory=_now)
    last_run_at: str = ""
    next_run_at: str = ""
    extra: dict[str, Any] = Field(default_factory=dict)
    sandbox: SandboxPolicy = Field(default_factory=SandboxPolicy)

    # ── Strategy: model tier ───────────────────────────────────────────────
    model_tier: ModelTier = "balanced"
    """
    fast     → srs-push, recommendations  (latency + cost sensitive)
    balanced → daily-digest, orchestrator (default)
    powerful → weekly-digest, deep analysis (quality-first)
    """

    # ── Strategy: persistent agent memory ─────────────────────────────────
    enable_memory: bool = False
    """
    When True the agent reads the last N run summaries from its memory dir
    before each run, and writes a brief note after each successful run.
    """


class AgentPatch(BaseModel):
    """Whitelisted mutable fields for API/CLI patch operations."""
    name: str | None = None
    description: str | None = None
    prompt: str | None = None
    schedule: str | None = None
    notify_telegram: bool | None = None
    notify_whatsapp: bool | None = None
    enabled: bool | None = None
    model_tier: ModelTier | None = None
    enable_memory: bool | None = None
    extra: dict[str, Any] | None = None


class AgentRun(BaseModel):
    """One execution record for an agent."""
    run_id: str
    agent_id: str
    started_at: str = Field(default_factory=_now)
    finished_at: str = ""
    success: bool = False
    output: str = ""
    error: str = ""
    tools_used: list[str] = Field(default_factory=list)
    model_tier_used: ModelTier = "balanced"
