from __future__ import annotations

import asyncio
from pathlib import Path

from fastapi import APIRouter, File, HTTPException, UploadFile
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from sarthak.core.logging import get_logger
from sarthak.web.routers.helpers import get_space_or_404, invalidate_spaces_list_cache, resolve_space_dir

log = get_logger(__name__)

router = APIRouter()


# ── Spaces — fixed paths MUST come BEFORE roadmap_router include ──────────────
# FastAPI matches in registration order. roadmap_router registers /{space}/...
# which would match "init", "rag", "session", "quick", "profile" as space names.


@router.get("/api/spaces")
async def list_spaces_api() -> list[dict]:
    from pathlib import Path
    from sarthak.spaces.store import get_active_space, list_spaces, load_space

    active = get_active_space()
    active_dir = active.get("directory", "") if active else ""
    spaces = list_spaces()
    for s in spaces:
        s["is_active"] = s.get("directory", "") == active_dir
        # Enrich with goal/description from space config if not in registry
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

    active = get_active_space()
    return active or {}


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


class SpaceInit(BaseModel):
    directory: str
    space_type: str = "custom"  # default to custom so domain discovery always runs
    background: str = ""
    name: str = ""
    goal: str = ""
    rag_enabled: bool = False


async def _post_init(ws, profile, discovered_folders, domain_name=""):
    """Background tasks after space creation: directory structure doc + roadmap."""
    from sarthak.spaces.roadmap_init import ensure_roadmap, write_directory_structure
    from sarthak.spaces.workspace_transformer import TEMPLATES

    default_dirs = list(TEMPLATES.get(profile.space_type, {}).get("directories", []))
    all_dirs = list(dict.fromkeys(default_dirs + discovered_folders))
    write_directory_structure(ws, domain_name or profile.domain, all_dirs)
    await ensure_roadmap(ws, profile)


@router.post("/api/spaces/init")
async def init_space_api(body: SpaceInit) -> dict:
    """Initialize a space: create config, apply workspace template, prime SQLite DB,
    run domain discovery for CUSTOM spaces, and generate roadmap.

    WorkspaceTransformer.transform is sync I/O — run in thread, parallelise with DB init.
    Roadmap generation runs in background after responding so the UI isn't blocked.
    """
    from sarthak.spaces.models import SpaceType, ToolRecommendation
    from sarthak.spaces.roadmap.db import RoadmapDB
    from sarthak.spaces.roadmap_init import discover_custom_domain
    from sarthak.spaces.store import (
        init_space,
        init_space_profile,
        load_space,
        save_profile,
    )
    from sarthak.spaces.workspace_transformer import WorkspaceTransformer

    ws = Path(body.directory).expanduser().resolve()
    st = SpaceType(body.space_type)

    # For CUSTOM spaces: discover the actual domain via LLM before persisting profile
    domain_name = ""
    recommended_tools = None
    clarifying_questions: list[str] = []
    discovered_folders: list[str] = []
    if st == SpaceType.CUSTOM and (body.background or body.goal):
        discovery = await discover_custom_domain(
            background=body.background,
            goal=body.goal,
        )
        domain_name = discovery.get("domain_name", "")
        clarifying_questions = discovery.get("clarifying_questions", [])
        # Convert tool dicts to ToolRecommendation objects
        raw_tools = discovery.get("recommended_tools", [])
        recommended_tools = [
            ToolRecommendation(
                name=t.get("name", ""),
                purpose=t.get("purpose", ""),
                install_linux=t.get("install", ""),
            )
            for t in raw_tools if t.get("name")
        ]
        # Update workspace template with discovered folders if provided
        discovered_folders = discovery.get("workspace_folders", [])
        if discovered_folders:
            body = body.model_copy(update={"goal": discovery.get("suggested_goal", body.goal)})

    # Sync config writes — fast, no thread needed
    if not load_space(ws):
        init_space(
            ws,
            name=body.name or domain_name or st.value.replace("_", " ").title(),
            description=f"Sarthak Space: {domain_name or st.value}",
            goal=body.goal,
        )
    profile = init_space_profile(
        ws, st,
        background=body.background,
        learner_name=body.name,
        goal=body.goal,
        domain_name=domain_name,
        recommended_tools=recommended_tools,
    )

    # Parallelize: workspace template I/O  +  SQLite schema init
    def _transform() -> list[str]:
        return WorkspaceTransformer(ws).transform(st, extra_dirs=discovered_folders)

    async def _db_init() -> None:
        db = RoadmapDB(ws)
        await db.init()

    try:
        created, _ = await asyncio.gather(
            asyncio.to_thread(_transform),
            _db_init(),
        )
    except Exception as exc:
        log.error("space_init_failed", error=str(exc))
        raise HTTPException(500, f"Space initialization failed: {exc}")

    if body.rag_enabled:
        profile.rag_enabled = True
        await asyncio.to_thread(save_profile, ws, profile)

    # Write directory structure doc + generate roadmap in background
    asyncio.create_task(_post_init(ws, profile, discovered_folders, domain_name))
    invalidate_spaces_list_cache()

    return {
        "name": body.name or domain_name or st.value.replace("_", " ").title(),
        "domain": profile.domain,
        "directory": str(ws),
        "space_type": st.value,
        "files_created": len(created),
        "rag_enabled": body.rag_enabled,
        "clarifying_questions": clarifying_questions,
    }


class RoadmapRegenerateReq(BaseModel):
    directory: str


@router.post("/api/spaces/regenerate-roadmap")
async def regenerate_roadmap_api(body: RoadmapRegenerateReq) -> dict:
    """Force-regenerate the roadmap for a space, discarding the existing one."""
    from sarthak.spaces.roadmap_init import ensure_roadmap
    from sarthak.spaces.store import load_profile

    ws = Path(body.directory).expanduser().resolve()
    profile = load_profile(ws)
    if profile is None:
        raise HTTPException(404, "Space not found. Run spaces/init first.")

    success = await ensure_roadmap(ws, profile, force=True)
    if not success:
        raise HTTPException(
            500,
            "Roadmap generation failed — the AI may be unavailable. Check logs for details.",
        )
    return {"ok": True, "directory": str(ws)}


class RoadmapRefineReq(BaseModel):
    directory: str
    answers: str  # free-form answers to the clarifying questions


@router.post("/api/spaces/refine")
async def refine_space_roadmap(body: RoadmapRefineReq) -> dict:
    """Refine and regenerate the roadmap using user answers to clarifying questions.

    Accepts free-form text answers. Enriches the goal in .spaces.json and
    forces a fresh roadmap generation so the result is tailored to the user's
    actual intent.
    """
    from sarthak.spaces.roadmap_init import refine_roadmap
    from sarthak.spaces.store import load_profile

    ws = Path(body.directory).expanduser().resolve()
    profile = load_profile(ws)
    if profile is None:
        raise HTTPException(404, "Space not found. Run spaces/init first.")

    async def _run_refine() -> None:
        await refine_roadmap(ws, profile, body.answers)

    asyncio.create_task(_run_refine())
    return {"ok": True, "scheduled": True, "directory": str(ws)}


class SpaceDeleteReq(BaseModel):
    directory: str
    name: str


@router.post("/api/spaces/delete")
async def delete_space_api(body: SpaceDeleteReq) -> dict:
    """Move a space to trash (retained 30 days) and remove from active list."""
    from sarthak.spaces.store import list_spaces, trash_space

    ws = Path(body.directory).expanduser().resolve()
    # Confirm name against registry (works even if .spaces.json is missing)
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


class SessionReq(BaseModel):
    directory: str
    reshape: bool = False


@router.post("/api/spaces/session")
async def run_session(body: SessionReq) -> dict:
    from sarthak.spaces.orchestrator import SpacesOrchestrator

    orch = SpacesOrchestrator(Path(body.directory).expanduser().resolve())
    result = await orch.next_session(reshape_workspace=body.reshape)
    return {
        "reply": result.reply,
        "xp_earned": result.xp_earned,
        "workspace_changes": result.workspace_changes or [],
    }


@router.post("/api/spaces/quick")
async def quicktest(body: SessionReq) -> dict:
    from sarthak.spaces.orchestrator import SpacesOrchestrator

    orch = SpacesOrchestrator(Path(body.directory).expanduser().resolve())
    result = await orch.quicktest()
    return {"reply": result.reply}


# RAG legacy endpoints — body takes {directory} instead of URL space param.
# Returns same shape as roadmap router so frontend code is uniform.


@router.post("/api/spaces/rag/index")
async def rag_index_legacy(body: SessionReq) -> dict:
    from sarthak.spaces.rag import index_space

    ws = Path(body.directory).expanduser().resolve()
    count = await index_space(ws)
    return {"chunks_indexed": count, "directory": str(ws)}


@router.get("/api/spaces/rag/status")
async def rag_status_legacy(directory: str) -> dict:
    from sarthak.spaces.rag import rag_status as _status

    return await asyncio.to_thread(_status, Path(directory).expanduser().resolve())


class RagQuery(BaseModel):
    directory: str
    query: str
    top_k: int = 5


@router.post("/api/spaces/rag/search")
async def rag_search_legacy(body: RagQuery) -> dict:
    # Use roadmap/rag.py for structured List[SearchResult] response
    from sarthak.spaces.rag import search_space_structured

    ws = Path(body.directory).expanduser().resolve()
    results = await search_space_structured(ws, body.query, top_k=body.top_k)
    return {"results": [r.to_dict() for r in results]}


class ProfileUpdate(BaseModel):
    directory: str
    background: str = ""
    goal: str = ""
    name: str = ""


@router.post("/api/spaces/profile")
async def update_profile(body: ProfileUpdate) -> dict:
    from sarthak.spaces.orchestrator import SpacesOrchestrator

    orch = SpacesOrchestrator(Path(body.directory).expanduser().resolve())
    kwargs = {
        k: v
        for k, v in [
            ("background", body.background),
            ("goal", body.goal),
            ("name", body.name),
        ]
        if v
    }
    if not kwargs:
        raise HTTPException(400, "Provide at least one field to update")
    orch.update_learner(**kwargs)
    return {"status": orch.get_status()}


# ── Session end endpoint ──────────────────────────────────────────────────────


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
        "reply": result.reply,
        "xp_earned": result.xp_earned,
        "optimizations": [o.model_dump() for o in (result.optimizations or [])],
        "badges_earned": result.badges_earned,
    }


# ── Practice test endpoints ───────────────────────────────────────────────────


class PracticeGenerateReq(BaseModel):
    directory: str = ""  # optional — resolved from space_id if omitted
    test_type: str = "concept"
    scope: str = ""
    source: str = "llm"
    source_prompt: str = ""
    seconds_per_question: int = 120
    n_questions: int | None = None


@router.post("/api/spaces/{space_id}/practice/generate")
async def practice_generate_api(space_id: str, body: PracticeGenerateReq) -> dict:
    from sarthak.spaces.orchestrator import SpacesOrchestrator

    ws = resolve_space_dir(space_id, body.directory)
    orch = SpacesOrchestrator(ws)
    profile = orch._load_or_init()
    ctx = orch._build_ctx(profile)
    test = await orch._practice.create_test(
        ctx,
        test_type=body.test_type,
        scope=body.scope,
        source=body.source,
        source_prompt=body.source_prompt,
        seconds_per_question=body.seconds_per_question,
        n_questions=body.n_questions,
    )
    return test.model_dump()


class PracticeGradeReq(BaseModel):
    directory: str = ""  # optional — resolved from space_id if omitted
    test_id: str
    answers: dict[str, str] = {}
    time_taken: dict[str, int] = {}


@router.post("/api/spaces/{space_id}/practice/grade")
async def practice_grade_api(space_id: str, body: PracticeGradeReq) -> dict:
    from sarthak.spaces.practice import PracticeEngine
    from sarthak.spaces.models import PracticeTest

    space_dir = resolve_space_dir(space_id, body.directory)
    # Load saved test from .spaces/tests.jsonl
    tests_file = space_dir / ".spaces" / "tests.jsonl"
    if not tests_file.exists():
        raise HTTPException(404, "No tests found")

    test = None
    for line in tests_file.read_text().splitlines():
        try:
            t = PracticeTest.model_validate_json(line)
            if t.test_id == body.test_id:
                test = t
                break  # early-exit once found
        except Exception:
            pass
    if not test:
        raise HTTPException(404, f"Test {body.test_id} not found")

    engine = PracticeEngine()
    result = await engine.grade_test(test, body.answers, body.time_taken)

    # Record graded test to activity store
    try:
        from sarthak.storage.activity_store import write_activity
        await write_activity(
            activity_type="practice_test",
            space_dir=str(space_dir),
            concept_id=test.scope,
            concept_title=test.scope,
            content_text="\n".join(
                f"Q: {q.question}\nA: {body.answers.get(q.question_id,'')}"
                for q in test.questions
            )[:4096],
            metadata={
                "test_id": result.test_id,
                "percent": result.percent,
                "passed": result.passed,
                "weak": result.weak_concepts,
                "strong": result.strong_concepts,
                "time_taken": body.time_taken,
            },
        )
    except Exception:
        pass

    return result.model_dump()


class DigestSubscribeReq(BaseModel):
    subscribed: bool


@router.post("/api/spaces/{space_id}/digest/subscribe")
async def digest_subscribe_api(space_id: str, body: DigestSubscribeReq) -> dict:
    """Persist digest subscription preference in .spaces.json."""
    from sarthak.spaces.store import update_space

    match = get_space_or_404(space_id)
    update_space({"digest_subscribed": body.subscribed}, Path(match["directory"]))
    return {"ok": True, "subscribed": body.subscribed}


@router.get("/api/spaces/{space_id}/digest/subscribe")
async def digest_subscribe_status_api(space_id: str) -> dict:
    """Return current digest subscription status."""
    from sarthak.spaces.store import load_space

    match = get_space_or_404(space_id)
    ws = load_space(Path(match["directory"])) or {}
    return {"subscribed": bool(ws.get("digest_subscribed", False))}


# ── Optimize endpoint ─────────────────────────────────────────────────────────


@router.get("/api/spaces/{space_id}/optimize")
async def optimize_api(space_id: str, recent_n: int = 10) -> list[dict]:
    from sarthak.spaces.learner_context import build_learner_context
    from sarthak.spaces.optimizer import SignalOptimizer
    from sarthak.spaces.store import load_profile

    match = get_space_or_404(space_id)

    ws_dir = Path(match["directory"])
    profile = load_profile(ws_dir)
    if not profile:
        return []

    lc = await build_learner_context(ws_dir, profile, days=recent_n * 2)
    optimizer = SignalOptimizer()
    opts = optimizer.analyze_from_context(ws_dir, profile, lc)
    return [o.model_dump() for o in opts]


@router.get("/api/spaces/{space_id}/profile")
async def space_profile_api(space_id: str) -> dict:
    """Return full structured SpaceProfile fields — used by SpaceHome hero stats."""
    from sarthak.spaces.models import LEVEL_LABELS, XP_THRESHOLDS
    from sarthak.spaces.store import load_profile

    match = get_space_or_404(space_id)

    profile = load_profile(Path(match["directory"]))
    if not profile:
        return {"directory": match["directory"], "name": match.get("name", "")}

    return _profile_payload(match, profile)


@router.get("/api/spaces/profiles")
async def space_profiles_api() -> list[dict]:
    """Batch profile summary for all spaces (avoids N+1)."""
    from sarthak.spaces.store import list_spaces, load_profile

    spaces = list_spaces()
    async def _one(s: dict) -> dict:
        d = s.get("directory", "")
        if not d:
            return {"directory": "", "name": s.get("name", "")}
        try:
            prof = await asyncio.to_thread(load_profile, Path(d))
        except Exception:
            prof = None
        if prof:
            return _profile_payload(s, prof)
        return {"directory": d, "name": s.get("name", "")}

    return await asyncio.gather(*[_one(s) for s in spaces])


def _profile_payload(match: dict, profile) -> dict:
    from sarthak.spaces.models import LEVEL_LABELS, XP_THRESHOLDS
    lr = profile.learner
    threshold = XP_THRESHOLDS.get(lr.skill_level, 9999)
    return {
        "directory": match.get("directory", ""),
        "name": match.get("name", ""),
        "domain": profile.domain,
        "space_type": profile.space_type.value,
        "xp": lr.xp,
        "xp_to_next": max(0, threshold - lr.xp),
        "streak_days": lr.streak_days,
        "session_count": lr.total_sessions,
        "level": LEVEL_LABELS.get(lr.skill_level, lr.skill_level.value),
        "skill_level": lr.skill_level.value,
        "mastered_count": len(lr.mastered_concepts),
        "mastered_concepts": lr.mastered_concepts[-10:],
        "struggling_concepts": lr.struggling_concepts[:5],
        "badges": lr.badges,
        "goal": lr.goal,
        "background": lr.background,
        "rag_enabled": profile.rag_enabled,
    }


class SpaceSettingsUpdate(BaseModel):
    goal: str | None = None
    background: str | None = None
    domain_name: str | None = None
    rag_enabled: bool | None = None
    llm_context: str | None = None       # stored in .spaces/llm_context.md
    soul_md: str | None = None           # stored in .spaces/SOUL.md
    memory_md: str | None = None         # stored in .spaces/MEMORY.md
    # Learner profile fields
    preferred_style: str | None = None
    daily_goal_minutes: int | None = None
    is_technical: bool | None = None
    mastered_concepts: list[str] | None = None
    struggling_concepts: list[str] | None = None
    badges: list[str] | None = None


@router.get("/api/spaces/{space_id}/overview")
async def get_space_overview(space_id: str) -> dict:
    """Return just the space overview JSON (generated alongside the roadmap)."""
    import json as _json
    match = get_space_or_404(space_id)
    overview_path = Path(match["directory"]) / ".spaces" / "overview.json"
    if overview_path.exists():
        try:
            return _json.loads(overview_path.read_text(encoding="utf-8"))
        except Exception:
            pass
    return {}


@router.get("/api/spaces/{space_id}/settings")
async def get_space_settings(space_id: str) -> dict:
    """Return all configuration, markdown files, identity and LLM context for a space."""
    from sarthak.spaces.store import load_profile, load_space

    match = get_space_or_404(space_id)

    ws_dir = Path(match["directory"])
    profile = load_profile(ws_dir)
    ws = load_space(ws_dir) or {}

    # Read all editable .spaces/ markdown files
    spaces_dir = ws_dir / ".spaces"
    md_files: dict[str, str] = {}
    for fname in ["SOUL.md", "USER.md", "HEARTBEAT.md", "MEMORY.md",
                  "llm_context.md", "Optimal_Learn.md", "directory_structure.md"]:
        p = spaces_dir / fname
        if p.exists():
            md_files[fname] = p.read_text(encoding="utf-8")

    # Load overview.json if it exists
    import json as _json
    overview_data: dict = {}
    overview_path = spaces_dir / "overview.json"
    if overview_path.exists():
        try:
            overview_data = _json.loads(overview_path.read_text(encoding="utf-8"))
        except Exception:
            pass

    lr = profile.learner if profile else None
    return {
        "directory": str(ws_dir),
        "name": match.get("name", ""),
        "domain": profile.domain if profile else "",
        "space_type": profile.space_type.value if profile else "custom",
        "goal": lr.goal if lr else ws.get("goal", ""),
        "background": lr.background if lr else "",
        "rag_enabled": profile.rag_enabled if profile else False,
        "tags": ws.get("tags", []),
        "description": ws.get("description", ""),
        "llm_context": md_files.get("llm_context.md", ""),
        "soul_md": md_files.get("SOUL.md", ""),
        "memory_md": md_files.get("MEMORY.md", ""),
        "user_md": md_files.get("USER.md", ""),
        "heartbeat_md": md_files.get("HEARTBEAT.md", ""),
        "md_files": md_files,
        "preferred_tools": ws.get("preferred_tools", []),
        # Learner profile fields for editing
        "preferred_style": lr.preferred_style if lr else "visual + hands-on",
        "daily_goal_minutes": lr.daily_goal_minutes if lr else 30,
        "is_technical": lr.is_technical if lr else False,
        "skill_level": lr.skill_level.value if lr else "novice",
        "xp": lr.xp if lr else 0,
        "streak_days": lr.streak_days if lr else 0,
        "total_sessions": lr.total_sessions if lr else 0,
        "mastered_concepts": lr.mastered_concepts if lr else [],
        "struggling_concepts": lr.struggling_concepts if lr else [],
        "badges": lr.badges if lr else [],
        "overview": overview_data,
    }


@router.patch("/api/spaces/{space_id}/settings")
async def update_space_settings(space_id: str, body: SpaceSettingsUpdate) -> dict:
    """Update space configuration and persist."""
    from sarthak.spaces.store import load_profile, save_profile, update_space

    match = get_space_or_404(space_id)

    ws_dir = Path(match["directory"])
    profile = load_profile(ws_dir)
    spaces_dir = ws_dir / ".spaces"
    spaces_dir.mkdir(exist_ok=True)

    if profile:
        if body.goal is not None:
            profile.learner.goal = body.goal
        if body.background is not None:
            profile.learner.background = body.background
        if body.domain_name is not None:
            profile.domain = body.domain_name
        if body.rag_enabled is not None:
            profile.rag_enabled = body.rag_enabled
        if body.preferred_style is not None:
            profile.learner.preferred_style = body.preferred_style
        if body.daily_goal_minutes is not None:
            profile.learner.daily_goal_minutes = body.daily_goal_minutes
        if body.is_technical is not None:
            profile.learner.is_technical = body.is_technical
        if body.mastered_concepts is not None:
            profile.learner.mastered_concepts = body.mastered_concepts
        if body.struggling_concepts is not None:
            profile.learner.struggling_concepts = body.struggling_concepts
        if body.badges is not None:
            profile.learner.badges = body.badges
        await asyncio.to_thread(save_profile, ws_dir, profile)

    if body.llm_context is not None:
        (spaces_dir / "llm_context.md").write_text(body.llm_context, encoding="utf-8")
    if body.soul_md is not None:
        (spaces_dir / "SOUL.md").write_text(body.soul_md, encoding="utf-8")
    if body.memory_md is not None:
        (spaces_dir / "MEMORY.md").write_text(body.memory_md, encoding="utf-8")

    patch = {}
    if body.goal is not None:
        patch["goal"] = body.goal
    if body.domain_name is not None:
        patch["name"] = body.domain_name
    if patch:
        update_space(patch, ws_dir)

    return {"ok": True}


@router.get("/api/spaces/{space_id}/status")
async def space_status_api(space_id: str) -> dict:
    from sarthak.spaces.models import LEVEL_LABELS, XP_THRESHOLDS
    from sarthak.spaces.orchestrator import SpacesOrchestrator
    from sarthak.spaces.store import load_profile

    match = get_space_or_404(space_id)
    orch = SpacesOrchestrator(Path(match["directory"]))
    profile = load_profile(Path(match["directory"]))
    profile_data = {}
    if profile:
        lr = profile.learner
        threshold = XP_THRESHOLDS.get(lr.skill_level, 9999)
        profile_data = {
            "xp": lr.xp,
            "xp_to_next": max(0, threshold - lr.xp),
            "streak_days": lr.streak_days,
            "session_count": lr.total_sessions,
            "level": LEVEL_LABELS.get(lr.skill_level, lr.skill_level.value),
            "domain": profile.domain,
            "mastered_count": len(lr.mastered_concepts),
            "badges": lr.badges,
        }
    return {"status": orch.get_status(), **match, **profile_data}


# ── Files: chat with file content ───────────────────────────────────────────


class FileChatReq(BaseModel):
    path: str  # relative to space directory
    question: str
    history: list[dict[str, str]] = []  # [{"role": "user"|"assistant", "content": str}]
    max_context_chars: int = 12_000


@router.post("/api/spaces/{space_id}/files/chat")
async def chat_with_file_api(space_id: str, body: FileChatReq) -> dict:
    from sarthak.spaces.rag import chat_with_file

    match = get_space_or_404(space_id)

    ws_dir = Path(match["directory"])
    file_path = (ws_dir / body.path).resolve()
    if not str(file_path).startswith(str(ws_dir.resolve())):
        raise HTTPException(400, "Invalid path")
    if not file_path.exists():
        raise HTTPException(404, "File not found")

    reply = await chat_with_file(
        file_path,
        body.question,
        history=body.history or None,
        max_context_chars=body.max_context_chars,
    )
    return {"reply": reply, "file": body.path}


# ── Files: open in native app ───────────────────────────────────────────────


class FileOpenReq(BaseModel):
    path: str


@router.post("/api/spaces/{space_id}/files/open")
async def open_file_native(space_id: str, body: FileOpenReq) -> dict:
    import subprocess
    import sys

    match = get_space_or_404(space_id)

    ws_dir = Path(match["directory"])
    file_path = (ws_dir / body.path).resolve()

    # Prevent path traversal outside the workspace
    if not str(file_path).startswith(str(ws_dir.resolve())):
        raise HTTPException(400, "Invalid path")

    if not file_path.exists():
        raise HTTPException(404, "File not found")

    try:
        if sys.platform == "darwin":
            subprocess.Popen(["open", str(file_path)])
        elif sys.platform == "win32":
            import os as _os

            _os.startfile(str(file_path))
        else:
            subprocess.Popen(["xdg-open", str(file_path)])
        return {"ok": True, "path": str(file_path)}
    except Exception as exc:
        raise HTTPException(500, str(exc))


# ── Space RAG endpoints ─────────────────────────────────────────────────────


@router.get("/api/spaces/{space_id}/rag/walk")
async def space_rag_walk(space_id: str) -> dict:
    from sarthak.spaces.rag import rag_status, walk_space

    ws = resolve_space_dir(space_id)
    files = walk_space(ws)
    st = rag_status(ws)
    return {
        "files": files,
        "total_files": len(files),
        "indexed_files": st.get("indexed_files", 0),
        "indexed_chunks": st.get("indexed_chunks", 0),
    }


@router.get("/api/spaces/{space_id}/rag/files")
async def space_rag_files(space_id: str) -> dict:
    from sarthak.spaces.rag import list_indexed_files, rag_status

    ws = resolve_space_dir(space_id)
    st = rag_status(ws)
    return {
        "files": [{"path": p} for p in list_indexed_files(ws)],
        "indexed_files": st.get("indexed_files", 0),
        "indexed_chunks": st.get("indexed_chunks", 0),
    }


class RagIndexPathsReq(BaseModel):
    paths: list[str]
    pipeline: str = "text"


@router.post("/api/spaces/{space_id}/rag/index-paths/stream")
async def space_rag_index_stream(space_id: str, body: RagIndexPathsReq):
    from sarthak.spaces.rag import index_paths_streaming

    ws = resolve_space_dir(space_id)
    return StreamingResponse(
        index_paths_streaming(ws, body.paths, pipeline=body.pipeline),
        media_type="text/event-stream",
    )


@router.post("/api/spaces/{space_id}/rag/export-activities")
async def space_rag_export_activities(space_id: str) -> dict:
    from sarthak.spaces.rag import export_activities_to_markdown

    ws = resolve_space_dir(space_id)
    written = await export_activities_to_markdown(ws)
    return {"written": len(written), "paths": written}


@router.post("/api/spaces/{space_id}/rag/upload")
async def space_rag_upload(
    space_id: str,
    pipeline: str = "text",
    file: UploadFile = File(...),
) -> dict:
    from sarthak.spaces.rag import index_paths, rag_status

    ws = resolve_space_dir(space_id)

    # Sanitise filename — prevent path traversal
    filename = Path(file.filename).name if file.filename else "upload"
    dest = ws / filename
    dest.write_bytes(await file.read())

    count = await index_paths(ws, [filename], pipeline=pipeline)
    st = rag_status(ws)
    return {
        "chunks_indexed": count,
        "indexed_files": st.get("indexed_files", 0),
        "indexed_chunks": st.get("indexed_chunks", 0),
    }


class SpaceRagQuery(BaseModel):
    query: str
    top_k: int = 5


@router.post("/api/spaces/{space_id}/rag/search")
async def space_rag_search(space_id: str, body: SpaceRagQuery) -> dict:
    from sarthak.spaces.rag import search_space_structured

    ws = resolve_space_dir(space_id)
    try:
        results = await search_space_structured(ws, body.query, top_k=body.top_k)
        return {"results": [r.to_dict() for r in results]}
    except Exception as exc:
        msg = str(exc)
        if "not configured" in msg.lower() or "embedding" in msg.lower() or "api key" in msg.lower():
            raise HTTPException(status_code=400, detail=f"RAG embeddings not configured: {msg}")
        if "not indexed" in msg.lower():
            raise HTTPException(status_code=400, detail="Space not indexed yet. Use 'Index all files' first.")
        raise HTTPException(status_code=500, detail=msg)


@router.get("/api/spaces/{space_id}/rag/status")
async def space_rag_status(space_id: str) -> dict:
    from sarthak.spaces.rag import rag_status

    ws = resolve_space_dir(space_id)
    return await asyncio.to_thread(rag_status, ws)


class RagChatReq(BaseModel):
    question: str
    history: list[dict] = []
    top_k: int = 5


@router.post("/api/spaces/{space_id}/rag/chat")
async def space_rag_chat(space_id: str, body: RagChatReq) -> dict:
    from sarthak.spaces.rag import search_space_structured
    from sarthak.core.ai_utils.multi_provider import call_llm

    ws = resolve_space_dir(space_id)
    try:
        results = await search_space_structured(ws, body.question, top_k=body.top_k)
    except Exception as exc:
        msg = str(exc)
        if "not configured" in msg.lower() or "embedding" in msg.lower() or "api key" in msg.lower():
            raise HTTPException(status_code=400, detail=f"RAG embeddings not configured: {msg}")
        raise HTTPException(status_code=500, detail=msg)

    if not results:
        context = "No relevant content found in the indexed workspace files."
    else:
        context = "\n\n---\n\n".join(
            f"[{r.source}:{r.line}]\n{r.text.strip()}" for r in results
        )

    history_text = ""
    for turn in body.history:
        role = turn.get("role", "")
        content = turn.get("content", "")
        if role == "user":
            history_text += f"\n\nUser: {content}"
        elif role == "assistant":
            history_text += f"\n\nAssistant: {content}"

    prompt = (
        "You are a knowledgeable assistant. Answer the user's question using ONLY "
        "the workspace file excerpts provided below. Cite file:line references when relevant. "
        "If the answer is not in the excerpts, say so.\n\n"
        f"=== WORKSPACE CONTEXT ===\n{context}\n=== END CONTEXT ==="
        f"{history_text}\n\nUser: {body.question}\n\nAssistant:"
    )

    answer = await call_llm(prompt)
    sources = [{"source": r.source, "line": r.line, "score": round(1 - r.distance, 3)} for r in results]
    return {"answer": answer, "sources": sources}


# ── Workspace Insights (Optimal_Learn.md) ───────────────────────────────────────

@router.get("/api/spaces/{space_id}/workspace/insights")
async def workspace_insights(space_id: str, refresh: bool = False) -> dict:
    """
    Return the latest Optimal_Learn.md content for this space.
    If refresh=true, re-runs WorkspaceAnalyserAgent first.
    Also returns recommendations.md if it exists.
    """
    ws = resolve_space_dir(space_id)
    spaces_dir = ws / ".spaces"

    if refresh:
        from sarthak.spaces.store import load_profile
        from sarthak.spaces.models import SpaceContext
        from sarthak.spaces.agents import WorkspaceAnalyserAgent, detect_platform
        profile = await asyncio.to_thread(load_profile, ws)
        if not profile:
            raise HTTPException(status_code=404, detail="Space profile not found")
        ctx = SpaceContext(workspace_dir=str(ws), profile=profile, platform=detect_platform())
        analyser = WorkspaceAnalyserAgent()
        content = await analyser.analyse(ctx)
        await asyncio.to_thread(analyser.write_optimal_learn, ws, content)
    else:
        optimal = spaces_dir / "Optimal_Learn.md"
        content = optimal.read_text(encoding="utf-8") if optimal.exists() else None

    recs_file = spaces_dir / "recommendations.md"
    recommendations = recs_file.read_text(encoding="utf-8") if recs_file.exists() else None

    return {
        "content": content,
        "recommendations": recommendations,
        "has_content": bool(content),
    }


# ── Workspace Q&A (pydantic-ai agent with tools) ─────────────────────────────

class WorkspaceQAReq(BaseModel):
    question: str
    history: list[dict] = []


@router.post("/api/spaces/{space_id}/workspace/qa")
async def workspace_qa(space_id: str, body: WorkspaceQAReq) -> StreamingResponse:
    """
    Agent-based workspace Q&A. Uses pydantic-ai agent with workspace tools:
    - SQL queries on sarthak.db
    - Notes search
    - RAG search on indexed files
    - Session/SRS/concept/activity data
    - Optimal_Learn.md / recommendations
    Streams SSE tokens.
    """
    ws = resolve_space_dir(space_id)

    async def _generate():
        try:
            from sarthak.spaces.workspace_qa import answer_workspace_question
            answer = await answer_workspace_question(ws, body.question)
            # Stream as SSE
            import json
            # Stream in chunks for responsiveness
            chunk_size = 80
            for i in range(0, len(answer), chunk_size):
                chunk = answer[i:i + chunk_size]
                yield f"data: {json.dumps({'delta': chunk})}\n\n"
            yield "data: [DONE]\n\n"
        except Exception as exc:
            import json
            yield f"data: {json.dumps({'error': str(exc)})}\n\n"
            yield "data: [DONE]\n\n"

    return StreamingResponse(
        _generate(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )
