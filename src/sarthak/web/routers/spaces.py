"""
spaces.py — Core Space CRUD and session endpoints.

Focused on: list, init, activate, delete, recover, session, quick, profile-update.
Other concerns are split into:
  spaces_rag.py      — document indexing and search
  spaces_practice.py — practice test generation and grading
  spaces_settings.py — profile, settings, overview, insights, file ops

IMPORTANT: fixed-path routes (/api/spaces/init, /api/spaces/rag/*, etc.) MUST
be registered BEFORE the roadmap router which registers /{space}/... wildcards.
"""
from __future__ import annotations

import asyncio
from pathlib import Path

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from sarthak.core.logging import get_logger
from sarthak.web.routers.helpers import (
    get_space_or_404,
    invalidate_spaces_list_cache,
    resolve_space_dir,
)

log = get_logger(__name__)

router = APIRouter()


# ── Expert templates ──────────────────────────────────────────────────────────

@router.get("/api/spaces/expert-templates")
async def list_expert_templates() -> list[dict]:
    """Return curated expert space templates for the creation wizard."""
    from sarthak.data.expert_spaces import load_expert_spaces
    return load_expert_spaces()


# ── List / active ─────────────────────────────────────────────────────────────

@router.get("/api/spaces")
async def list_spaces_api() -> list[dict]:
    from sarthak.spaces.store import get_active_space, list_spaces, load_space
    active = get_active_space()
    active_dir = active.get("directory", "") if active else ""
    spaces = list_spaces()
    for s in spaces:
        s["is_active"] = s.get("directory", "") == active_dir
        if not s.get("goal") and not s.get("description"):
            try:
                cfg = load_space(Path(s["directory"]))
                if cfg:
                    s["goal"] = cfg.get("goal", "")
                    s["description"] = cfg.get("description", "")
            except Exception:
                pass
    return spaces


@router.get("/api/spaces/active")
async def get_active_space_api() -> dict:
    from sarthak.spaces.store import get_active_space
    return get_active_space() or {}


class ActivateReq(BaseModel):
    directory: str


@router.post("/api/spaces/activate")
async def activate_space_api(body: ActivateReq) -> dict:
    from sarthak.spaces.store import clear_active_space, set_active_space
    if not body.directory.strip():
        clear_active_space()
        invalidate_spaces_list_cache()
        return {"ok": True, "name": "", "directory": ""}
    ws = Path(body.directory).expanduser().resolve()
    try:
        space = set_active_space(ws)
        invalidate_spaces_list_cache()
        return {"ok": True, "name": space.get("name", ""), "directory": str(ws)}
    except FileNotFoundError as exc:
        raise HTTPException(404, str(exc))


# ── Init ──────────────────────────────────────────────────────────────────────

class SpaceInit(BaseModel):
    directory: str
    space_type: str = "custom"
    background: str = ""
    name: str = ""
    goal: str = ""
    rag_enabled: bool = False


async def _post_init(ws, profile, discovered_folders, domain_name=""):
    """Background: write directory structure doc + generate roadmap."""
    from sarthak.spaces.roadmap_init import ensure_roadmap, write_directory_structure
    from sarthak.spaces.workspace_transformer import TEMPLATES
    default_dirs = list(TEMPLATES.get(profile.space_type, {}).get("directories", []))
    all_dirs = list(dict.fromkeys(default_dirs + discovered_folders))
    write_directory_structure(ws, domain_name or profile.domain, all_dirs)
    await ensure_roadmap(ws, profile)


@router.post("/api/spaces/init")
async def init_space_api(body: SpaceInit) -> dict:
    """Initialise a space: config, workspace template, DB, domain discovery, roadmap."""
    from sarthak.spaces.models import SpaceType, ToolRecommendation
    from sarthak.spaces.roadmap.db import RoadmapDB
    from sarthak.spaces.roadmap_init import discover_custom_domain
    from sarthak.spaces.store import init_space, init_space_profile, load_space, save_profile
    from sarthak.spaces.workspace_transformer import WorkspaceTransformer

    ws = Path(body.directory).expanduser().resolve()
    st = SpaceType(body.space_type)

    domain_name = ""
    recommended_tools = None
    clarifying_questions: list[str] = []
    discovered_folders: list[str] = []

    if st == SpaceType.CUSTOM and (body.background or body.goal):
        discovery = await discover_custom_domain(background=body.background, goal=body.goal)
        domain_name = discovery.get("domain_name", "")
        clarifying_questions = discovery.get("clarifying_questions", [])
        raw_tools = discovery.get("recommended_tools", [])
        recommended_tools = [
            ToolRecommendation(
                name=t.get("name", ""), purpose=t.get("purpose", ""),
                install_linux=t.get("install", ""),
            )
            for t in raw_tools if t.get("name")
        ]
        discovered_folders = discovery.get("workspace_folders", [])
        if discovered_folders:
            body = body.model_copy(update={"goal": discovery.get("suggested_goal", body.goal)})

    if not load_space(ws):
        init_space(
            ws,
            name=body.name or domain_name or st.value.replace("_", " ").title(),
            description=f"Sarthak Space: {domain_name or st.value}",
            goal=body.goal,
        )
    profile = init_space_profile(
        ws, st, background=body.background, learner_name=body.name,
        goal=body.goal, domain_name=domain_name, recommended_tools=recommended_tools,
    )

    def _transform() -> list[str]:
        return WorkspaceTransformer(ws).transform(st, extra_dirs=discovered_folders)

    async def _db_init() -> None:
        db = RoadmapDB(ws)
        await db.init()

    try:
        created, _ = await asyncio.gather(asyncio.to_thread(_transform), _db_init())
    except Exception as exc:
        log.error("space_init_failed", error=str(exc))
        raise HTTPException(500, f"Space initialization failed: {exc}")

    if body.rag_enabled:
        profile.rag_enabled = True
        await asyncio.to_thread(save_profile, ws, profile)

    asyncio.create_task(_post_init(ws, profile, discovered_folders, domain_name))
    invalidate_spaces_list_cache()

    return {
        "name":                body.name or domain_name or st.value.replace("_", " ").title(),
        "domain":              profile.domain,
        "directory":           str(ws),
        "space_type":          st.value,
        "files_created":       len(created),
        "rag_enabled":         body.rag_enabled,
        "clarifying_questions": clarifying_questions,
    }


# ── Roadmap ───────────────────────────────────────────────────────────────────

class RoadmapRegenerateReq(BaseModel):
    directory: str


@router.post("/api/spaces/regenerate-roadmap")
async def regenerate_roadmap_api(body: RoadmapRegenerateReq) -> dict:
    from sarthak.spaces.roadmap_init import ensure_roadmap
    from sarthak.spaces.store import load_profile
    ws = Path(body.directory).expanduser().resolve()
    profile = load_profile(ws)
    if profile is None:
        raise HTTPException(404, "Space not found. Run spaces/init first.")
    success = await ensure_roadmap(ws, profile, force=True)
    if not success:
        raise HTTPException(500, "Roadmap generation failed — check logs for details.")
    return {"ok": True, "directory": str(ws)}


class RoadmapRefineReq(BaseModel):
    directory: str
    answers: str


@router.post("/api/spaces/refine")
async def refine_space_roadmap(body: RoadmapRefineReq) -> dict:
    from sarthak.spaces.roadmap_init import refine_roadmap
    from sarthak.spaces.store import load_profile
    ws = Path(body.directory).expanduser().resolve()
    profile = load_profile(ws)
    if profile is None:
        raise HTTPException(404, "Space not found.")

    async def _run():
        await refine_roadmap(ws, profile, body.answers)

    asyncio.create_task(_run())
    return {"ok": True, "scheduled": True, "directory": str(ws)}


# ── Delete / recover ──────────────────────────────────────────────────────────

class SpaceDeleteReq(BaseModel):
    directory: str
    name: str


@router.post("/api/spaces/delete")
async def delete_space_api(body: SpaceDeleteReq) -> dict:
    from sarthak.spaces.store import list_spaces, trash_space
    ws = Path(body.directory).expanduser().resolve()
    all_spaces = list_spaces()
    entry = next((s for s in all_spaces if s.get("directory") == str(ws)), None)
    if entry and body.name and entry.get("name") != body.name:
        raise HTTPException(400, "Space name confirmation does not match.")
    result = trash_space(ws, body.name)
    invalidate_spaces_list_cache()
    try:
        from sarthak.storage.factory import remove_embedding_repo
        await remove_embedding_repo(ws)
    except Exception:
        pass
    return {"ok": True, **result}


@router.get("/api/spaces/trashed")
async def list_trashed_spaces_api() -> list[dict]:
    from sarthak.spaces.store import list_trashed_spaces
    return list_trashed_spaces()


class SpaceRecoverReq(BaseModel):
    directory: str


@router.post("/api/spaces/recover")
async def recover_space_api(body: SpaceRecoverReq) -> dict:
    from sarthak.spaces.store import recover_space
    ws = Path(body.directory).expanduser().resolve()
    try:
        entry = recover_space(ws)
    except FileExistsError as exc:
        raise HTTPException(409, str(exc))
    except FileNotFoundError as exc:
        raise HTTPException(404, str(exc))
    return {"ok": True, "space": entry}


class SpaceDeletePermanentReq(BaseModel):
    directory: str


@router.post("/api/spaces/delete-permanent")
async def delete_space_permanent_api(body: SpaceDeletePermanentReq) -> dict:
    from sarthak.spaces.store import delete_space_permanently
    ws = Path(body.directory).expanduser().resolve()
    removed = delete_space_permanently(ws)
    return {"ok": True, "removed": removed}


# ── Session ───────────────────────────────────────────────────────────────────

class SessionReq(BaseModel):
    directory: str
    reshape: bool = False


@router.post("/api/spaces/session")
async def run_session(body: SessionReq) -> dict:
    from sarthak.spaces.orchestrator import SpacesOrchestrator
    orch = SpacesOrchestrator(Path(body.directory).expanduser().resolve())
    result = await orch.next_session(reshape_workspace=body.reshape)
    return {
        "reply":             result.reply,
        "xp_earned":         result.xp_earned,
        "workspace_changes": result.workspace_changes or [],
    }


@router.post("/api/spaces/quick")
async def quicktest(body: SessionReq) -> dict:
    from sarthak.spaces.orchestrator import SpacesOrchestrator
    orch = SpacesOrchestrator(Path(body.directory).expanduser().resolve())
    result = await orch.quicktest()
    return {"reply": result.reply}


class ProfileUpdate(BaseModel):
    directory: str
    background: str = ""
    goal: str = ""
    name: str = ""


@router.post("/api/spaces/profile")
async def update_profile(body: ProfileUpdate) -> dict:
    from sarthak.spaces.orchestrator import SpacesOrchestrator
    orch = SpacesOrchestrator(Path(body.directory).expanduser().resolve())
    kwargs = {k: v for k, v in [
        ("background", body.background), ("goal", body.goal), ("name", body.name)
    ] if v}
    if not kwargs:
        raise HTTPException(400, "Provide at least one field to update")
    orch.update_learner(**kwargs)
    return {"status": orch.get_status()}


# ── Session end ───────────────────────────────────────────────────────────────

class SessionEndReq(BaseModel):
    task_completed: bool = True
    understanding_rating: int = 3
    stuck_on: list[str] = []
    breakthrough: str = ""
    session_id: str = ""


@router.post("/api/spaces/{space_id}/session/end")
async def end_session_api(space_id: str, body: SessionEndReq) -> dict:
    from sarthak.spaces.models import SelfReport
    from sarthak.spaces.orchestrator import SpacesOrchestrator
    match = get_space_or_404(space_id)
    orch = SpacesOrchestrator(Path(match["directory"]))
    report = SelfReport(
        task_completed=body.task_completed,
        understanding_rating=body.understanding_rating,
        stuck_on=body.stuck_on,
        breakthrough=body.breakthrough,
    )
    result = await orch.end_session(report)
    return {
        "reply":         result.reply,
        "xp_earned":     result.xp_earned,
        "optimizations": [o.model_dump() for o in (result.optimizations or [])],
        "badges_earned": result.badges_earned,
    }
