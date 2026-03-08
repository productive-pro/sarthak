"""
Sarthak AI — Provider registry for the configure UI.

Handles live model discovery from provider APIs.
Sync fetch functions use httpx.Client (blocking); the async wrapper runs them
in a thread so the event loop is never blocked.
"""
from __future__ import annotations

import asyncio
from dataclasses import dataclass

import httpx

from sarthak.core.ai_utils.catalog import list_models as catalog_models
from sarthak.core.ai_utils.catalog import provider_meta


@dataclass(frozen=True)
class ProviderEntry:
    label: str
    kind: str
    base_url: str | None
    env_key: str | None
    api_key_default: str | None = None
    models_dynamic: bool = False


# Canonical alias map — single source of truth for provider name normalisation
_ALIASES: dict[str, str] = {
    "grok":        "xai",
    "huggingface": "hf",
}


def canonical_provider(provider: str) -> str:
    return _ALIASES.get(provider, provider)


def provider_entry(provider: str) -> ProviderEntry:
    meta = provider_meta(canonical_provider(provider))
    return ProviderEntry(
        label=meta.label,
        kind=meta.kind,
        base_url=meta.base_url,
        env_key=meta.env_key,
        api_key_default=meta.api_key_default,
        models_dynamic=meta.models_dynamic,
    )


def static_models(provider: str) -> list[str]:
    return [m.id for m in catalog_models(canonical_provider(provider))]


def _unique_sorted(models: list[str]) -> list[str]:
    return sorted({m for m in models if m})


# ── Sync HTTP fetchers (all blocking — called via asyncio.to_thread) ──────────

def _fetch_openai_like(url: str, api_key: str) -> list[str]:
    if not api_key:
        return []
    with httpx.Client(timeout=15, headers={"Authorization": f"Bearer {api_key}"}) as c:
        resp = c.get(url)
        if resp.status_code != 200:
            return []
        data = resp.json()
    items = data if isinstance(data, list) else data.get("data", [])
    return [m.get("id", "") for m in items if isinstance(m, dict) and m.get("id")]


def _fetch_openrouter_models(api_key: str) -> list[str]:
    return _fetch_openai_like("https://openrouter.ai/api/v1/models/user", api_key)


def _fetch_openai_models(api_key: str) -> list[str]:
    return _fetch_openai_like("https://api.openai.com/v1/models", api_key)


def _fetch_openai_compat_models(base_url: str, api_key: str) -> list[str]:
    if not base_url:
        return []
    return _fetch_openai_like(base_url.rstrip("/") + "/models", api_key)


def _fetch_ollama_models(base_url: str) -> list[str]:
    if not base_url:
        return []
    url = base_url.replace("/v1", "").rstrip("/") + "/api/tags"
    with httpx.Client(timeout=5) as c:
        resp = c.get(url)
        if resp.status_code != 200:
            return []
        data = resp.json()
    return [m.get("name", "") for m in data.get("models", []) if m.get("name")]


def _fetch_aimlapi_models(api_key: str) -> list[str]:
    headers = {"Authorization": f"Bearer {api_key}"} if api_key else {}
    with httpx.Client(timeout=30, headers=headers) as c:
        resp = c.get("https://api.aimlapi.com/models")
        if resp.status_code != 200:
            return []
        data = resp.json()
    items = data.get("data", []) if isinstance(data, dict) else []
    return [
        m.get("id", "")
        for m in items
        if isinstance(m, dict) and m.get("id")
        and m.get("type") in ("chat-completion", "responses")
    ]


def list_models_sync(
    provider: str, api_key: str | None = None, base_url: str | None = None
) -> list[str]:
    """Synchronously fetch live model list from the provider API.

    Falls back to static catalog entries on error or missing key.
    NOTE: This makes blocking HTTP calls — do not call from an async context.
    Use list_models() (async) instead.
    """
    canon = canonical_provider(provider)
    entry = provider_entry(canon)
    resolved_base = base_url or entry.base_url or ""

    fetchers: dict[str, Any] = {
        "ollama":     lambda: _fetch_ollama_models(resolved_base),
        "aimlapi":    lambda: _fetch_aimlapi_models(api_key or ""),
        "openrouter": lambda: _fetch_openrouter_models(api_key or ""),
    }
    kind_fetchers = {
        "openai":       lambda: _fetch_openai_models(api_key or ""),
        "openai-compat": lambda: _fetch_openai_compat_models(resolved_base, api_key or ""),
    }

    fetch = fetchers.get(canon) or kind_fetchers.get(entry.kind)
    if fetch:
        try:
            models = fetch()
            if models:
                return _unique_sorted(models)
        except Exception:
            pass

    return static_models(canon)


async def list_models(
    provider: str, api_key: str | None = None, base_url: str | None = None
) -> list[str]:
    """Async model list — runs the blocking sync fetcher in a thread pool.

    Safe to await from any async context without blocking the event loop.
    """
    return await asyncio.to_thread(list_models_sync, provider, api_key, base_url)


# keep backward-compat type hint
from typing import Any  # noqa: E402 (late import for type alias)
