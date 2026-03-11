"""
sarthak.storage — pluggable storage layer.

Public surface:
    get_activity_repo()           → ActivityRepository
    await get_embedding_repo(dir) → EmbeddingRepository
    get_cache()                   → CacheBackend
    await cached(key, fn, ttl)    → Any
    space_cache_key(dir, suffix)  → str
    await invalidate_space_cache(dir)

Repository facades (lazy backend resolution):
    ActivityRepo, ChatRepo, EmbeddingRepo, RoadmapRepo

Protocols (structural typing):
    ActivityRepository, ChatRepository,
    EmbeddingRepository, RoadmapRepository
"""
from __future__ import annotations

from sarthak.storage.factory import (
    get_activity_repo,
    get_embedding_repo,
    get_cache,
    cached,
    space_cache_key,
    invalidate_space_cache,
    LRUCache,
    RedisCache,
    CacheBackend,
)

from sarthak.storage.repositories import (
    ActivityRepository,
    ChatRepository,
    EmbeddingRepository,
    ActivityRepo,
    ChatRepo,
    EmbeddingRepo,
    RoadmapRepo,
)

from sarthak.storage.sql_loader import (
    load_schema,
    load_queries,
    get_query,
)

__all__ = [
    # Factory
    "get_activity_repo",
    "get_embedding_repo",
    "get_cache",
    "cached",
    "space_cache_key",
    "invalidate_space_cache",
    "LRUCache",
    "RedisCache",
    "CacheBackend",
    # Repository facades
    "ActivityRepo",
    "ChatRepo",
    "EmbeddingRepo",
    "RoadmapRepo",
    # Protocols
    "ActivityRepository",
    "ChatRepository",
    "EmbeddingRepository",
    # SQL loader
    "load_schema",
    "load_queries",
    "get_query",
]
