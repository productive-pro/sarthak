"""
Agent / Tool / Skill registry loader.

    load_agent(agent_id)              -> AgentMeta   (data/agents/**/<id>.md)
    load_spaces_agent_prompt(agent_id) -> str         (data/agents/spaces/<id>.md body)
    get_agent_tier(agent_id)          -> str          (model_tier from frontmatter)
    load_builtin_agent_specs()        -> list[dict]   (data/agents/builtin.toml)
    resolve_tool_fn(tool_id)          -> callable     (imported from tool YAML stub)
    build_prompt(meta, ...)           -> str          (body + context + skills)

Architecture:
  Every agent is ONE markdown file with YAML frontmatter.
  The frontmatter declares: id, name, description, model_tier, tools, delegates.
  The body IS the system prompt — no code needed to maintain prompt text.
  Context files (data/agents/<id>/*.md) are auto-appended — same as Claude Code.

  Built-in scheduled agents are declared in data/agents/builtin.toml.
  scheduler.py reads them via load_builtin_agent_specs() — no hardcoded dicts.

Agent locations:
  data/agents/orchestrator.md      — primary user-facing agent
  data/agents/vision.md            — screenshot analysis
  data/agents/summary.md           — daily digest
  data/agents/system/*.md          — built-in scheduled agents
  data/agents/spaces/*.md          — spaces sub-agents

Tool stubs: data/tools/<group>.tool.yaml
Skills:     data/skills/<n>.md  (shipped built-ins)
"""
from __future__ import annotations

import importlib
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path
from typing import Any

from sarthak.core.logging import get_logger

log = get_logger(__name__)

_DATA_DIR   = Path(__file__).parent
_AGENTS_DIR = _DATA_DIR / "agents"
_TOOLS_DIR  = _DATA_DIR / "tools"


# ── Data classes ──────────────────────────────────────────────────────────────

@dataclass
class AgentMeta:
    id: str
    name: str
    description: str
    system_prompt: str
    model_tier: str = "balanced"
    output: str = "text"
    tools: list[str] = field(default_factory=list)
    skills: list[str] = field(default_factory=list)
    delegates: list[str] = field(default_factory=list)
    sandbox: dict[str, Any] = field(default_factory=dict)
    channels: list[str] = field(default_factory=list)
    schedule: str = ""


@dataclass
class ToolStub:
    id: str
    module: str
    function: str
    description: str = ""


# ── Minimal YAML frontmatter parser (zero extra deps) ────────────────────────

def _parse_simple_yaml(text: str) -> dict[str, Any]:
    result: dict[str, Any] = {}
    current_parent: str | None = None
    for raw_line in text.splitlines():
        line = raw_line.rstrip()
        if not line or line.startswith("#"):
            continue
        indent   = len(raw_line) - len(raw_line.lstrip())
        stripped = line.strip()
        if indent > 0 and current_parent:
            if stripped.startswith("- "):
                item = stripped[2:].strip()
                if not isinstance(result.get(current_parent), list):
                    result[current_parent] = []
                result[current_parent].append(_coerce(item))
            else:
                k, _, v = stripped.partition(":")
                if not isinstance(result.get(current_parent), dict):
                    result[current_parent] = {}
                result[current_parent][k.strip()] = _coerce(v.strip())
            continue
        current_parent = None
        k, _, v = line.partition(":")
        k, v = k.strip(), v.strip()
        if not v:
            current_parent = k
            result[k] = {}
        elif v.startswith("["):
            items = v.strip("[]").split(",")
            result[k] = [i.strip().strip("\"'") for i in items if i.strip()]
        else:
            result[k] = _coerce(v)
    return result


def _coerce(v: str) -> Any:
    if v.lower() in ("true", "yes"):  return True
    if v.lower() in ("false", "no"):  return False
    try: return int(v)
    except ValueError: pass
    return v.strip("\"'")


def _split_frontmatter(text: str) -> tuple[dict[str, Any], str]:
    if not text.startswith("---"):
        return {}, text
    try:
        end = text.index("\n---", 3)
    except ValueError:
        return {}, text
    return _parse_simple_yaml(text[3:end].strip()), text[end + 4:].strip()


def _load_context_dir(agent_id: str, agent_path: Path) -> str:
    ctx_dir = agent_path.parent / agent_id
    if not ctx_dir.is_dir():
        return ""
    parts = []
    for f in sorted(ctx_dir.glob("*.md")):
        content = f.read_text(encoding="utf-8").strip()
        if content:
            parts.append(f"<!-- context: {f.name} -->\n{content}")
    return "\n\n".join(parts)

# ── Agent loaders ─────────────────────────────────────────────────────────────

@lru_cache(maxsize=64)
def load_agent(agent_id: str) -> AgentMeta:
    """
    Load any agent by id. Searches data/agents/**/<id>.md recursively.
    Includes context directory if present. Process-lifetime cached.
    """
    candidates = list(_AGENTS_DIR.rglob(f"{agent_id}.md"))
    if not candidates:
        raise FileNotFoundError(
            f"Agent '{agent_id}' not found under {_AGENTS_DIR}. "
            f"Create data/agents/.../{agent_id}.md to register it."
        )
    path = candidates[0]
    raw  = path.read_text(encoding="utf-8")
    fm, body = _split_frontmatter(raw)
    ctx    = _load_context_dir(agent_id, path)
    prompt = f"{body}\n\n{ctx}".strip() if ctx else body
    sandbox = fm.get("sandbox", {})
    if not isinstance(sandbox, dict):
        sandbox = {}
    return AgentMeta(
        id=fm.get("id", agent_id),
        name=fm.get("name", agent_id),
        description=fm.get("description", ""),
        system_prompt=prompt,
        model_tier=fm.get("model_tier", "balanced"),
        output=fm.get("output", "text"),
        tools=fm.get("tools", []),
        skills=fm.get("skills", []),
        delegates=fm.get("delegates", []),
        sandbox=sandbox,
        channels=fm.get("channels", []),
        schedule=fm.get("schedule", ""),
    )


@lru_cache(maxsize=32)
def load_spaces_agent_prompt(skill_id: str) -> str:
    """
    Load system prompt body for a Spaces skill from data/agents/spaces/<skill_id>.md.
    Cached for process lifetime — .md files are read-only at runtime.
    """
    path = _AGENTS_DIR / "spaces" / f"{skill_id}.md"
    if not path.exists():
        raise FileNotFoundError(
            f"Spaces skill prompt not found: {path}. "
            f"Create data/agents/spaces/{skill_id}.md to register it."
        )
    raw = path.read_text(encoding="utf-8")
    _, body = _split_frontmatter(raw)
    return body


def get_agent_tier(agent_id: str) -> str:
    """Return the model_tier declared in an agent's frontmatter. Fallback: 'balanced'."""
    try:
        return load_agent(agent_id).model_tier
    except Exception:
        return "balanced"


# ── Built-in agent specs from TOML ────────────────────────────────────────────

@lru_cache(maxsize=1)
def load_builtin_agent_specs() -> list[dict[str, Any]]:
    """
    Load built-in scheduled agent declarations from data/agents/builtin.toml.
    Returns a list of dicts, each with AgentSpec-compatible fields plus 'handler'.
    Cached for process lifetime.
    """
    toml_path = _AGENTS_DIR / "builtin.toml"
    if not toml_path.exists():
        log.warning("builtin_toml_missing", path=str(toml_path))
        return []
    try:
        import tomllib  # Python 3.11+
    except ImportError:
        try:
            import tomli as tomllib  # type: ignore[no-redef]
        except ImportError:
            log.warning("toml_library_missing", hint="Install tomli for Python <3.11")
            return _parse_builtin_toml_fallback(toml_path.read_text(encoding="utf-8"))
    try:
        with open(toml_path, "rb") as f:
            data = tomllib.load(f)
        return data.get("agent", [])
    except Exception as exc:
        log.warning("builtin_toml_parse_failed", error=str(exc))
        return []


def _parse_builtin_toml_fallback(text: str) -> list[dict[str, Any]]:
    """Minimal TOML [[agent]] parser — only used when tomllib is unavailable."""
    agents: list[dict[str, Any]] = []
    current: dict[str, Any] = {}
    for raw in text.splitlines():
        line = raw.strip()
        if line == "[[agent]]":
            if current:
                agents.append(current)
            current = {}
        elif line and not line.startswith("#") and "=" in line:
            k, _, v = line.partition("=")
            current[k.strip()] = _coerce(v.strip().strip('"'))
    if current:
        agents.append(current)
    return agents


# ── Tool stub loader ──────────────────────────────────────────────────────────

@lru_cache(maxsize=128)
def _load_all_tool_stubs() -> dict[str, ToolStub]:
    stubs: dict[str, ToolStub] = {}
    for path in sorted(_TOOLS_DIR.glob("*.tool.yaml")):
        raw = path.read_text(encoding="utf-8")
        for block in raw.split("\n---"):
            block = block.strip()
            if not block:
                continue
            d = _parse_simple_yaml(block)
            tool_id = d.get("id", "")
            if not tool_id or "module" not in d or "function" not in d:
                continue
            stubs[tool_id] = ToolStub(
                id=tool_id, module=d["module"], function=d["function"],
                description=d.get("description", ""),
            )
    return stubs


def load_tool_stub(tool_id: str) -> ToolStub:
    stubs = _load_all_tool_stubs()
    if tool_id not in stubs:
        raise FileNotFoundError(f"Tool '{tool_id}' not found in {_TOOLS_DIR}.")
    return stubs[tool_id]


def resolve_tool_fn(tool_id: str):
    """Import and return the callable for a registered tool."""
    stub = load_tool_stub(tool_id)
    mod  = importlib.import_module(stub.module)
    fn   = getattr(mod, stub.function)
    log.debug("tool_resolved", id=tool_id, module=stub.module, fn=stub.function)
    return fn


def list_tool_ids() -> list[str]:
    return sorted(_load_all_tool_stubs().keys())


# ── Prompt builder ────────────────────────────────────────────────────────────

def build_prompt(meta: AgentMeta, skills_block: str = "") -> str:
    """Compose full system prompt: agent body + context + skills summary."""
    parts = [meta.system_prompt]
    if skills_block:
        parts.append(skills_block)
    return "\n\n".join(p for p in parts if p)


# ── Cache management ──────────────────────────────────────────────────────────

def invalidate_caches() -> None:
    """Clear loader caches — useful in dev/hot-reload."""
    load_agent.cache_clear()
    load_spaces_agent_prompt.cache_clear()
    load_builtin_agent_specs.cache_clear()
    _load_all_tool_stubs.cache_clear()
