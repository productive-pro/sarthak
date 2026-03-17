"""
DEAD CODE — superseded by spaces/roadmap/db.py + spaces/roadmap/models.py.

This module is kept as a tombstone. All roadmap persistence now goes through
RoadmapDB (async SQLite). Do not add new code here.

Migration map:
  roadmap_tracker.load_roadmap()          → RoadmapDB.load_roadmap()
  roadmap_tracker.save_roadmap()          → RoadmapDB.save_roadmap()
  roadmap_tracker.init_roadmap()          → spaces/roadmap_init.ensure_roadmap()
  roadmap_tracker.record_session_to_roadmap() → spaces/orchestrator._post_session()
"""
from __future__ import annotations
from pathlib import Path


def record_session_to_roadmap(
    workspace_dir,
    profile,
    *,
    concept: str = "",
    xp_earned: int = 0,
    tools_used=None,
    external_tools=None,
    mastered: bool = False,
) -> None:
    """No-op stub. Recording now happens inside SpacesOrchestrator._post_session()."""
    pass
