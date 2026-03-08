"""
Sarthak Spaces — Roadmap data models.

roadmap.json is the single source of truth for curriculum structure.
Progress (progress_pct) and recommendations are DERIVED on read.
"""
from __future__ import annotations

import uuid
from enum import Enum
from typing import Any

from pydantic import BaseModel, Field

# ── ID generators ─────────────────────────────────────────────────────────────

def _ch_id() -> str:
    return f"ch_{uuid.uuid4().hex[:8]}"

def _tp_id() -> str:
    return f"tp_{uuid.uuid4().hex[:8]}"

def _cn_id() -> str:
    return f"cn_{uuid.uuid4().hex[:8]}"

def _note_id() -> str:
    return f"note_{uuid.uuid4().hex[:12]}"

def _qt_id() -> str:
    return f"qt_{uuid.uuid4().hex[:12]}"

def _file_id() -> str:
    return f"file_{uuid.uuid4().hex[:8]}"


# ── Status enum ───────────────────────────────────────────────────────────────

class RoadmapStatus(str, Enum):
    NOT_STARTED = "not_started"
    IN_PROGRESS = "in_progress"
    REVIEW      = "review"
    COMPLETED   = "completed"

    def next(self) -> "RoadmapStatus":
        cycle = [self.NOT_STARTED, self.IN_PROGRESS, self.REVIEW, self.COMPLETED]
        idx = cycle.index(self)
        return cycle[(idx + 1) % len(cycle)]


# ── Concept ───────────────────────────────────────────────────────────────────

class Concept(BaseModel):
    id: str = Field(default_factory=_cn_id)
    title: str
    description: str = ""
    order: int = 0
    status: RoadmapStatus = RoadmapStatus.NOT_STARTED
    tags: list[str] = Field(default_factory=list)
    related_concepts: list[str] = Field(default_factory=list)  # concept IDs
    notes: list[str] = Field(default_factory=list)             # note IDs
    quicktests: list[str] = Field(default_factory=list)         # quicktest IDs


# ── Topic ─────────────────────────────────────────────────────────────────────

class Topic(BaseModel):
    id: str = Field(default_factory=_tp_id)
    title: str
    order: int = 0
    status: RoadmapStatus = RoadmapStatus.NOT_STARTED
    concepts: list[Concept] = Field(default_factory=list)


# ── Chapter ───────────────────────────────────────────────────────────────────

class Chapter(BaseModel):
    id: str = Field(default_factory=_ch_id)
    title: str
    description: str = ""
    order: int = 0
    status: RoadmapStatus = RoadmapStatus.NOT_STARTED
    progress_pct: float = 0.0
    topics: list[Topic] = Field(default_factory=list)

    def compute_progress(self) -> float:
        """Derive progress_pct from concept statuses. Does NOT mutate."""
        total = sum(len(t.concepts) for t in self.topics)
        if total == 0:
            return 0.0
        done = sum(
            1
            for t in self.topics
            for c in t.concepts
            if c.status == RoadmapStatus.COMPLETED
        )
        return round(done / total * 100, 1)

    def all_concepts(self) -> list[Concept]:
        return [c for t in self.topics for c in t.concepts]


# ── File link ─────────────────────────────────────────────────────────────────

class LinkedTarget(BaseModel):
    type: str   # "chapter" | "topic" | "concept"
    id: str


class FileLink(BaseModel):
    id: str = Field(default_factory=_file_id)
    path: str                                          # relative to space root
    linked_to: list[LinkedTarget] = Field(default_factory=list)


# ── Roadmap root ──────────────────────────────────────────────────────────────

class Roadmap(BaseModel):
    version: int = 1
    space: str
    chapters: list[Chapter] = Field(default_factory=list)
    files: list[FileLink] = Field(default_factory=list)
    recommendations: list[str] = Field(default_factory=list)  # concept IDs

    def get_concept(self, concept_id: str) -> Concept | None:
        for ch in self.chapters:
            for tp in ch.topics:
                for cn in tp.concepts:
                    if cn.id == concept_id:
                        return cn
        return None

    def all_concepts(self) -> list[Concept]:
        return [c for ch in self.chapters for c in ch.all_concepts()]

    def sorted_by_order(self) -> "Roadmap":
        """Return a new Roadmap with chapters/topics/concepts sorted by their order field."""
        updated = self.model_copy(deep=True)
        updated.chapters.sort(key=lambda c: c.order)
        for ch in updated.chapters:
            ch.topics.sort(key=lambda t: t.order)
            for tp in ch.topics:
                tp.concepts.sort(key=lambda cn: cn.order)
        return updated

    def compute_all_progress(self) -> "Roadmap":
        """Return a new Roadmap with progress_pct fields updated."""
        updated = self.model_copy(deep=True)
        for ch in updated.chapters:
            ch.progress_pct = ch.compute_progress()
        return updated

    def to_dict(self) -> dict[str, Any]:
        return self.model_dump(mode="json")


# ── DB row models (not stored in roadmap.json) ────────────────────────────────

class NoteRow(BaseModel):
    id: str = Field(default_factory=_note_id)
    chapter_id: str = ""
    topic_id: str = ""
    concept_id: str = ""
    title: str = ""
    body_md: str = ""
    type: str = "note"             # 'note' | 'explain'
    audio_path: str | None = None   # path to .webm audio blob
    video_path: str | None = None   # path to .webm video blob (screen/cam)
    created_at: str = ""


class QuickTestRow(BaseModel):
    id: str = Field(default_factory=_qt_id)
    chapter_id: str = ""
    topic_id: str = ""
    concept_id: str = ""
    prompt: str = ""
    response_md: str = ""
    input_mode: str = "user"         # "user" | "random" | "notes"
    created_at: str = ""
