"""
Sarthak Spaces — Domain Loader.

Loads domain knowledge (concept trees, tools, projects) from
data/domains/ YAML files instead of hardcoded Python.

Layout:
    data/domains/
        domains_metadata.yaml       — registry: maps SpaceType → file + metadata
        <space_type>.yaml           — per-domain: concept_tree, tools, projects
                                      (may use `extends: <other>` to inherit)

Public API (drop-in replacement for the old domains.py):
    get_domain(space_type)                              → dict
    get_next_concepts(space_type, mastered, level)      → list[str]
    get_available_projects(space_type, level, done_ids) → list[dict]

Adding a new domain — NO Python changes needed:
    1. Add entry in data/domains/domains_metadata.yaml
    2. Create data/domains/<file>.yaml with concept_tree / tools / projects
"""
from __future__ import annotations

import threading
from functools import lru_cache
from pathlib import Path
from typing import Any

import yaml

from sarthak.core.logging import get_logger
from sarthak.spaces.models import SkillLevel, SpaceType, ToolRecommendation

log = get_logger(__name__)

# ── Paths ──────────────────────────────────────────────────────────────────────

_PKG_ROOT = Path(__file__).resolve().parent  # src/sarthak/spaces/  (dev)
                                              # sarthak/spaces/       (installed)

def _resolve_data_dir() -> Path:
    """
    Locate data/domains/ in both dev and installed-wheel layouts.

    Dev layout (repo):
        src/sarthak/spaces/domain_loader.py  →  ../../.. → repo root  →  data/domains/

    Installed wheel layout (force-include maps data/domains → sarthak/data/domains):
        sarthak/spaces/domain_loader.py  →  ../  → sarthak/  →  data/domains/
    """
    # Dev: go up 3 levels from spaces/ → spaces→sarthak→src→repo_root
    dev_path = _PKG_ROOT.parent.parent.parent / "data" / "domains"
    if dev_path.is_dir():
        return dev_path
    # Installed wheel: go up 1 level from spaces/ → package root → data/domains
    installed_path = _PKG_ROOT.parent / "data" / "domains"
    if installed_path.is_dir():
        return installed_path
    # Last resort: env var override
    import os
    env_path = os.environ.get("SARTHAK_DOMAINS_DIR")
    if env_path:
        return Path(env_path)
    # Return dev path anyway; error will surface on first YAML load
    return dev_path


_DATA_DIR = _resolve_data_dir()
_METADATA_FILE = _DATA_DIR / "domains_metadata.yaml"

_load_lock = threading.Lock()
_domain_cache: dict[str, dict[str, Any]] = {}
_metadata_cache: dict[str, Any] | None = None


# ── YAML loading ──────────────────────────────────────────────────────────────

def _load_yaml(path: Path) -> dict:
    try:
        with path.open("r", encoding="utf-8") as f:
            return yaml.safe_load(f) or {}
    except FileNotFoundError:
        log.error("domain_file_not_found", path=str(path))
        return {}
    except yaml.YAMLError as exc:
        log.error("domain_yaml_parse_error", path=str(path), error=str(exc))
        return {}


def _get_metadata() -> dict[str, Any]:
    global _metadata_cache
    if _metadata_cache is not None:
        return _metadata_cache
    raw = _load_yaml(_METADATA_FILE)
    _metadata_cache = raw.get("domains", {})
    return _metadata_cache


# ── Domain file loading with `extends` support ────────────────────────────────

def _load_domain_file(filename: str, _stack: frozenset[str] | None = None) -> dict:
    """
    Load a single domain YAML file.
    Supports `extends: <other_filename_without_.yaml>` for inheritance.
    Circular-extend protection via `_stack`.
    """
    stack = _stack or frozenset()
    path = _DATA_DIR / filename

    raw = _load_yaml(path)
    if not raw:
        return {}

    parent_key = raw.get("extends")
    if parent_key:
        parent_file = f"{parent_key}.yaml"
        if parent_file in stack:
            log.warning("domain_circular_extends", file=filename, parent=parent_file)
        else:
            parent = _load_domain_file(parent_file, stack | {filename})
            # Child inherits everything from parent; child keys override parent
            merged: dict = {**parent}
            for key, val in raw.items():
                if key != "extends":
                    merged[key] = val
            return merged

    return raw


# ── Tool hydration ────────────────────────────────────────────────────────────

def _hydrate_tools(raw_tools: list[dict]) -> list[ToolRecommendation]:
    tools: list[ToolRecommendation] = []
    for t in raw_tools:
        try:
            tools.append(ToolRecommendation(
                name=t.get("name", ""),
                purpose=t.get("purpose", ""),
                install_linux=t.get("install_linux", ""),
                install_mac=t.get("install_mac", t.get("install_linux", "")),
                install_windows=t.get("install_windows", t.get("install_linux", "")),
                url=t.get("url", ""),
                why_experts_use_it=t.get("why_experts_use_it", ""),
                category=t.get("category", "general"),
            ))
        except Exception as exc:
            log.warning("domain_tool_hydrate_failed", tool=t, error=str(exc))
    return tools


# ── Concept tree key normalisation ────────────────────────────────────────────

def _normalise_concept_tree(raw_tree: dict) -> dict[SkillLevel, list[str]]:
    """
    YAML keys are strings (e.g. "novice").
    Convert to SkillLevel enum keys to match the old domains.py shape.
    """
    normalised: dict[SkillLevel, list[str]] = {}
    for key, concepts in raw_tree.items():
        try:
            level = SkillLevel(key)
            normalised[level] = list(concepts or [])
        except ValueError:
            log.warning("domain_unknown_skill_level", key=key)
    return normalised


# ── Project level hydration ───────────────────────────────────────────────────

def _normalise_projects(raw_projects: list[dict]) -> list[dict]:
    result = []
    for p in raw_projects:
        try:
            level_str = p.get("level", "novice")
            p["level"] = SkillLevel(level_str)
            result.append(p)
        except (ValueError, AttributeError):
            log.warning("domain_project_bad_level", project=p.get("id"), level=p.get("level"))
    return result


# ── Main loader ───────────────────────────────────────────────────────────────

def _build_domain_dict(space_type_value: str) -> dict[str, Any]:
    """
    Load and assemble the full domain dict for a given SpaceType value string.
    Returns a dict with keys: concept_tree, tools, projects, domain_name, expert_description.
    """
    metadata = _get_metadata()
    meta = metadata.get(space_type_value)

    if not meta:
        log.warning("domain_metadata_missing", space_type=space_type_value)
        meta = {
            "domain_name": space_type_value.replace("_", " ").title(),
            "expert_description": "",
            "file": f"{space_type_value}.yaml",
        }

    filename = meta.get("file", f"{space_type_value}.yaml")
    raw = _load_domain_file(filename)

    concept_tree = _normalise_concept_tree(raw.get("concept_tree", {}))
    tools = _hydrate_tools(raw.get("tools", []))
    projects = _normalise_projects(raw.get("projects", []))

    return {
        "concept_tree": concept_tree,
        "tools": tools,
        "projects": projects,
        "domain_name": meta.get("domain_name", space_type_value),
        "expert_description": meta.get("expert_description", ""),
    }


def _get_cached_domain(space_type_value: str) -> dict[str, Any]:
    if space_type_value in _domain_cache:
        return _domain_cache[space_type_value]
    with _load_lock:
        # Double-checked locking
        if space_type_value in _domain_cache:
            return _domain_cache[space_type_value]
        domain = _build_domain_dict(space_type_value)
        _domain_cache[space_type_value] = domain
        return domain


# ── Public API — identical to old domains.py ─────────────────────────────────

def get_domain(space_type: SpaceType) -> dict:
    """
    Return domain config for the given SpaceType.
    Falls back to CUSTOM gracefully; never accidentally returns DATA_SCIENCE.
    """
    try:
        return _get_cached_domain(space_type.value)
    except Exception as exc:
        log.error("get_domain_failed", space_type=space_type, error=str(exc))
        return _get_cached_domain(SpaceType.CUSTOM.value)


def get_next_concepts(
    space_type: SpaceType,
    mastered: list[str],
    level: SkillLevel,
    limit: int = 5,
) -> list[str]:
    """Return pending concepts for the learner's current level."""
    tree = get_domain(space_type)["concept_tree"]
    mastered_set = set(mastered)
    pending = [c for c in tree.get(level, []) if c not in mastered_set]
    return pending[:limit] or tree.get(SkillLevel.NOVICE, [])[:3]


def get_available_projects(
    space_type: SpaceType,
    level: SkillLevel,
    completed_project_ids: list[str],
) -> list[dict]:
    """Return projects appropriate for the learner's level, excluding completed ones."""
    projects = get_domain(space_type).get("projects", [])
    level_order = list(SkillLevel)
    level_idx = level_order.index(level) if level in level_order else 0
    completed = set(completed_project_ids)
    suitable = [
        p for p in projects
        if p["id"] not in completed
        and p["level"] in level_order
        and level_order.index(p["level"]) <= level_idx + 1
    ]
    return suitable[:3]


def invalidate_cache() -> None:
    """Clear the in-process domain cache. Call after editing YAML files at runtime."""
    global _domain_cache, _metadata_cache
    with _load_lock:
        _domain_cache.clear()
        _metadata_cache = None
    log.info("domain_cache_invalidated")
