"""
Sarthak Spaces — Roadmap & Progress Tracker.

Stores the learner's roadmap and tracks achievements per concept, per session,
per tool, in a structured JSON file: <workspace>/.spaces/roadmap.json

This is the single source of truth for:
- What the learner plans to achieve (roadmap)
- What they have achieved (milestones)
- When they achieved it
- Which tools they used at each stage
- Which external tools (VS Code, Google Colab, etc.) they used
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from sarthak.spaces.models import SkillLevel, SpaceProfile

# store imported lazily inside functions to avoid circular imports


_ROADMAP_FILE = ".spaces/roadmap.json"


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


# ── Schema helpers ─────────────────────────────────────────────────────────────

def _empty_roadmap(profile: SpaceProfile) -> dict[str, Any]:
    return {
        "version": 1,
        "domain": profile.domain,
        "learner": profile.learner.name or "Learner",
        "goal": profile.learner.goal or "Mastery",
        "started_at": _now(),
        "last_updated": _now(),
        "current_level": profile.learner.skill_level.value,
        "phases": [],          # list of phase dicts
        "milestones": [],      # completed concept milestones
        "sessions": [],        # one entry per learning session
        "tools_used": {},      # tool_name -> {first_used, sessions_count, category}
        "external_tools": [],  # VS Code, Google Colab, etc.
        "projects": [],        # completed projects
        "total_xp": 0,
        "total_sessions": 0,
        "streak_days": 0,
    }


def _build_phases(profile: SpaceProfile) -> list[dict]:
    """Build roadmap phases from the domain concept tree."""
    from sarthak.spaces.domains import get_domain

    level_order = [
        SkillLevel.NOVICE,
        SkillLevel.BEGINNER,
        SkillLevel.INTERMEDIATE,
        SkillLevel.ADVANCED,
        SkillLevel.EXPERT,
    ]
    domain = get_domain(profile.space_type)
    tree = domain.get("concept_tree", {})
    mastered = set(profile.learner.mastered_concepts)
    phases = []
    for level in level_order:
        concepts = tree.get(level, [])
        if not concepts:
            continue
        done = [c for c in concepts if c in mastered]
        phases.append({
            "level": level.value,
            "concepts": concepts,
            "completed": done,
            "completion_pct": round(len(done) / len(concepts) * 100) if concepts else 0,
        })
    return phases


# ── Public API ─────────────────────────────────────────────────────────────────

def load_roadmap(workspace_dir: Path) -> dict[str, Any] | None:
    path = workspace_dir / _ROADMAP_FILE
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None


def save_roadmap(workspace_dir: Path, roadmap: dict[str, Any]) -> None:
    path = workspace_dir / _ROADMAP_FILE
    path.parent.mkdir(parents=True, exist_ok=True)
    roadmap["last_updated"] = _now()
    path.write_text(json.dumps(roadmap, indent=2, ensure_ascii=False), encoding="utf-8")


def init_roadmap(workspace_dir: Path, profile: SpaceProfile) -> dict[str, Any]:
    roadmap = _empty_roadmap(profile)
    roadmap["phases"] = _build_phases(profile)
    save_roadmap(workspace_dir, roadmap)
    return roadmap


def record_session_to_roadmap(
    workspace_dir: Path,
    profile: SpaceProfile,
    concept: str,
    xp_earned: int,
    tools_used: list[str],
    external_tools: list[str],
    mastered: bool,
    duration_minutes: int = 30,
) -> dict[str, Any]:
    """Append one session to the roadmap and update milestones."""
    roadmap = load_roadmap(workspace_dir) or init_roadmap(workspace_dir, profile)

    # Session entry
    session_entry = {
        "session_id": f"s{roadmap['total_sessions'] + 1:04d}",
        "timestamp": _now(),
        "concept": concept,
        "xp_earned": xp_earned,
        "mastered": mastered,
        "tools_used": tools_used,
        "external_tools": external_tools,
        "duration_minutes": duration_minutes,
        "level": profile.learner.skill_level.value,
    }
    roadmap["sessions"].append(session_entry)
    roadmap["sessions"] = roadmap["sessions"][-200:]  # keep last 200

    # Milestones
    if mastered and concept not in [m["concept"] for m in roadmap["milestones"]]:
        roadmap["milestones"].append({
            "concept": concept,
            "achieved_at": _now(),
            "level": profile.learner.skill_level.value,
            "session_id": session_entry["session_id"],
        })

    # Tools tracking
    for tool in tools_used:
        if tool not in roadmap["tools_used"]:
            roadmap["tools_used"][tool] = {"first_used": _now(), "sessions_count": 0, "category": "workspace"}
        roadmap["tools_used"][tool]["sessions_count"] += 1

    # External tools
    for ext in external_tools:
        if ext not in roadmap["external_tools"]:
            roadmap["external_tools"].append(ext)

    # Summary stats
    roadmap["total_xp"] = profile.learner.xp
    roadmap["total_sessions"] = profile.learner.total_sessions
    roadmap["current_level"] = profile.learner.skill_level.value
    roadmap["streak_days"] = profile.learner.streak_days

    # Refresh phases
    roadmap["phases"] = _build_phases(profile)

    save_roadmap(workspace_dir, roadmap)
    return roadmap


