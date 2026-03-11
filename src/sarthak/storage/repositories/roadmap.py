"""
repositories/roadmap.py — RoadmapRepository.

The roadmap is stored as a JSON file per space:
  <space_dir>/.spaces/roadmap.json

This repository provides a typed async interface over that file.
It delegates the heavy lifting to spaces.roadmap_tracker where the
full roadmap logic already lives.

No SQL involved — roadmap data is document-style, JSON is the right fit.
If a team/cloud deployment needs SQL, swap the file backend here.

Usage:
    from sarthak.storage.repositories.roadmap import RoadmapRepo
    repo = RoadmapRepo(space_dir)
    data = await repo.load()
    await repo.add_milestone(concept, details)
"""
from __future__ import annotations

import asyncio
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


class RoadmapRepo:
    """
    Async interface to a space's roadmap.json.

    All I/O is offloaded to asyncio.to_thread for event-loop safety.
    Writes are atomic: write to .tmp → rename.
    """

    def __init__(self, space_dir: str | Path) -> None:
        self._space_dir = Path(space_dir)
        self._path = self._space_dir / ".spaces" / "roadmap.json"

    def _read_sync(self) -> dict:
        if not self._path.exists():
            return {}
        return json.loads(self._path.read_text(encoding="utf-8"))

    def _write_sync(self, data: dict) -> None:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self._path.with_suffix(".json.tmp")
        tmp.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
        tmp.replace(self._path)

    async def load(self) -> dict:
        """Return the full roadmap dict. Returns {} if not yet initialised."""
        return await asyncio.to_thread(self._read_sync)

    async def save(self, data: dict) -> None:
        """Atomically overwrite roadmap.json."""
        await asyncio.to_thread(self._write_sync, data)

    async def exists(self) -> bool:
        return await asyncio.to_thread(self._path.exists)

    async def get_phases(self) -> list[dict]:
        data = await self.load()
        return data.get("phases", [])

    async def get_milestones(self) -> list[dict]:
        data = await self.load()
        return data.get("milestones", [])

    async def add_milestone(
        self,
        concept: str,
        details: dict[str, Any] | None = None,
    ) -> None:
        def _do() -> None:
            data = self._read_sync()
            milestones = data.setdefault("milestones", [])
            milestones.append({
                "concept": concept,
                "completed_at": datetime.now(timezone.utc).isoformat(),
                **(details or {}),
            })
            data["last_updated"] = datetime.now(timezone.utc).isoformat()
            self._write_sync(data)
        await asyncio.to_thread(_do)

    async def get_sessions(self, limit: int = 50) -> list[dict]:
        data = await self.load()
        return data.get("sessions", [])[-limit:]

    async def add_session(self, session: dict[str, Any]) -> None:
        def _do() -> None:
            data = self._read_sync()
            data.setdefault("sessions", []).append(session)
            data["last_updated"] = datetime.now(timezone.utc).isoformat()
            self._write_sync(data)
        await asyncio.to_thread(_do)

    async def get_total_xp(self) -> int:
        data = await self.load()
        return int(data.get("total_xp", 0))

    async def add_xp(self, amount: int) -> int:
        def _do() -> int:
            data = self._read_sync()
            new_xp = int(data.get("total_xp", 0)) + amount
            data["total_xp"] = new_xp
            data["last_updated"] = datetime.now(timezone.utc).isoformat()
            self._write_sync(data)
            return new_xp
        return await asyncio.to_thread(_do)

    async def get_phase_by_id(self, phase_id: str) -> dict | None:
        phases = await self.get_phases()
        return next((p for p in phases if p.get("id") == phase_id), None)

    async def update_phase(self, phase_id: str, updates: dict[str, Any]) -> None:
        def _do() -> None:
            data = self._read_sync()
            for phase in data.get("phases", []):
                if phase.get("id") == phase_id:
                    phase.update(updates)
                    break
            data["last_updated"] = datetime.now(timezone.utc).isoformat()
            self._write_sync(data)
        await asyncio.to_thread(_do)
