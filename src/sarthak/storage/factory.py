"""
Storage factory — resolves backends from config.toml [storage].

Public API:
    get_activity_repo()           → ActivityRepository (process singleton)
    await get_embedding_repo(dir) → EmbeddingRepository (per-space singleton)
    get_cache()                   → CacheBackend (process singleton)
    await cached(key, factory)    → Any  (cache-aside helper)
    space_cache_key(dir, suffix)  → str
    await invalidate_space_cache(dir)

Supported backends
──────────────────
Relational  : sqlite (default) | postgres | duckdb | libsql
Vector      : sqlite_vec (default) | qdrant | chroma | pgvector | lancedb | weaviate
Cache       : in-process LRU (default) | redis
"""
from __future__ import annotations

import asyncio
import time
import threading
from collections import OrderedDict
from pathlib import Path
from typing import TYPE_CHECKING, Any

import structlog

if TYPE_CHECKING:
    from sarthak.storage.repositories.base import ActivityRepository, EmbeddingRepository

log = structlog.get_logger(__name__)

# ── Singleton state ───────────────────────────────────────────────────────────
_activity_repo: "ActivityRepository | None" = None
_embedding_repos: dict[str, "EmbeddingRepository"] = {}
_embedding_locks: dict[str, asyncio.Lock] = {}
_cache: "CacheBackend | None" = None
_global_lock = asyncio.Lock()
_activity_repo_lock = threading.Lock()  # guards sync get_activity_repo()
_cache_lock = threading.Lock()          # guards sync get_cache()


# ══════════════════════════════════════════════════════════════════════════════
# Cache layer
# ══════════════════════════════════════════════════════════════════════════════

class LRUCache:
    """In-process TTL LRU cache. No external deps."""

    def __init__(self, maxsize: int = 512, default_ttl: int = 300) -> None:
        self._store: OrderedDict[str, tuple[Any, float]] = OrderedDict()
        self._maxsize = maxsize
        self._default_ttl = default_ttl
        self._lock = asyncio.Lock()

    async def get(self, key: str) -> Any | None:
        async with self._lock:
            if key not in self._store:
                return None
            val, exp = self._store[key]
            if time.monotonic() > exp:
                del self._store[key]
                return None
            self._store.move_to_end(key)
            return val

    async def set(self, key: str, value: Any, ttl: int | None = None) -> None:
        async with self._lock:
            self._store[key] = (value, time.monotonic() + (ttl or self._default_ttl))
            self._store.move_to_end(key)
            if len(self._store) > self._maxsize:
                self._store.popitem(last=False)

    async def delete(self, key: str) -> None:
        async with self._lock:
            self._store.pop(key, None)

    async def delete_prefix(self, prefix: str) -> None:
        async with self._lock:
            for k in [k for k in self._store if k.startswith(prefix)]:
                del self._store[k]

    async def mget(self, keys: list[str]) -> list[Any | None]:
        """Batch get: single lock acquisition for all keys."""
        now = time.monotonic()
        results: list[Any | None] = []
        expired: list[str] = []
        async with self._lock:
            for key in keys:
                if key not in self._store:
                    results.append(None)
                    continue
                val, exp = self._store[key]
                if now > exp:
                    expired.append(key)  # collect expired keys, delete after iteration
                    results.append(None)
                else:
                    self._store.move_to_end(key)
                    results.append(val)
            for key in expired:
                self._store.pop(key, None)
        return results

    async def mset(self, items: dict[str, Any], ttl: int | None = None) -> None:
        """Batch set: single lock acquisition for all keys."""
        ttl_val = ttl or self._default_ttl
        now = time.monotonic()
        async with self._lock:
            for k, v in items.items():
                self._store[k] = (v, now + ttl_val)
                self._store.move_to_end(k)
            while len(self._store) > self._maxsize:
                self._store.popitem(last=False)

    async def close(self) -> None:
        pass

    @property
    def backend_name(self) -> str:
        return "lru"


class RedisCache:
    """Redis-backed cache. Falls back to LRU on any connection error."""

    def __init__(self, url: str, default_ttl: int = 300) -> None:
        self._url = url
        self._default_ttl = default_ttl
        self._redis: Any = None
        self._fallback = LRUCache(default_ttl=default_ttl)
        self._broken = False
        self._retry_after: float = 0.0  # monotonic timestamp

    async def _client(self) -> Any:
        if self._broken and time.monotonic() < self._retry_after:
            return None
        if self._redis is None:
            try:
                import redis.asyncio as aioredis  # type: ignore
                self._redis = aioredis.from_url(
                    self._url, decode_responses=True,
                    socket_connect_timeout=2, socket_timeout=2,
                    retry_on_timeout=True, health_check_interval=30,
                )
                await self._redis.ping()
                self._broken = False
                self._retry_after = 0.0
                log.info("redis_cache_connected", url=self._url)
            except Exception as exc:
                log.warning("redis_unavailable", error=str(exc))
                self._redis = None
                self._broken = True
                self._retry_after = time.monotonic() + 60.0  # retry after 60s
        return self._redis

    async def get(self, key: str) -> Any | None:
        import json as _j
        c = await self._client()
        if c:
            try:
                v = await c.get(f"sarthak:{key}")
                return _j.loads(v) if v else None
            except Exception:
                pass
        return await self._fallback.get(key)

    async def set(self, key: str, value: Any, ttl: int | None = None) -> None:
        import json as _j
        c = await self._client()
        if c:
            try:
                await c.set(f"sarthak:{key}", _j.dumps(value), ex=ttl or self._default_ttl)
                return
            except Exception:
                pass
        await self._fallback.set(key, value, ttl)

    async def delete(self, key: str) -> None:
        c = await self._client()
        if c:
            try:
                await c.delete(f"sarthak:{key}"); return
            except Exception:
                pass
        await self._fallback.delete(key)

    async def delete_prefix(self, prefix: str) -> None:
        c = await self._client()
        if c:
            try:
                pattern = f"sarthak:{prefix}*"
                cursor, keys_to_del = 0, []
                while True:
                    cursor, keys = await c.scan(cursor=cursor, match=pattern, count=100)
                    keys_to_del.extend(keys)
                    if cursor == 0:
                        break
                if keys_to_del:
                    await c.delete(*keys_to_del)
                return
            except Exception:
                pass
        await self._fallback.delete_prefix(prefix)

    async def mget(self, keys: list[str]) -> list[Any | None]:
        import json as _j
        c = await self._client()
        if c:
            try:
                raw = await c.mget(*[f"sarthak:{k}" for k in keys])
                return [_j.loads(v) if v else None for v in raw]
            except Exception:
                pass
        return await self._fallback.mget(keys)

    async def mset(self, items: dict[str, Any], ttl: int | None = None) -> None:
        import json as _j
        c = await self._client()
        if c:
            try:
                pipe = c.pipeline(transaction=False)
                for k, v in items.items():
                    pipe.set(f"sarthak:{k}", _j.dumps(v), ex=ttl or self._default_ttl)
                await pipe.execute()
                return
            except Exception:
                pass
        await self._fallback.mset(items, ttl)

    async def close(self) -> None:
        if self._redis:
            try:
                await self._redis.aclose()
            except Exception:
                pass

    @property
    def backend_name(self) -> str:
        return "redis" if not self._broken else "lru"


CacheBackend = LRUCache | RedisCache


# ══════════════════════════════════════════════════════════════════════════════
# Public API
# ══════════════════════════════════════════════════════════════════════════════

def get_activity_repo() -> "ActivityRepository":
    """Process-level singleton ActivityRepository. Thread-safe."""
    global _activity_repo
    if _activity_repo is None:
        with _activity_repo_lock:
            if _activity_repo is None:
                _activity_repo = _build_activity_repo()
    return _activity_repo


async def get_embedding_repo(space_dir: str | Path) -> "EmbeddingRepository":
    """Per-space EmbeddingRepository singleton. Created once per space_dir."""
    key = str(Path(space_dir).resolve())
    if key in _embedding_repos:
        return _embedding_repos[key]
    if key not in _embedding_locks:
        async with _global_lock:
            if key not in _embedding_locks:
                _embedding_locks[key] = asyncio.Lock()
    async with _embedding_locks[key]:
        if key not in _embedding_repos:
            _embedding_repos[key] = _build_embedding_repo(Path(space_dir))
    return _embedding_repos[key]


async def remove_embedding_repo(space_dir: str | Path) -> None:
    """Remove per-space embedding repo + lock to avoid unbounded growth.

    Must be called when a space is deleted so that the per-space singletons
    don't accumulate indefinitely in long-running processes.
    """
    key = str(Path(space_dir).resolve())
    async with _global_lock:
        repo = _embedding_repos.pop(key, None)
        _embedding_locks.pop(key, None)
    if repo:
        close = getattr(repo, "aclose", None) or getattr(repo, "close", None)
        if close:
            try:
                result = close()
                if asyncio.iscoroutine(result):
                    await result
            except Exception:
                pass


def get_cache() -> CacheBackend:
    """Process-level singleton cache (Redis or LRU). Thread-safe."""
    global _cache
    if _cache is None:
        with _cache_lock:
            if _cache is None:
                _cache = _build_cache()
    return _cache


async def invalidate_space_cache(space_dir: str) -> None:
    """Invalidate all cache entries for a space."""
    await get_cache().delete_prefix(_space_prefix(space_dir))
    log.debug("space_cache_invalidated", space=space_dir)


def space_cache_key(space_dir: str, suffix: str) -> str:
    return f"{_space_prefix(space_dir)}:{suffix}"


_MISS = object()  # sentinel distinct from any cacheable value


async def cached(key: str, factory, ttl: int | None = None) -> Any:
    """
    Cache-aside: call factory() on miss, cache and return result.

    Wraps the cached value in a single-element list so that falsy values
    (False, 0, [], {}, "") are distinguished from a genuine cache miss
    (None returned by get()).
    """
    cache = get_cache()
    hit = await cache.get(key)
    if hit is not None:
        # New format for cached None: {"__cached_none__": True}
        if isinstance(hit, dict) and hit.get("__cached_none__") is True:
            return None
        # Backward-compatible list wrapper
        if isinstance(hit, list) and len(hit) == 1:
            return hit[0]
        return hit
    value = await factory() if asyncio.iscoroutinefunction(factory) else factory()
    if value is None:
        await cache.set(key, {"__cached_none__": True}, ttl)
    else:
        await cache.set(key, [value], ttl)  # wrap so falsy values survive round-trip
    return value


# ══════════════════════════════════════════════════════════════════════════════
# Private builders
# ══════════════════════════════════════════════════════════════════════════════

def _load_cfg() -> dict:
    try:
        from sarthak.core.config import load_config
        return load_config().get("storage", {})
    except Exception:
        return {}


def _build_activity_repo() -> "ActivityRepository":
    cfg = _load_cfg()
    backend = cfg.get("backend", "sqlite")
    builders = {
        "sqlite": lambda: _build_activity_sqlite(),
        "postgres": lambda: _build_activity_postgres(cfg),
        "postgresql": lambda: _build_activity_postgres(cfg),
        "duckdb": lambda: _build_activity_duckdb(cfg),
        "libsql": lambda: _build_activity_libsql(cfg),
    }
    builder = builders.get(backend)
    repo = builder() if builder else None
    if repo:
        return repo
    log.warning("unknown_activity_backend_fallback", requested=backend)
    return _build_activity_sqlite()


def _build_embedding_repo(space_dir: Path) -> "EmbeddingRepository":
    cfg = _load_cfg()
    backend = cfg.get("vector_backend", "sqlite_vec")
    builders = {
        "sqlite_vec": lambda: _build_vector_sqlite(space_dir),
        "qdrant": lambda: _build_vector_qdrant(space_dir, cfg),
        "chroma": lambda: _build_vector_chroma(space_dir, cfg),
        "pgvector": lambda: _build_vector_pgvector(space_dir, cfg),
        "lancedb": lambda: _build_vector_lancedb(space_dir, cfg),
        "weaviate": lambda: _build_vector_weaviate(space_dir, cfg),
    }
    builder = builders.get(backend)
    repo = builder() if builder else None
    if repo:
        return repo
    log.warning("unknown_vector_backend_fallback", requested=backend)
    return _build_vector_sqlite(space_dir)


def _build_activity_sqlite():
    from sarthak.storage.backends.sqlite import SQLiteActivityRepo
    log.info("activity_backend", backend="sqlite")
    return SQLiteActivityRepo()


def _build_activity_postgres(cfg: dict):
    try:
        from sarthak.storage.backends.postgres import PostgresActivityRepo
        url = cfg.get("postgres", {}).get("url", "")
        if not url:
            raise ValueError("[storage.postgres] url not configured")
        log.info("activity_backend", backend="postgres")
        return PostgresActivityRepo(
            url=url,
            pool_size=int(cfg.get("postgres", {}).get("pool_size", 5)),
        )
    except ImportError:
        log.warning("postgres_unavailable", hint="pip install asyncpg")
    except Exception as exc:
        log.warning("postgres_unavailable", error=str(exc))
    return None


def _build_activity_duckdb(cfg: dict):
    try:
        from sarthak.storage.backends.duckdb import DuckDBActivityRepo
        path = cfg.get("duckdb", {}).get("path", "~/.sarthak_ai/sarthak.duckdb")
        log.info("activity_backend", backend="duckdb")
        return DuckDBActivityRepo(path=path)
    except ImportError:
        log.warning("duckdb_unavailable", hint="pip install duckdb")
    return None


def _build_activity_libsql(cfg: dict):
    try:
        from sarthak.storage.backends.libsql import LibSQLActivityRepo
        lcfg = cfg.get("libsql", {})
        url = lcfg.get("url", "file:///~/.sarthak_ai/sarthak.db")
        token = lcfg.get("auth_token", "")
        log.info("activity_backend", backend="libsql")
        return LibSQLActivityRepo(url=url, auth_token=token)
    except ImportError:
        log.warning("libsql_unavailable", hint="pip install libsql-client")
    return None


def _build_vector_sqlite(space_dir: Path):
    from sarthak.storage.vector.sqlite_vec import SqliteVecRepo
    log.debug("vector_backend", backend="sqlite_vec", space=str(space_dir))
    return SqliteVecRepo(space_dir)


def _build_vector_qdrant(space_dir: Path, cfg: dict):
    try:
        from sarthak.storage.vector.qdrant import QdrantRepo
        qcfg = cfg.get("qdrant", {})
        log.info("vector_backend", backend="qdrant")
        return QdrantRepo(
            space_dir,
            url=qcfg.get("url", "http://localhost:6333"),
            api_key=qcfg.get("api_key", ""),
            collection_prefix=qcfg.get("collection_prefix", "sarthak"),
        )
    except ImportError:
        log.warning("qdrant_unavailable", hint="pip install qdrant-client")
    return None


def _build_vector_chroma(space_dir: Path, cfg: dict):
    try:
        from sarthak.storage.vector.chroma import ChromaRepo
        ccfg = cfg.get("chroma", {})
        log.info("vector_backend", backend="chroma")
        return ChromaRepo(
            space_dir,
            persist_directory=ccfg.get("persist_directory", "~/.sarthak_ai/chroma"),
            host=ccfg.get("host", ""),
            port=int(ccfg.get("port", 8000)),
        )
    except ImportError:
        log.warning("chroma_unavailable", hint="pip install chromadb")
    return None


def _build_vector_pgvector(space_dir: Path, cfg: dict):
    try:
        from sarthak.storage.vector.pgvector import PGVectorRepo
        url = cfg.get("postgres", {}).get("url", "")
        if not url:
            raise ValueError("[storage.postgres] url required for pgvector")
        log.info("vector_backend", backend="pgvector")
        return PGVectorRepo(
            space_dir,
            url=url,
            table_prefix=cfg.get("pgvector", {}).get("table_prefix", "sarthak"),
        )
    except ImportError:
        log.warning("pgvector_unavailable", hint="pip install asyncpg pgvector")
    except Exception as exc:
        log.warning("pgvector_unavailable", error=str(exc))
    return None


def _build_vector_lancedb(space_dir: Path, cfg: dict):
    try:
        from sarthak.storage.vector.lancedb import LanceDBRepo
        uri = cfg.get("lancedb", {}).get("uri", "~/.sarthak_ai/lancedb")
        log.info("vector_backend", backend="lancedb")
        return LanceDBRepo(space_dir, uri=uri)
    except ImportError:
        log.warning("lancedb_unavailable", hint="pip install lancedb pyarrow")
    return None


def _build_vector_weaviate(space_dir: Path, cfg: dict):
    try:
        from sarthak.storage.vector.weaviate import WeaviateRepo
        wcfg = cfg.get("weaviate", {})
        log.info("vector_backend", backend="weaviate")
        return WeaviateRepo(
            space_dir,
            url=wcfg.get("url", "http://localhost:8080"),
            api_key=wcfg.get("api_key", ""),
            grpc_port=int(wcfg.get("grpc_port", 50051)),
        )
    except ImportError:
        log.warning("weaviate_unavailable", hint="pip install weaviate-client>=4.0")
    return None


def _build_cache() -> CacheBackend:
    cfg = _load_cfg()
    redis_cfg = cfg.get("redis", {})
    url = redis_cfg.get("url", "")
    ttl = int(redis_cfg.get("default_ttl", 300))
    if url:
        log.info("cache_backend", backend="redis", url=url, ttl=ttl)
        return RedisCache(url=url, default_ttl=ttl)
    log.info("cache_backend", backend="lru", ttl=ttl)
    return LRUCache(default_ttl=ttl)


def _space_prefix(space_dir: str) -> str:
    return f"space:{Path(space_dir).as_posix()}"
