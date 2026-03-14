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
from typing import Any

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
    FILE_WRITE  = "file_write"   # write inside declared write_roots only
    HTTP_FETCH  = "http_fetch"   # single URL fetch — narrower than full web search


class SandboxPolicy(BaseModel):
    """
    Optional per-agent overrides for sandbox resource limits and capability flags.

    When absent, defaults from SandboxConfig (config.py) apply.
    Capability overrides (allow_web, allow_shell) let you create e.g. a
    web-search agent that runs sandboxed with web disabled for testing.
    """
    wall_timeout:  int | None  = None   # seconds; overrides default per-scope timeout
    memory_cap:    int | None  = None   # bytes
    cpu_seconds:   int | None  = None   # subprocess CPU cap (POSIX only)
    output_cap:    int | None  = None   # characters saved to AgentRun.output
    max_web_calls: int | None  = None   # per-run web search call limit
    # capability overrides — None means "derive from AgentSpec.tools" (default)
    allow_web:   bool | None = None
    allow_shell: bool | None = None


class AgentSpec(BaseModel):
    """Persistent definition of a custom agent."""
    agent_id: str                                  # slug, e.g. "daily-digest"
    name: str                                      # human display name
    description: str = ""                          # what this agent does
    prompt: str                                    # the task/instruction template
    schedule: str                                  # cron expression, e.g. "0 8 * * *"
    tools: list[AgentTool] = Field(default_factory=list)
    scope: AgentScope = AgentScope.GLOBAL
    space_dir: str = ""                            # set when scope == SPACE
    context_space_dirs: list[str] = Field(default_factory=list)  # extra spaces for context injection
    notify_telegram: bool = False                  # push result to Telegram if configured
    notify_whatsapp: bool = False                  # push result to WhatsApp if configured
    enabled: bool = True
    created_at: str = Field(default_factory=_now)
    updated_at: str = Field(default_factory=_now)
    last_run_at: str = ""
    next_run_at: str = ""                          # ISO-8601, computed from schedule
    extra: dict[str, Any] = Field(default_factory=dict)  # free-form metadata from creator
    sandbox: SandboxPolicy = Field(default_factory=SandboxPolicy)  # resource overrides


class AgentPatch(BaseModel):
    """Whitelisted mutable fields for API/CLI patch operations."""
    name: str | None = None
    description: str | None = None
    prompt: str | None = None
    schedule: str | None = None
    notify_telegram: bool | None = None
    notify_whatsapp: bool | None = None
    enabled: bool | None = None
    extra: dict[str, Any] | None = None


class AgentRun(BaseModel):
    """One execution record for an agent."""
    run_id: str
    agent_id: str
    started_at: str = Field(default_factory=_now)
    finished_at: str = ""
    success: bool = False
    output: str = ""                               # markdown / plain text result
    error: str = ""
    tools_used: list[str] = Field(default_factory=list)
