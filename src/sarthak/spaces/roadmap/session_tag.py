"""
Sarthak Spaces — Terminal session tagging (Feature 4).

Links running terminal commands to the active roadmap concept.
No new DB tables — appends `roadmap_tag` JSON metadata to the existing
`.spaces.json["sessions"]` entries and writes a lightweight tag log
at `.spaces/session_tags.jsonl` for analytics.

How it works:
  1. `tag_session(space_dir, command, cwd)` is called after each terminal command.
  2. It looks at roadmap concepts and matches command keywords against tags.
  3. Best-matching concept → chapter/topic/concept IDs stored in tag log.
  4. `get_session_tags(space_dir)` returns recent tags for dashboard.

The tag log format (one JSON per line):
  { "ts": "ISO", "command": "...", "cwd": "...", "chapter_id": "", "topic_id": "", "concept_id": "", "concept_title": "" }
"""
from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from sarthak.core.logging import get_logger

log = get_logger(__name__)

_TAG_LOG = "session_tags.jsonl"
_MAX_LOG_LINES = 500


def _tag_path(space_dir: Path) -> Path:
    d = space_dir / ".spaces"
    d.mkdir(exist_ok=True)
    return d / _TAG_LOG


async def tag_session(
    space_dir: Path,
    command: str,
    cwd: str = "",
    concept_id: str | None = None,  # explicit override from frontend
) -> dict[str, Any] | None:
    """
    Match command against active roadmap concepts and write a tag entry.
    Returns the tag dict if a match was found, else None.
    """
    from .db import RoadmapDB

    db = RoadmapDB(space_dir)
    await db.init()
    roadmap = await db.load_roadmap()
    if roadmap is None:
        return None

    # Explicit concept_id wins
    if concept_id:
        cn = roadmap.get_concept(concept_id)
        if cn:
            for ch in roadmap.chapters:
                for tp in ch.topics:
                    if any(c.id == concept_id for c in tp.concepts):
                        return await _write_tag(space_dir, command, cwd, ch.id, tp.id, cn.id, cn.title)

    # Auto-match: tokenize command, score against concept tags
    cmd_tokens = set(re.findall(r"[a-z0-9_]+", command.lower()))
    best_score, best_meta = 0, None

    for ch in roadmap.chapters:
        for tp in ch.topics:
            for cn in tp.concepts:
                score = len(cmd_tokens & set(t.lower() for t in cn.tags))
                if score > best_score:
                    best_score = score
                    best_meta  = (ch.id, tp.id, cn.id, cn.title)

    if best_score < 1 or best_meta is None:
        return None

    return await _write_tag(space_dir, command, cwd, *best_meta)


async def _write_tag(
    space_dir: Path,
    command: str,
    cwd: str,
    chapter_id: str,
    topic_id: str,
    concept_id: str,
    concept_title: str,
) -> dict[str, Any]:
    tag: dict[str, Any] = {
        "ts":           datetime.now(timezone.utc).isoformat(),
        "command":      command[:300],
        "cwd":          cwd[:200],
        "chapter_id":   chapter_id,
        "topic_id":     topic_id,
        "concept_id":   concept_id,
        "concept_title": concept_title,
    }
    path = _tag_path(space_dir)
    lines = path.read_text().splitlines() if path.exists() else []
    lines.append(json.dumps(tag))
    # Trim to last N entries
    path.write_text("\n".join(lines[-_MAX_LOG_LINES:]) + "\n")
    log.info("session_tagged", concept=concept_title, command=command[:60])
    return tag


def get_session_tags(space_dir: Path, last_n: int = 50) -> list[dict[str, Any]]:
    """Return the last N tag entries (most recent last)."""
    path = _tag_path(space_dir)
    if not path.exists():
        return []
    lines = [ln for ln in path.read_text().splitlines() if ln.strip()][-last_n:]
    result = []
    for line in reversed(lines):
        try:
            result.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    return result
