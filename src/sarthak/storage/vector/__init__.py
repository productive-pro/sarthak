"""
vector/__init__.py — re-exports all EmbeddingRepository implementations.
"""
from __future__ import annotations

from sarthak.storage.vector.sqlite_vec import SqliteVecRepo

__all__ = ["SqliteVecRepo"]

try:
    from sarthak.storage.vector.qdrant import QdrantRepo
    __all__ += ["QdrantRepo"]
except ImportError:
    pass

try:
    from sarthak.storage.vector.chroma import ChromaRepo
    __all__ += ["ChromaRepo"]
except ImportError:
    pass

try:
    from sarthak.storage.vector.pgvector import PGVectorRepo
    __all__ += ["PGVectorRepo"]
except ImportError:
    pass

try:
    from sarthak.storage.vector.lancedb import LanceDBRepo
    __all__ += ["LanceDBRepo"]
except ImportError:
    pass

try:
    from sarthak.storage.vector.weaviate import WeaviateRepo
    __all__ += ["WeaviateRepo"]
except ImportError:
    pass
