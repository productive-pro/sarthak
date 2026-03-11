"""
repositories/embeddings.py — EmbeddingRepository thin wrapper.

Delegates to the vector backend resolved by factory.get_embedding_repo().
Business logic imports this module — never a backend directly.

Usage:
    from sarthak.storage.repositories.embeddings import EmbeddingRepo
    repo = EmbeddingRepo(space_dir)
    await repo.upsert(chunks, embeddings)
    results = await repo.search(query_vec, top_k=5)
"""
from __future__ import annotations

from pathlib import Path
from typing import Any


class EmbeddingRepo:
    """
    Async facade over the configured EmbeddingRepository backend.

    Backend is resolved lazily on first awaited call.
    One instance per space_dir — use EmbeddingRepo.for_space(dir).
    """

    def __init__(self, space_dir: str | Path) -> None:
        self._space_dir = Path(space_dir)
        self._backend: Any = None

    @classmethod
    async def for_space(cls, space_dir: str | Path) -> "EmbeddingRepo":
        """Async constructor — resolves backend before returning."""
        repo = cls(space_dir)
        await repo._get_backend()
        return repo

    async def _get_backend(self) -> Any:
        if self._backend is None:
            from sarthak.storage.factory import get_embedding_repo
            self._backend = await get_embedding_repo(self._space_dir)
        return self._backend

    async def upsert(
        self, chunks: list[dict], embeddings: list[list[float]]
    ) -> None:
        backend = await self._get_backend()
        await backend.upsert(chunks, embeddings)

    async def search(
        self, query_vec: list[float], top_k: int = 5
    ) -> list[dict]:
        backend = await self._get_backend()
        return await backend.search(query_vec, top_k)

    async def delete_source(self, source: str) -> None:
        backend = await self._get_backend()
        await backend.delete_source(source)

    async def fts_search(
        self, query: str, top_k: int = 5
    ) -> list[tuple[str, float]]:
        backend = await self._get_backend()
        return await backend.fts_search(query, top_k)

    def status(self) -> dict:
        if self._backend is None:
            return {"enabled": False, "reason": "not_initialized"}
        return self._backend.status()
