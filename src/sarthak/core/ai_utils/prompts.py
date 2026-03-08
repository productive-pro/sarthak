"""
Prompt loader — reads prompts.json once, cached for the process lifetime.

Usage
-----
    from sarthak.core.ai_utils.prompts import get_prompt
    system = get_prompt("chat_agent")
    snapshot_tmpl = get_prompt("sarthak_agent", "snapshot_prompt")
"""
from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path
from typing import Any

_PROMPTS_PATH = Path(__file__).parent / "prompts.json"


@lru_cache(maxsize=1)
def _load() -> dict[str, Any]:
    return json.loads(_PROMPTS_PATH.read_text(encoding="utf-8"))


def get_prompt(agent_key: str, field: str = "system") -> str:
    """Return a prompt string from prompts.json."""
    return _load()[agent_key][field]


def reload_prompts() -> None:
    """Force reload prompts from disk (useful after editing prompts.json)."""
    _load.cache_clear()
