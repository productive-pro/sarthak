"""
repositories/__init__.py — public surface for all repository types.

Usage:
    from sarthak.storage.repositories import (
        ActivityRepository, ChatRepository,
        EmbeddingRepository, RoadmapRepository,
        ActivityRepo, ChatRepo, EmbeddingRepo, RoadmapRepo,
    )
"""
from __future__ import annotations

# Protocol interfaces (structural typing)
from sarthak.storage.repositories.base import (
    ActivityRepository,
    ChatRepository,
    EmbeddingRepository,
)

# Concrete facade classes (lazy backend resolution)
from sarthak.storage.repositories.activity import ActivityRepo
from sarthak.storage.repositories.chat import ChatRepo
from sarthak.storage.repositories.embeddings import EmbeddingRepo
from sarthak.storage.repositories.roadmap import RoadmapRepo

__all__ = [
    # Protocols
    "ActivityRepository",
    "ChatRepository",
    "EmbeddingRepository",
    # Facades
    "ActivityRepo",
    "ChatRepo",
    "EmbeddingRepo",
    "RoadmapRepo",
]
