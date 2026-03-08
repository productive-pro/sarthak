"""
Sarthak AI — Prompt Logger.
Saves all outgoing LLM prompts to ~/.sarthak_ai/prompt_history/ as markdown files.
"""
from __future__ import annotations

import os
from datetime import datetime
from typing import Any

from sarthak.core.logging import get_logger

log = get_logger(__name__)

HISTORY_DIR = os.path.expanduser("~/.sarthak_ai/prompt_history")


def log_prompt(context: str, prompt_data: Any) -> None:
    """
    Saves the text prompt to a timestamped Markdown file.
    `context` is a short string like 'daily_summary' or 'snapshot_analysis'.
    """
    try:
        os.makedirs(HISTORY_DIR, exist_ok=True)
        # Avoid race condition naming if multiple calls happen in identical ms
        filename = f"{datetime.now().strftime('%Y%m%d_%H%M%S_%f')}_{context}.md"
        filepath = os.path.join(HISTORY_DIR, filename)

        with open(filepath, "w") as f:
            f.write(f"# Context: {context}\n")
            f.write(f"**Time**: {datetime.now().isoformat()}\n\n")
            f.write("---\n\n")
            
            if isinstance(prompt_data, str):
                f.write(prompt_data)
            else:
                # Handle lists of dicts (LiteLLM) or objects (PydanticAI)
                if isinstance(prompt_data, list):
                    for item in prompt_data:
                        if isinstance(item, dict):
                            _write_litellm_msg(f, item)
                        else:
                            f.write(str(item) + "\n")
                else:
                    f.write(str(prompt_data) + "\n")

        prompt_str = prompt_data if isinstance(prompt_data, str) else str(prompt_data)
        log.info("agent_prompt", agent=context, prompt=prompt_str, prompt_len=len(prompt_str))
    except Exception as exc:
        log.warning("failed_to_log_prompt", error=str(exc))


def _write_litellm_msg(f, msg: dict) -> None:
    role = msg.get("role", "unknown")
    content = msg.get("content", "")
    
    f.write(f"### Role: {role.upper()}\n\n")
    
    if isinstance(content, str):
        f.write(content + "\n\n")
    elif isinstance(content, list):
        for part in content:
            if isinstance(part, dict):
                if part.get("type") == "text":
                    f.write(part.get("text", "") + "\n\n")
                elif part.get("type") == "image_url":
                    f.write("[IMAGE SENT: Base64 data removed for readability]\n\n")
    else:
        f.write(str(content) + "\n\n")
