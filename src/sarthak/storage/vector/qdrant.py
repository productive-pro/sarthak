"""
QdrantRepo — Qdrant EmbeddingRepository implementation.

Requires: pip install qdrant-client
Config:
    [storage.qdrant]
    url = "http://localhost:6333"
    api_key = ""           # empty for local instances
    collection_prefix = "sarthak"

Collection naming: sarthak_{space_slug} where space_slug is
the space directory name sanitised to alphanumeric + underscore.

Each collection uses cosine distance. Payload stores source, line, chunk, text.
"""
from __future__ import annotations

import hashlib
import re
from pathlib import Path
from typing import Any

import structlog

log = structlog.get_logger(__name__)


def _slug(space_dir: Path, prefix: str = "sarthak") -> str:
    """Stable collection name from space directory path."""
    name = re.sub(r"[^a-z0-9_]", "_", Path(space_dir).name.lower())
    # Append short hash so renames don't collide
    h = hashlib.md5(str(space_dir).encode()).hexdigest()[:6]
    return f"{prefix}_{name}_{h}"


class QdrantRepo:
    """
    EmbeddingRepository backed by Qdrant.

    One Qdrant collection per Sarthak space.
    Creates the collection lazily on first upsert.
    """

    def __init__(
        self,
        space_dir: Path | str,
        *,
        url: str = "http://localhost:6333",
        api_key: str = "",
        collection_prefix: str = "sarthak",
    ) -> None:
        self._space_dir = Path(space_dir)
        self._url = url
        self._api_key = api_key
        self._collection = _slug(self._space_dir, collection_prefix)
        self._client: Any = None
        self._dim: int | None = None

    def _get_client(self) -> Any:
        if self._client is None:
            from qdrant_client import QdrantClient  # type: ignore
            self._client = QdrantClient(
                url=self._url,
                api_key=self._api_key or None,
                timeout=30,
            )
        return self._client

    async def _ensure_collection(self, dim: int) -> None:
        if self._dim == dim:
            return
        import asyncio
        await asyncio.to_thread(self._ensure_collection_sync, dim)
        self._dim = dim

    def _ensure_collection_sync(self, dim: int) -> None:
        from qdrant_client import QdrantClient
        from qdrant_client.models import Distance, VectorParams  # type: ignore
        client = self._get_client()
        existing = [c.name for c in client.get_collections().collections]
        if self._collection not in existing:
            client.create_collection(
                collection_name=self._collection,
                vectors_config=VectorParams(size=dim, distance=Distance.COSINE),
            )
            log.info("qdrant_collection_created",
                     collection=self._collection, dim=dim)

    async def upsert(
        self,
        chunks: list[dict],
        embeddings: list[list[float]],
    ) -> None:
        import asyncio
        from qdrant_client.models import PointStruct  # type: ignore

        if not chunks:
            return
        dim = len(embeddings[0])
        await self._ensure_collection(dim)

        points = [
            PointStruct(
                id=_chunk_point_id(c["id"]),  # collision-safe UUID5 → uint64
                vector=e,
                payload={
                    "chunk_id": c["id"],
                    "source":   c.get("source", ""),
                    "line":     c.get("line", 1),
                    "chunk":    c.get("chunk", 0),
                    "text":     c.get("text", ""),
                },
            )
            for c, e in zip(chunks, embeddings)
        ]

        client = self._get_client()
        await asyncio.to_thread(
            client.upsert,
            collection_name=self._collection,
            points=points,
        )
        log.debug("qdrant_upserted",
                  collection=self._collection, count=len(points))

    async def delete_source(self, source: str) -> None:
        import asyncio
        from qdrant_client.models import FieldCondition, Filter, MatchValue  # type: ignore

        client = self._get_client()
        await asyncio.to_thread(
            client.delete,
            collection_name=self._collection,
            points_selector=Filter(
                must=[FieldCondition(key="source", match=MatchValue(value=source))]
            ),
        )

    async def search(
        self,
        query_vec: list[float],
        top_k: int = 5,
    ) -> list[dict]:
        import asyncio

        client = self._get_client()
        try:
            hits = await asyncio.to_thread(
                client.query_points,
                collection_name=self._collection,
                query=query_vec,
                limit=top_k,
                with_payload=True,
            )
        except Exception as exc:
            log.warning("qdrant_search_failed", error=str(exc))
            return []

        results = []
        for h in hits.points:
            p = h.payload or {}
            results.append({
                "id":       p.get("chunk_id", str(h.id)),
                "source":   p.get("source", ""),
                "line":     p.get("line", 1),
                "chunk":    p.get("chunk", 0),
                "text":     p.get("text", ""),
                "distance": 1.0 - h.score,  # cosine: convert similarity to distance
            })
        return results

    async def fts_search(self, query: str, top_k: int = 5) -> list[tuple[str, float]]:
        """Qdrant has no BM25 — return empty to fall back to vector-only."""
        return []

    def status(self) -> dict:
        try:
            client = self._get_client()
            info = client.get_collection(self._collection)
            count = info.points_count or 0
            return {
                "enabled": True,
                "backend": "qdrant",
                "collection": self._collection,
                "indexed_chunks": count,
                "url": self._url,
            }
        except Exception:
            return {
                "enabled": False,
                "backend": "qdrant",
                "collection": self._collection,
                "indexed_chunks": 0,
                "url": self._url,
            }


def _chunk_point_id(chunk_id: str) -> int:
    """
    Deterministic positive int64 Qdrant point ID from chunk_id.

    Uses UUID5 (SHA-1 namespace hash) for collision resistance, then masks
    to a positive int64 (Qdrant requires IDs < 2^63).
    """
    import uuid
    return uuid.uuid5(uuid.NAMESPACE_OID, chunk_id).int % (2 ** 63)
