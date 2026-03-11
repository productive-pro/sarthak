"""
repositories/activity.py — ActivityRepository thin wrapper.

Delegates to the backend resolved by factory.get_activity_repo().
Business logic imports this module — never a backend directly.

Usage:
    from sarthak.storage.repositories.activity import ActivityRepo
    repo = ActivityRepo()
    await repo.write(activity_type="code_run", ...)
"""
from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    pass


class ActivityRepo:
    """
    Facade over the configured ActivityRepository backend.

    Calls factory.get_activity_repo() on first use (lazy, process-singleton).
    All method signatures mirror the ActivityRepository Protocol exactly.
    """

    def __init__(self) -> None:
        self._backend = None

    def _repo(self):
        if self._backend is None:
            from sarthak.storage.factory import get_activity_repo
            self._backend = get_activity_repo()
        return self._backend

    async def write(
        self,
        *,
        activity_type: str,
        space_dir: str = "",
        concept_id: str = "",
        concept_title: str = "",
        session_id: str = "",
        content_text: str = "",
        media_path: str = "",
        metadata: dict | None = None,
    ) -> int:
        return await self._repo().write(
            activity_type=activity_type,
            space_dir=space_dir,
            concept_id=concept_id,
            concept_title=concept_title,
            session_id=session_id,
            content_text=content_text,
            media_path=media_path,
            metadata=metadata or {},
        )

    async def query(
        self,
        *,
        space_dir: str = "",
        activity_type: str | None = None,
        concept_title: str = "",
        days: int = 30,
        limit: int = 200,
    ) -> list[dict]:
        return await self._repo().query(
            space_dir=space_dir,
            activity_type=activity_type,
            concept_title=concept_title,
            days=days,
            limit=limit,
        )

    async def summary(self, space_dir: str, days: int = 7) -> dict:
        return await self._repo().summary(space_dir, days)

    async def failed_code_concepts(
        self, space_dir: str, threshold: int = 3, days: int = 30
    ) -> list[str]:
        return await self._repo().failed_code_concepts(space_dir, threshold, days)

    async def concepts_touched(self, space_dir: str, days: int = 14) -> list[str]:
        return await self._repo().concepts_touched(space_dir, days)

    async def recent_media_notes(self, space_dir: str, days: int = 14) -> list[dict]:
        return await self._repo().recent_media_notes(space_dir, days)


# Process-level default instance — import and use directly
default = ActivityRepo()
