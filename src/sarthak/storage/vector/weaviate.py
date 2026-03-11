"""
WeaviateRepo — Weaviate EmbeddingRepository.

Requires: pip install weaviate-client>=4.0
Config:
    [storage.weaviate]
    url     = "http://localhost:8080"
    api_key = ""          # leave empty for local instance
    grpc_port = 50051     # required for v4 client

Weaviate features used:
  - Named vectors (per-space class isolation)
  - BM25 + vector hybrid search
  - Multi-tenancy optional

Each space gets its own Weaviate class: Sarthak_<slug>_<hash8>
Class names must be PascalCase and start with a letter.
"""
from __future__ import annotations

import asyncio
import hashlib
from pathlib import Path
from typing import Any

import structlog

log = structlog.get_logger(__name__)


def _class_name(space_dir: Path) -> str:
    slug = space_dir.name.replace("-", "_").replace(" ", "_").capitalize()[:20]
    h = hashlib.sha1(str(space_dir.resolve()).encode()).hexdigest()[:8]
    return f"Sarthak_{slug}_{h}"


class WeaviateRepo:
    """EmbeddingRepository backed by Weaviate v4."""

    def __init__(
        self,
        space_dir: Path | str,
        url: str = "http://localhost:8080",
        api_key: str = "",
        grpc_port: int = 50051,
    ) -> None:
        self._space_dir = Path(space_dir)
        self._url = url
        self._api_key = api_key
        self._grpc_port = grpc_port
        self._class_name = _class_name(self._space_dir)
        self._client: Any = None
        self._initialized = False

    def _connect_sync(self) -> Any:
        import weaviate  # type: ignore
        import weaviate.classes.config as wcc
        from urllib.parse import urlparse

        parsed = urlparse(self._url)
        host = parsed.hostname or "localhost"
        http_port = parsed.port or 8080
        use_grpc = self._grpc_port > 0

        if self._api_key:
            auth = weaviate.auth.AuthApiKey(api_key=self._api_key)
        else:
            auth = None

        client = weaviate.connect_to_custom(
            http_host=host,
            http_port=http_port,
            http_secure=parsed.scheme == "https",
            grpc_host=host,
            grpc_port=self._grpc_port,
            grpc_secure=False,
            auth_credentials=auth,
        )
        return client

    def _ensure_class_sync(self, client: Any, dim: int) -> None:
        import weaviate.classes.config as wcc
        if client.collections.exists(self._class_name):
            return
        client.collections.create(
            name=self._class_name,
            vectorizer_config=wcc.Configure.Vectorizer.none(),
            vector_index_config=wcc.Configure.VectorIndex.hnsw(
                distance_metric=wcc.VectorDistances.COSINE,
            ),
            properties=[
                wcc.Property(name="chunk_id", data_type=wcc.DataType.TEXT),
                wcc.Property(name="source", data_type=wcc.DataType.TEXT),
                wcc.Property(name="chunk", data_type=wcc.DataType.INT),
                wcc.Property(name="line", data_type=wcc.DataType.INT),
                wcc.Property(name="text", data_type=wcc.DataType.TEXT),
            ],
        )
        log.info("weaviate_class_created", class_name=self._class_name, dim=dim)

    async def _get_client(self, dim: int | None = None) -> Any:
        if self._client is None:
            self._client = await asyncio.to_thread(self._connect_sync)
        if not self._initialized and dim is not None:
            await asyncio.to_thread(self._ensure_class_sync, self._client, dim)
            self._initialized = True
        return self._client

    async def upsert(self, chunks: list[dict], embeddings: list[list[float]]) -> None:
        if not chunks:
            return
        dim = len(embeddings[0])
        client = await self._get_client(dim=dim)

        def _do() -> None:
            collection = client.collections.get(self._class_name)
            with collection.batch.dynamic() as batch:
                for c, e in zip(chunks, embeddings):
                    batch.add_object(
                        properties={
                            "chunk_id": c["id"],
                            "source": c["source"],
                            "chunk": c.get("chunk", 0),
                            "line": c.get("line", 1),
                            "text": c["text"],
                        },
                        vector=e,
                        uuid=_chunk_uuid(c["id"]),
                    )

        await asyncio.to_thread(_do)
        log.debug("weaviate_upserted", class_name=self._class_name, count=len(chunks))

    async def delete_source(self, source: str) -> None:
        client = await self._get_client()

        def _do() -> None:
            import weaviate.classes.query as wcq
            collection = client.collections.get(self._class_name)
            collection.data.delete_many(
                where=wcq.Filter.by_property("source").equal(source)
            )

        await asyncio.to_thread(_do)

    async def search(self, query_vec: list[float], top_k: int = 5) -> list[dict]:
        client = await self._get_client()

        def _do() -> list[dict]:
            import weaviate.classes.query as wcq
            collection = client.collections.get(self._class_name)
            results = collection.query.near_vector(
                near_vector=query_vec,
                limit=top_k,
                return_properties=["chunk_id", "source", "chunk", "line", "text"],
                return_metadata=wcq.MetadataQuery(distance=True),
            )
            return [
                {
                    "id": o.properties["chunk_id"],
                    "source": o.properties["source"],
                    "chunk": o.properties.get("chunk", 0),
                    "line": o.properties.get("line", 1),
                    "text": o.properties["text"],
                    "distance": o.metadata.distance if o.metadata else 0.0,
                }
                for o in results.objects
            ]

        return await asyncio.to_thread(_do)

    async def fts_search(self, query: str, top_k: int = 5) -> list[tuple[str, float]]:
        client = await self._get_client()

        def _do() -> list[tuple[str, float]]:
            import weaviate.classes.query as wcq
            collection = client.collections.get(self._class_name)
            results = collection.query.bm25(
                query=query,
                query_properties=["text"],
                limit=top_k,
                return_properties=["chunk_id"],
                return_metadata=wcq.MetadataQuery(score=True),
            )
            return [
                (o.properties["chunk_id"],
                 float(o.metadata.score) if o.metadata else 0.0)
                for o in results.objects
            ]

        try:
            return await asyncio.to_thread(_do)
        except Exception as exc:
            log.debug("weaviate_fts_failed", error=str(exc))
            return []

    def status(self) -> dict:
        # Check live collection existence rather than using the in-memory
        # _initialized flag which is False until the first upsert call.
        enabled = self._initialized
        if not enabled and self._client is not None:
            try:
                enabled = self._client.collections.exists(self._class_name)
            except Exception:
                pass
        return {
            "enabled": enabled,
            "backend": "weaviate",
            "url": self._url,
            "class": self._class_name,
        }


def _chunk_uuid(chunk_id: str) -> str:
    """Deterministic UUID v5 from chunk_id for idempotent upserts."""
    import uuid
    return str(uuid.uuid5(uuid.NAMESPACE_OID, chunk_id))
