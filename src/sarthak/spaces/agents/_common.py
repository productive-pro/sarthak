from __future__ import annotations

import sys

from sarthak.core.logging import get_logger
from sarthak.features.ai.agents._base import parse_json_response, run_llm

log = get_logger(__name__)


def detect_platform() -> str:
    """Return 'windows', 'darwin', or 'linux'."""
    s = sys.platform
    if s.startswith("win"):
        return "windows"
    if s == "darwin":
        return "darwin"
    return "linux"


def is_technical(background: str) -> bool:
    """Return True when the learner background string suggests a technical role."""
    keywords = {"engineer", "developer", "programmer", "coder", "cs", "tech",
                "software", "data", "analyst", "researcher", "scientist"}
    return any(k in background.lower() for k in keywords)


async def _call_llm_json(system: str, prompt: str, fallback: dict, *, tag: str) -> dict:
    """Call LLM and parse JSON response. Returns fallback on any error."""
    try:
        raw = await run_llm(system, prompt)
        return parse_json_response(raw)
    except Exception as exc:
        log.warning(f"{tag}_failed", error=str(exc))
        return fallback
