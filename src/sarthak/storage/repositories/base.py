"""
Storage Repository Protocols — backend-agnostic interfaces.

All business logic calls these protocols. Concrete backends are resolved
by storage/factory.py. Use structural typing (Protocol) — no inheritance.

Protocols defined here:
  ActivityRepository  — user_activity rows
  ChatRepository      — chat_history rows
  EmbeddingRepository — per-space vector index
  RoadmapRepository   — per-space roadmap document
"""
from __future__ import annotations

from typing import Any, Protocol, runtime_checkable


@runtime_checkable
class ActivityRepository(Protocol):
    """Read/write user_activity rows."""

    async def write(
        self,
        *,
        activity_type: str,
        space_dir: str,
        concept_id: str,
        concept_title: str,
        session_id: str,
        content_text: str,
        media_path: str,
        metadata: dict,
    ) -> int: ...

    async def query(
        self,
        *,
        space_dir: str,
        activity_type: str | None,
        concept_title: str,
        days: int,
        limit: int,
    ) -> list[dict]: ...

    async def summary(self, space_dir: str, days: int) -> dict: ...

    async def failed_code_concepts(
        self, space_dir: str, threshold: int, days: int
    ) -> list[str]: ...

    async def concepts_touched(self, space_dir: str, days: int) -> list[str]: ...

    async def recent_media_notes(self, space_dir: str, days: int) -> list[dict]: ...


@runtime_checkable
class ChatRepository(Protocol):
    """Read/write chat_history rows."""

    async def write_message(
        self, session_id: str, role: str, content: str
    ) -> None: ...

    async def get_history(self, session_id: str, limit: int) -> list[dict]: ...

    async def get_sessions(self, limit: int) -> list[dict]: ...

    async def latest_session_id(self) -> str | None: ...


@runtime_checkable
class EmbeddingRepository(Protocol):
    """Vector store operations for a single space's RAG index."""

    async def upsert(
        self, chunks: list[dict], embeddings: list[list[float]]
    ) -> None: ...

    async def search(
        self, query_vec: list[float], top_k: int
    ) -> list[dict]: ...

    async def delete_source(self, source: str) -> None: ...

    async def fts_search(
        self, query: str, top_k: int
    ) -> list[tuple[str, float]]:
        """BM25/FTS search. Returns [(chunk_id, score)]. May return [] if unsupported."""
        ...

    def status(self) -> dict:
        """Sync health/stats. No I/O — safe to call from sync code."""
        ...


@runtime_checkable
class RoadmapRepository(Protocol):
    """Per-space roadmap document operations."""

    async def load(self) -> dict: ...
    async def save(self, data: dict) -> None: ...
    async def exists(self) -> bool: ...
    async def get_phases(self) -> list[dict]: ...
    async def get_milestones(self) -> list[dict]: ...
    async def add_milestone(self, concept: str, details: dict[str, Any] | None) -> None: ...
    async def get_sessions(self, limit: int) -> list[dict]: ...
    async def add_session(self, session: dict[str, Any]) -> None: ...
    async def get_total_xp(self) -> int: ...
    async def add_xp(self, amount: int) -> int: ...
