"""
LanceDBRepo — LanceDB EmbeddingRepository.

Requires: pip install lancedb
Config:
    [storage.lancedb]
    uri = "~/.sarthak_ai/lancedb"   # local
    # uri = "s3://my-bucket/sarthak"  # S3-backed serverless

LanceDB is a columnar vector database (Rust-backed) that supports:
  - Local files (Apache Arrow / Lance format)
  - S3/GCS/Azure Blob serverless deployment
  - Native full-text search via tantivy
  - Zero-copy reads, versioned data

Each space gets its own LanceDB table named: sarthak_<slug>_<hash8>
"""
from __future__ import annotations

import asyncio
import hashlib
from pathlib import Path
from typing import Any

import structlog

log = structlog.get_logger(__name__)


def _table_name(space_dir: Path) -> str:
    slug = space_dir.name.lower().replace(" ", "_")[:24]
    h = hashlib.sha1(str(space_dir.resolve()).encode()).hexdigest()[:8]
    return f"sarthak_{slug}_{h}"


class LanceDBRepo:
    """EmbeddingRepository backed by LanceDB."""

    def __init__(
        self,
        space_dir: Path | str,
        uri: str = "~/.sarthak_ai/lancedb",
    ) -> None:
        self._space_dir = Path(space_dir)
        self._uri = str(Path(uri).expanduser().resolve())
        self._table_name = _table_name(self._space_dir)
        self._db: Any = None
        self._table: Any = None

    def _connect_sync(self) -> Any:
        import lancedb  # type: ignore
        return lancedb.connect(self._uri)

    async def _get_db(self) -> Any:
        if self._db is None:
            self._db = await asyncio.to_thread(self._connect_sync)
        return self._db

    async def _get_table(self, dim: int | None = None) -> Any:
        if self._table is not None:
            return self._table
        db = await self._get_db()

        def _open_or_create() -> Any:
            names = db.table_names()
            if self._table_name in names:
                return db.open_table(self._table_name)
            if dim is None:
                return None  # Table doesn't exist yet
            import pyarrow as pa  # type: ignore
            schema = pa.schema([
                pa.field("id", pa.string()),
                pa.field("source", pa.string()),
                pa.field("chunk", pa.int32()),
                pa.field("line", pa.int32()),
                pa.field("text", pa.string()),
                pa.field("embedding", pa.list_(pa.float32(), dim)),
            ])
            return db.create_table(self._table_name, schema=schema)

        self._table = await asyncio.to_thread(_open_or_create)
        return self._table

    async def upsert(self, chunks: list[dict], embeddings: list[list[float]]) -> None:
        if not chunks:
            return
        dim = len(embeddings[0])
        table = await self._get_table(dim=dim)

        def _do() -> None:
            import pyarrow as pa  # type: ignore
            data = [
                {
                    "id": c["id"],
                    "source": c["source"],
                    "chunk": c.get("chunk", 0),
                    "line": c.get("line", 1),
                    "text": c["text"],
                    "embedding": e,
                }
                for c, e in zip(chunks, embeddings)
            ]
            # LanceDB merge_insert upserts on the primary key "id"
            table.merge_insert("id").when_matched_update_all() \
                .when_not_matched_insert_all().execute(data)

        await asyncio.to_thread(_do)
        log.debug("lancedb_upserted", table=self._table_name, count=len(chunks))

    async def delete_source(self, source: str) -> None:
        table = await self._get_table()
        if table is None:
            return
        await asyncio.to_thread(lambda: table.delete(f"source = '{source}'"))

    async def search(self, query_vec: list[float], top_k: int = 5) -> list[dict]:
        table = await self._get_table()
        if table is None:
            return []

        def _do() -> list[dict]:
            results = (
                table.search(query_vec)
                .limit(top_k)
                .to_list()
            )
            for r in results:
                r.pop("embedding", None)  # Don't return raw vectors to callers
            return results

        return await asyncio.to_thread(_do)

    async def fts_search(self, query: str, top_k: int = 5) -> list[tuple[str, float]]:
        """Full-text search via LanceDB tantivy integration."""
        table = await self._get_table()
        if table is None:
            return []
        try:
            def _do() -> list[tuple[str, float]]:
                results = (
                    table.search(query, query_type="fts")
                    .limit(top_k)
                    .to_list()
                )
                return [(r["id"], float(r.get("_score", 0.0))) for r in results]
            return await asyncio.to_thread(_do)
        except Exception as exc:
            log.debug("lancedb_fts_failed", error=str(exc))
            return []

    def status(self) -> dict:
        # LanceDB stores tables as <uri>/<table_name>.lance directories.
        import os
        table_path = os.path.join(self._uri, f"{self._table_name}.lance")
        table_exists = os.path.isdir(table_path) or self._table is not None
        count = 0
        if self._table is not None:
            try:
                count = self._table.count_rows()
            except Exception:
                pass
        return {
            "enabled": table_exists,
            "backend": "lancedb",
            "uri": self._uri,
            "table": self._table_name,
            "indexed_chunks": count,
        }
