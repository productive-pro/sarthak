"""
Sarthak Agent Sandbox — SandboxConfig.

Declares per-agent resource limits, allowed filesystem roots,
and capability flags derived from AgentSpec.
"""
from __future__ import annotations

import sys
from dataclasses import dataclass, field
from pathlib import Path

from sarthak.agents.models import AgentScope, AgentSpec, AgentTool


# ── Defaults ──────────────────────────────────────────────────────────────────

_GLOBAL_DIR = Path.home() / ".sarthak_ai"

# Wall-clock timeouts (seconds)
_TIMEOUT_SYSTEM = 120
_TIMEOUT_SPACE  = 300

# Memory cap bytes (256 MB)
_MEMORY_CAP = 256 * 1024 * 1024

# Max CPU seconds for subprocess shell commands
_CPU_SECONDS = 30

# Max output characters saved to AgentRun.output
OUTPUT_CAP = 64 * 1024  # 64 KB

# Max web search calls allowed per run
WEB_SEARCH_RATE = 10


@dataclass
class SandboxConfig:
    """
    Immutable per-run sandbox policy.

    Constructed once at the start of run_agent() from the AgentSpec.
    Consumed by PathGuard, SecretScrubber, ProcessSandbox, and audit.
    """
    agent_id: str
    scope: AgentScope

    # Capability flags — derived from AgentSpec.tools
    allow_shell: bool
    allow_web: bool
    allow_file_read: bool
    allow_file_write: bool
    allow_http_fetch: bool

    # Filesystem roots
    # write_roots: directories the agent MAY write inside
    # read_roots:  directories the agent MAY read inside
    write_roots: list[Path] = field(default_factory=list)
    read_roots:  list[Path] = field(default_factory=list)

    # Resource limits
    wall_timeout: int  = _TIMEOUT_SYSTEM  # seconds
    memory_cap:   int  = _MEMORY_CAP      # bytes
    cpu_seconds:  int  = _CPU_SECONDS     # seconds (subprocess only)
    output_cap:   int  = OUTPUT_CAP       # characters

    # Rate limits
    max_web_calls: int = WEB_SEARCH_RATE

    # Windows: resource module unavailable; skip rlimit enforcement
    rlimits_available: bool = field(default_factory=lambda: sys.platform != "win32")


def _load_sandbox_cfg_overrides(is_space: bool) -> dict:
    """
    Read [agents.sandbox.system] or [agents.sandbox.space] from config.toml.

    Keys accepted (all optional):
      enabled        bool  — if False, skip sandbox enforcement entirely (unsafe, dev only)
      wall_timeout   int   — seconds
      memory_cap     int   — bytes
      cpu_seconds    int   — seconds
      output_cap     int   — characters
      max_web_calls  int   — calls per run

    See docs/guides/configuration.md for details.
    """
    try:
        from sarthak.core.config import load_config
        cfg = load_config()
        section_key = "space" if is_space else "system"
        return dict(cfg.get("agents", {}).get("sandbox", {}).get(section_key, {}))
    except Exception:
        return {}


def build_sandbox_config(spec: "AgentSpec") -> SandboxConfig:
    """Derive a SandboxConfig from an AgentSpec."""
    is_space = spec.scope == AgentScope.SPACE

    # tool-derived capabilities, with per-agent SandboxPolicy capability overrides
    policy = spec.sandbox
    allow_shell      = policy.allow_shell if policy.allow_shell is not None else (AgentTool.SHELL      in spec.tools)
    allow_web        = policy.allow_web   if policy.allow_web   is not None else (AgentTool.WEB_SEARCH in spec.tools)
    allow_file_read  = AgentTool.FILE_READ  in spec.tools
    allow_file_write = AgentTool.FILE_WRITE in spec.tools
    allow_http_fetch = AgentTool.HTTP_FETCH in spec.tools

    # Load config.toml overrides for this agent class (system or space)
    cfg_overrides = _load_sandbox_cfg_overrides(is_space)

    timeout = _TIMEOUT_SPACE if is_space else _TIMEOUT_SYSTEM

    # Filesystem roots
    runs_dir = _agent_runs_dir(spec)
    write_roots: list[Path] = [runs_dir]
    read_roots:  list[Path] = []

    if is_space and spec.space_dir:
        space_path = Path(spec.space_dir).resolve()
        write_roots.append(space_path / ".spaces")
        if allow_file_read:
            read_roots.append(space_path)
    else:
        # System agents: read-only access to global sarthak dir, write only to runs
        if allow_file_read:
            read_roots.append(_GLOBAL_DIR)

    # Resolution order: per-agent SandboxPolicy > config.toml [agents.sandbox.*] > hardcoded defaults
    return SandboxConfig(
        agent_id=spec.agent_id,
        scope=spec.scope,
        allow_shell=allow_shell,
        allow_web=allow_web,
        allow_file_read=allow_file_read,
        allow_file_write=allow_file_write,
        allow_http_fetch=allow_http_fetch,
        write_roots=write_roots,
        read_roots=read_roots,
        wall_timeout  =policy.wall_timeout   if policy.wall_timeout   is not None else int(cfg_overrides.get("wall_timeout",   timeout)),
        memory_cap    =policy.memory_cap     if policy.memory_cap     is not None else int(cfg_overrides.get("memory_cap",    _MEMORY_CAP)),
        cpu_seconds   =policy.cpu_seconds    if policy.cpu_seconds    is not None else int(cfg_overrides.get("cpu_seconds",   _CPU_SECONDS)),
        output_cap    =policy.output_cap     if policy.output_cap     is not None else int(cfg_overrides.get("output_cap",    OUTPUT_CAP)),
        max_web_calls =policy.max_web_calls  if policy.max_web_calls  is not None else int(cfg_overrides.get("max_web_calls", WEB_SEARCH_RATE)),
    )


def _agent_runs_dir(spec: AgentSpec) -> Path:
    """Mirror the path logic from agents/store.py without importing it."""
    if spec.scope == AgentScope.SPACE and spec.space_dir:
        base = Path(spec.space_dir) / ".spaces" / "agents"
    else:
        base = _GLOBAL_DIR / "agents"
    return base / spec.agent_id / "runs"
