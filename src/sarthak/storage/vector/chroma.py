"""
ChromaRepo — Chroma EmbeddingRepository implementation.

Requires: pip install chromadb
Config:
    [storage.chroma]
    persist_directory = "~/.sarthak_ai/chroma"
    host = ""   # set for HTTP client (remote Chroma)
    port = 8000
"""
from __future__ import annotations

import hashlib
import re
from pathlib import Path
from typing import Any

import structlog

log = structlog.get_logger(__name__)


def _collection_name(space_dir: Path) -> str:
    name = re.sub(r"[^a-z0-9_-]", "_", Path(space_dir).name.lower())
    h = hashlib.md5(str(space_dir).encode()).hexdigest()[:6]
    return f"sarthak_{name}_{h}"


class ChromaRepo:
    """
    EmbeddingRepository backed by ChromaDB.
    Supports both persistent local client and HTTP client for remote Chroma.
    """

    def __init__(
        self,
        space_dir: Path | str,
        *,
        persist_directory: str = "~/.sarthak_ai/chroma",
        host: str = "",
        port: int = 8000,
    ) -> None:
        self._space_dir = Path(space_dir)
        self._persist_dir = str(Path(persist_directory).expanduser())
        self._host = host
        self._port = port
        self._collection_name = _collection_name(self._space_dir)
        self._client: Any = None
        self._collection: Any = None

    def _get_client(self) -> Any:
        if self._client is None:
            import chromadb  # type: ignore
            if self._host:
                self._client = chromadb.HttpClient(
                    host=self._host, port=self._port
                )
            else:
                self._client = chromadb.PersistentClient(path=self._persist_dir)
        return self._client

    def _get_collection(self) -> Any:
        if self._collection is None:
            client = self._get_client()
            self._collection = client.get_or_create_collection(
                name=self._collection_name,
                metadata={"hnsw:space": "cosine"},
            )
        return self._collection

    async def upsert(
        self,
        chunks: list[dict],
        embeddings: list[list[float]],
    ) -> None:
        import asyncio

        def _do() -> None:
            col = self._get_collection()
            col.upsert(
                ids=[c["id"] for c in chunks],
                embeddings=embeddings,
                documents=[c.get("text", "") for c in chunks],
                metadatas=[
                    {
                        "source": c.get("source", ""),
                        "line":   c.get("line", 1),
                        "chunk":  c.get("chunk", 0),
                    }
                    for c in chunks
                ],
            )

        await asyncio.to_thread(_do)
        log.debug("chroma_upserted", count=len(chunks))

    async def delete_source(self, source: str) -> None:
        import asyncio

        def _do() -> None:
            col = self._get_collection()
            results = col.get(where={"source": source})
            if results and results["ids"]:
                col.delete(ids=results["ids"])

        await asyncio.to_thread(_do)

    async def search(
        self, query_vec: list[float], top_k: int = 5
    ) -> list[dict]:
        import asyncio

        def _do() -> list[dict]:
            col = self._get_collection()
            results = col.query(
                query_embeddings=[query_vec],
                n_results=top_k,
                include=["documents", "metadatas", "distances"],
            )
            out = []
            for i, chunk_id in enumerate(results["ids"][0]):
                meta = results["metadatas"][0][i] if results.get("metadatas") else {}
                dist = results["distances"][0][i] if results.get("distances") else 1.0
                out.append({
                    "id":       chunk_id,
                    "source":   meta.get("source", ""),
                    "line":     meta.get("line", 1),
                    "chunk":    meta.get("chunk", 0),
                    "text":     results["documents"][0][i] if results.get("documents") else "",
                    "distance": dist,
                })
            return out

        try:
            return await asyncio.to_thread(_do)
        except Exception as exc:
            log.warning("chroma_search_failed", error=str(exc))
            return []

    async def fts_search(self, query: str, top_k: int = 5) -> list[tuple[str, float]]:
        """Chroma has no BM25 — fall back to vector-only RRF."""
        return []

    def status(self) -> dict:
        try:
            col = self._get_collection()
            count = col.count()
            return {
                "enabled": True,
                "backend": "chroma",
                "collection": self._collection_name,
                "indexed_chunks": count,
            }
        except Exception:
            return {
                "enabled": False,
                "backend": "chroma",
                "collection": self._collection_name,
                "indexed_chunks": 0,
            }
