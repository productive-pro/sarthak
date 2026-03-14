from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Query
from pydantic import BaseModel, Field

router = APIRouter()


class ActivityRecord(BaseModel):
    # Valid values match the activity store's public ActivityType union.
    activity_type: str
    space_dir: str = ""
    concept_id: str = ""
    concept_title: str = ""
    session_id: str = ""
    content_text: str = ""
    media_path: str = ""
    metadata: dict[str, Any] = Field(default_factory=dict)


@router.post("/api/activity")
async def record_activity(body: ActivityRecord) -> dict:
    """Store any user-produced artefact (audio note, code run, test, etc.)."""
    from sarthak.storage.activity_store import write_activity

    row_id = await write_activity(
        activity_type=body.activity_type,  # type: ignore[arg-type]
        space_dir=body.space_dir,
        concept_id=body.concept_id,
        concept_title=body.concept_title,
        session_id=body.session_id,
        content_text=body.content_text,
        media_path=body.media_path,
        metadata=body.metadata,
    )
    return {"id": row_id}


@router.get("/api/activity")
async def list_activity(
    space_dir: str = "",
    activity_type: str = "",
    concept_title: str = "",
    days: int = Query(default=30, ge=1, le=3650),
    limit: int = Query(default=100, ge=1, le=500),
) -> list[dict]:
    """Query stored user activity with optional filters."""
    from sarthak.storage.activity_store import query_activity

    return await query_activity(
        space_dir=space_dir,
        activity_type=activity_type or None,  # type: ignore[arg-type]
        concept_title=concept_title,
        days=days,
        limit=limit,
    )


@router.get("/api/activity/summary")
async def activity_summary_api(
    space_dir: str,
    days: int = Query(default=7, ge=1, le=3650),
) -> dict:
    """Per-type activity counts for a space — used by the digest and dashboard."""
    from sarthak.storage.activity_store import activity_summary

    return await activity_summary(space_dir, days=days)
