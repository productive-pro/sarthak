"""
Sarthak AI — providers.json catalog loader.

Reads providers.json once and caches the result for the process lifetime.
Call invalidate_catalog_cache() if providers.json is modified at runtime.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path
from typing import Any
import importlib.resources
import json

_CAPABILITIES = {"text", "vision", "tools", "code", "reasoning", "audio", "embedding"}


@dataclass(frozen=True)
class ModelEntry:
    id: str
    name: str
    provider: str
    context_window: int
    capabilities: list[str]
    tier: str
    speed: str
    notes: str = ""
    raw: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class ProviderMeta:
    label: str
    kind: str
    base_url: str | None
    env_key: str | None
    api_key_default: str | None = None
    models_dynamic: bool = False


def catalog_path() -> Path:
    """Return path to providers.json for callers that need a filesystem Path.

    Prefer _read_catalog_bytes() internally.  This is kept for external callers.
    """
    # Dev-tree: repo root is 4 levels up from this file
    dev_path = Path(__file__).resolve().parents[4] / "providers.json"
    if dev_path.exists():
        return dev_path
    # Installed package: providers.json lives in sarthak/data/
    try:
        with importlib.resources.as_file(
            importlib.resources.files("sarthak.data").joinpath("providers.json")
        ) as p:
            return p  # valid for non-zip installs; fine for our use
    except (ModuleNotFoundError, FileNotFoundError, TypeError):
        pass
    raise FileNotFoundError(
        "providers.json not found. "
        "If running from source, ensure providers.json is in the repo root. "
        "If installed via pip, reinstall with: pip install --upgrade sarthak"
    )


def _read_catalog_text() -> str:
    """Read providers.json as text, works both from source and pip-installed."""
    # 1. Bundled package data (pip install) — use importlib.resources directly
    try:
        ref = importlib.resources.files("sarthak.data").joinpath("providers.json")
        return ref.read_text(encoding="utf-8")
    except (ModuleNotFoundError, FileNotFoundError, TypeError):
        pass
    # 2. Dev-tree fallback
    dev_path = Path(__file__).resolve().parents[4] / "providers.json"
    if dev_path.exists():
        return dev_path.read_text(encoding="utf-8")
    raise FileNotFoundError(
        "providers.json not found. "
        "If running from source, ensure providers.json is in the repo root. "
        "If installed via pip, reinstall with: pip install --upgrade sarthak"
    )


@lru_cache(maxsize=1)
def load_catalog() -> dict[str, dict[str, Any]]:
    """Parse providers.json and return the full catalog. Result is cached for the process lifetime."""
    raw = json.loads(_read_catalog_text())
    providers = raw.get("providers", {})
    catalog: dict[str, dict[str, Any]] = {}

    for pid, pdata in providers.items():
        models: list[ModelEntry] = []
        for entry in pdata.get("models", []):
            caps = entry.get("capabilities", [])
            unknown = [c for c in caps if c not in _CAPABILITIES]
            if unknown:
                raise ValueError(
                    f"Unsupported capability {unknown!r} in {pid}:{entry.get('id')}"
                )
            extra = {
                k: v for k, v in entry.items()
                if k not in ("id", "name", "context_window", "capabilities", "tier", "speed", "notes")
            }
            models.append(ModelEntry(
                id=entry.get("id", ""),
                name=entry.get("name", entry.get("id", "")),
                provider=pid,
                context_window=int(entry.get("context_window", 0)),
                capabilities=list(caps),
                tier=entry.get("tier", "unknown"),
                speed=entry.get("speed", "unknown"),
                notes=entry.get("notes", ""),
                raw=extra,
            ))
        catalog[pid] = {
            "meta": {k: v for k, v in pdata.items() if k != "models"},
            "models": models,
        }
    return catalog


def invalidate_catalog_cache() -> None:
    """Force reload of providers.json on next access (e.g. after editing it)."""
    load_catalog.cache_clear()


def provider_meta(provider: str) -> ProviderMeta:
    catalog = load_catalog()
    if provider not in catalog:
        raise ValueError(f"Unknown provider '{provider}'")
    meta = catalog[provider]["meta"]
    return ProviderMeta(
        label=str(meta.get("label", provider)),
        kind=str(meta.get("kind", "")),
        base_url=meta.get("base_url") or None,
        env_key=meta.get("env_key") or None,
        api_key_default=meta.get("api_key_default") or None,
        models_dynamic=bool(meta.get("models_dynamic", False)),
    )


def list_models(provider: str) -> list[ModelEntry]:
    catalog = load_catalog()
    if provider not in catalog:
        raise ValueError(f"Unknown provider '{provider}'")
    return list(catalog[provider]["models"])


def list_embedding_models() -> list[str]:
    """Return all embedding model IDs as 'provider:model_id' strings."""
    result: list[str] = []
    for pid, pdata in load_catalog().items():
        for m in pdata["models"]:
            if "embedding" in m.capabilities:
                result.append(f"{pid}:{m.id}")
    return result
