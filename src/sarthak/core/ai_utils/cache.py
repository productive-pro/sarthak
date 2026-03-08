"""
Sarthak AI — Disk-based LLM response cache.
Prevents redundant LLM calls for identical prompt+model combinations.
Pure functions. No global state — cache dir from env/config.
"""
from __future__ import annotations

import hashlib
import json
import os
import time
from pathlib import Path
from typing import Any

import structlog

from sarthak.core.ai_utils.multi_provider import call_llm

log = structlog.get_logger(__name__)

_DEFAULT_CACHE_DIR = os.path.expanduser("~/.cache/sarthak/llm")
_DEFAULT_TTL = 3600  # 1 hour


def _cache_key(prompt: str, model: str, provider: str, system: str | None) -> str:
    """SHA256 fingerprint of the call parameters."""
    payload = json.dumps({
        "prompt": prompt, "model": model,
        "provider": provider, "system": system or "",
    }, sort_keys=True)
    return hashlib.sha256(payload.encode()).hexdigest()


def _cache_path(key: str, cache_dir: str = _DEFAULT_CACHE_DIR) -> Path:
    return Path(cache_dir) / f"{key[:2]}" / f"{key}.json"


def get_cached(key: str, ttl: int = _DEFAULT_TTL,
               cache_dir: str = _DEFAULT_CACHE_DIR) -> str | None:
    """Return cached response if exists and not expired. None otherwise."""
    p = _cache_path(key, cache_dir)
    if not p.exists():
        return None
    data = json.loads(p.read_text())
    if time.time() - data["ts"] > ttl:
        p.unlink(missing_ok=True)
        return None
    return data["response"]


def set_cached(key: str, response: str, cache_dir: str = _DEFAULT_CACHE_DIR) -> None:
    """Write response to disk cache."""
    p = _cache_path(key, cache_dir)
    p.parent.mkdir(parents=True, exist_ok=True)
    try:
        p.write_text(json.dumps({"ts": time.time(), "response": response}))
    except Exception as exc:
        log.warning("cache_write_failed", error=str(exc))


def invalidate_cache(cache_dir: str = _DEFAULT_CACHE_DIR) -> int:
    """Delete all expired cache entries. Returns count deleted."""
    removed = 0
    for p in Path(cache_dir).rglob("*.json"):
        data = json.loads(p.read_text())
        if time.time() - data["ts"] > _DEFAULT_TTL:
            p.unlink()
            removed += 1
    return removed


async def cached_llm_call(
    prompt: str,
    model: str = "gemma3:4b",
    provider: str = "ollama",
    system: str | None = None,
    ttl: int = _DEFAULT_TTL,
    cache_dir: str | None = None,
    **kwargs: Any,
) -> str:
    """
    Call LLM with disk-based caching. Returns cached result if available.
    Cache dir: ~/.cache/sarthak/llm (or SARTHAK_DATA_DIR override).
    """
    cache_dir = cache_dir or os.environ.get(
        "SARTHAK_LLM_CACHE_DIR", _DEFAULT_CACHE_DIR
    )
    key = _cache_key(prompt, model, provider, system)

    cached = get_cached(key, ttl=ttl, cache_dir=cache_dir)
    if cached is not None:
        log.debug("llm_cache_hit", key=key[:8])
        return cached

    response = await call_llm(prompt, model=model, provider=provider, system=system, **kwargs)
    set_cached(key, response, cache_dir=cache_dir)
    log.debug("llm_cache_miss_stored", key=key[:8])
    return response
