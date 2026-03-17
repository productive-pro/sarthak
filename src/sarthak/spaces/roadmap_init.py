"""
Sarthak Spaces — Roadmap bootstrap helper.

Public API:
  ensure_roadmap(space_dir, profile, force?)  → bool
  discover_custom_domain(background, goal)    → dict
  refine_roadmap(space_dir, profile, answers) → bool

Per-space locks use weakref so entries are GC'd automatically when no
coroutine holds a reference — no manual eviction, no unbounded growth.
"""
from __future__ import annotations

import asyncio
import weakref
from pathlib import Path

from sarthak.core.logging import get_logger

log = get_logger(__name__)

# WeakValueDictionary: entries disappear automatically once no coroutine
# holds the lock, so the dict stays bounded without any manual eviction.
_ROADMAP_LOCKS: weakref.WeakValueDictionary[str, asyncio.Lock] = (
    weakref.WeakValueDictionary()
)
_LOCKS_GUARD = asyncio.Lock()


async def _get_roadmap_lock(space_dir: Path) -> asyncio.Lock:
    """Return (or create) the per-space roadmap generation lock."""
    key = str(space_dir.resolve())
    async with _LOCKS_GUARD:
        lock = _ROADMAP_LOCKS.get(key)
        if lock is None:
            lock = asyncio.Lock()
            _ROADMAP_LOCKS[key] = lock
    return lock


async def ensure_roadmap(
    space_dir: Path,
    profile,  # SpaceProfile
    *,
    force: bool = False,
) -> bool:
    """
    Generate and persist a roadmap if one doesn't exist yet.
    Idempotent unless force=True. Thread-safe via per-space asyncio.Lock.
    Returns True if a new roadmap was generated.
    """
    from sarthak.agents.roadmap_agents import generate_roadmap, generate_space_overview
    from sarthak.spaces.roadmap.db import RoadmapDB
    import json as _json

    lock = await _get_roadmap_lock(space_dir)
    async with lock:
        db = RoadmapDB(space_dir)
        await db.init()

        if not force and (await db.load_roadmap()) is not None:
            log.debug("roadmap_already_exists", space=str(space_dir))
            return False

        domain     = profile.domain or profile.space_type.value.replace("_", " ").title()
        background = profile.learner.background or "general learner"
        goal       = profile.learner.goal or f"master {domain}"
        space_name = space_dir.name

        log.info("roadmap_generating", space=space_name, domain=domain)
        _write_roadmap_status(space_dir, "generating")
        try:
            roadmap, overview = await asyncio.gather(
                generate_roadmap(
                    space_name=space_name, domain=domain,
                    background=background, goal=goal,
                ),
                generate_space_overview(
                    domain=domain, background=background, goal=goal,
                ),
            )
            await db.save_roadmap(roadmap)
            _write_roadmap_json(space_dir, roadmap)
            if overview:
                (space_dir / ".spaces" / "overview.json").write_text(
                    _json.dumps(overview, indent=2), encoding="utf-8"
                )
            _write_roadmap_status(space_dir, "ready")
            log.info("roadmap_saved", space=space_name, chapters=len(roadmap.chapters))
            return True
        except Exception as exc:
            log.error("roadmap_generation_failed", space=space_name, error=str(exc))
            _write_roadmap_status(space_dir, "failed", error=str(exc))
            return False


def _write_roadmap_status(space_dir: Path, status: str, error: str = "") -> None:
    import json as _json
    path = space_dir / ".spaces" / "roadmap_status.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(_json.dumps({"status": status, "error": error}), encoding="utf-8")


def _write_roadmap_json(space_dir: Path, roadmap) -> None:
    """Human-readable snapshot alongside SQLite (not source of truth)."""
    out = space_dir / ".spaces" / "roadmap.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(roadmap.model_dump_json(indent=2), encoding="utf-8")


async def discover_custom_domain(
    background: str,
    goal: str,
    extra_context: str = "",
) -> dict:
    """LLM-based domain discovery for CUSTOM spaces. Returns structured dict."""
    from sarthak.features.ai.agents._base import parse_json_response, run_llm

    system = (
        "You are an expert learning architect. Design a personalised learning space.\n\n"
        "Output ONLY valid JSON:\n"
        "{\n"
        '  "domain_name": "Specific domain name",\n'
        '  "description": "1-2 sentences",\n'
        '  "suggested_goal": "Refined goal",\n'
        '  "clarifying_questions": ["q1", "q2"],\n'
        '  "concept_outline": ["theme1","theme2","theme3","theme4","theme5"],\n'
        '  "workspace_folders": ["folder1","folder2","folder3","folder4"],\n'
        '  "recommended_tools": [{"name":"tool","purpose":"why","install":"how"}]\n'
        "}\n\n"
        "Rules: domain_name must reflect actual subject. concept_outline: 5 domain-specific "
        "themes. workspace_folders: 4-6 domain-appropriate folders. recommended_tools: 0-5 "
        "genuinely relevant tools only. clarifying_questions: exactly 2."
    )
    user = (
        f"Background: {background or 'not specified'}\n"
        f"Goal: {goal or 'not specified'}\n"
        + (f"Context: {extra_context}\n" if extra_context else "")
    )
    fallback = {
        "domain_name": goal or "Custom Learning Space",
        "description": f"A personalised space focused on: {goal}",
        "suggested_goal": goal,
        "clarifying_questions": [
            "What is your current familiarity with this subject?",
            "What specific outcome would make this a success?",
        ],
        "concept_outline": ["Foundations", "Core Concepts", "Application", "Advanced", "Mastery"],
        "workspace_folders": ["notes", "resources", "reflections", "projects"],
        "recommended_tools": [],
    }
    raw = await run_llm(system, user)
    try:
        return parse_json_response(raw)
    except Exception:
        log.warning("discover_custom_domain_parse_failed", raw=raw[:200])
        return fallback


async def refine_roadmap(
    space_dir: Path,
    profile,  # SpaceProfile
    clarification_answers: str,
) -> bool:
    """Regenerate roadmap incorporating user answers to clarifying questions."""
    if clarification_answers.strip():
        from sarthak.spaces.store import save_clarification_answers
        save_clarification_answers(space_dir, clarification_answers.strip())
        refined_goal = f"{profile.learner.goal}\n\nRefinement: {clarification_answers.strip()}"
        profile = profile.model_copy(update={"learner": profile.learner.model_copy(
            update={"goal": refined_goal}
        )})
    return await ensure_roadmap(space_dir, profile, force=True)

