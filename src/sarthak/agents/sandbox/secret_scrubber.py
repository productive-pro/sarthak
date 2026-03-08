"""
Sarthak Agent Sandbox — SecretScrubber.

Strips sensitive material from agent prompts and run outputs before
they are persisted or forwarded.

Patterns scrubbed:
  - ENC:<base64>          encrypted credential tokens from secrets.toml
  - master.key path refs  absolute paths containing .sarthak_ai/master.key
  - Raw API key patterns  sk-..., Bearer <token>, api_key=...
  - SARTHAK_* env values  any env var starting with SARTHAK_
"""
from __future__ import annotations

import os
import re

from sarthak.agents.sandbox.audit import emit

# ── Compiled patterns ─────────────────────────────────────────────────────────

_PATTERNS: list[tuple[str, re.Pattern, str]] = [
    (
        "enc_token",
        re.compile(r"ENC:[A-Za-z0-9+/=]{8,}", re.ASCII),
        "[REDACTED:enc_token]",
    ),
    (
        "master_key_path",
        re.compile(r"[\w/\\.:-]*master\.key[\w/\\.:-]*", re.IGNORECASE),
        "[REDACTED:master_key_path]",
    ),
    (
        "openai_key",
        re.compile(r"sk-[A-Za-z0-9]{20,}", re.ASCII),
        "[REDACTED:api_key]",
    ),
    (
        "bearer_token",
        re.compile(r"Bearer\s+[A-Za-z0-9\-._~+/]+=*", re.IGNORECASE | re.ASCII),
        "[REDACTED:bearer_token]",
    ),
    (
        "api_key_param",
        re.compile(r"api[_\-]?key\s*[=:]\s*\S+", re.IGNORECASE),
        "[REDACTED:api_key_param]",
    ),
]


def _build_env_pattern() -> re.Pattern | None:
    """Build a pattern from current SARTHAK_* env vars that have non-empty values."""
    values = [
        re.escape(v)
        for k, v in os.environ.items()
        if k.startswith("SARTHAK_") and len(v) > 8
    ]
    if not values:
        return None
    return re.compile("|".join(values))


# ── Public API ────────────────────────────────────────────────────────────────

def scrub(text: str, agent_id: str = "") -> tuple[str, int]:
    """
    Remove secrets from *text*.

    Returns (scrubbed_text, count_of_replacements).
    Emits an audit event if anything was stripped.
    """
    result = text
    total = 0

    for label, pattern, replacement in _PATTERNS:
        result, n = pattern.subn(replacement, result)
        total += n

    env_pat = _build_env_pattern()
    if env_pat:
        result, n = env_pat.subn("[REDACTED:env_secret]", result)
        total += n

    if total > 0:
        emit(
            "agent_secret_stripped",
            agent_id=agent_id,
            count=total,
        )

    return result, total


def scrub_env(env: dict[str, str]) -> dict[str, str]:
    """
    Return a copy of *env* with SARTHAK_* secrets removed.

    Keeps PATH, LANG, HOME, USER, LOGNAME, TERM, TMPDIR, TMP, TEMP.
    Strips everything else by default so subprocess environments are minimal.
    """
    _ALLOWLIST = {"PATH", "LANG", "HOME", "USER", "LOGNAME", "TERM",
                  "TMPDIR", "TMP", "TEMP", "USERPROFILE", "SYSTEMROOT",
                  "WINDIR", "COMSPEC"}
    return {k: v for k, v in env.items() if k in _ALLOWLIST}
