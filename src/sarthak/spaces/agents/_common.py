"""
_common.py — shared infrastructure for all spaces sub-agents.

Design principle: agent identity lives in the .md file, not in Python.
  Every agent class calls _load_system(agent_id) to get its system prompt
  from data/agents/spaces/<id>.md.  The Python class only handles:
    - prompt construction (assembling the user message from runtime data)
    - structured output parsing / fallback
    - business logic (SM-2 math, badge milestone checks, tool scanning)

Tier assignments (declared in each agent's .md frontmatter AND mirrored here):
  onboarding        → balanced   (first-time profiling)
  curriculum        → fast       (called every session, simple JSON)
  assessment        → balanced   (careful judgment)
  quicktest         → fast       (simple task generation)
  math              → powerful   (LaTeX derivations, deep explanation)
  task-builder      → balanced   (structured task)
  project           → powerful   (full scaffold, long output)
  engagement        → balanced   (voice/tone rendering)
  workspace-designer → fast      (directory JSON, simple)
  environment       → fast       (scan + install commands)
  workspace-analyser → balanced  (session-start briefing)
  ExternalToolsAgent → no LLM   (pure logic)
  SpacedRepetition  → no LLM    (pure SM-2 math)
  BadgeAgent        → no LLM    (pure milestone logic)
"""
from __future__ import annotations

import sys
from functools import lru_cache

from sarthak.core.logging import get_logger
from sarthak.features.ai.agents._base import parse_json_response, run_llm

log = get_logger(__name__)


# ── Platform + background helpers ─────────────────────────────────────────────

def detect_platform() -> str:
    """Return 'windows', 'darwin', or 'linux'."""
    s = sys.platform
    if s.startswith("win"):  return "windows"
    if s == "darwin":        return "darwin"
    return "linux"


def is_technical(background: str) -> bool:
    """Return True when the learner background suggests a technical role."""
    keywords = {"engineer", "developer", "programmer", "coder", "cs", "tech",
                "software", "data", "analyst", "researcher", "scientist"}
    return any(k in background.lower() for k in keywords)


# ── System prompt loader ──────────────────────────────────────────────────────

@lru_cache(maxsize=32)
def _load_system(agent_id: str) -> str:
    """
    Load system prompt from data/agents/spaces/<agent_id>.md.
    Falls back to an empty string (log warning) if not found.
    Result is process-lifetime cached — .md files are read-only at runtime.
    """
    try:
        from sarthak.data.loader import load_spaces_agent_prompt
        return load_spaces_agent_prompt(agent_id)
    except FileNotFoundError:
        log.warning("spaces_agent_md_missing", agent_id=agent_id,
                    hint=f"Create data/agents/spaces/{agent_id}.md")
        return ""
    except Exception as exc:
        log.warning("spaces_agent_md_load_failed", agent_id=agent_id, error=str(exc))
        return ""


# ── Core LLM call ─────────────────────────────────────────────────────────────

async def _call_llm_json(
    system: str,
    prompt: str,
    fallback: dict,
    *,
    tag: str,
    model_tier: str = "balanced",
) -> dict:
    """
    One-shot LLM call → parsed JSON dict.
    Returns fallback on any LLM or parse error — never raises.

    model_tier: "fast" | "balanced" | "powerful"
    """
    try:
        raw = await run_llm(system, prompt, tier=model_tier)
        return parse_json_response(raw)
    except Exception as exc:
        log.warning(f"{tag}_failed", error=str(exc))
        return fallback
