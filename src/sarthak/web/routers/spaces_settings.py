"""
spaces_settings.py — Space profile, settings, overview and workspace endpoints.

Routes:
  GET/PATCH /api/spaces/{space_id}/settings
  GET       /api/spaces/{space_id}/overview
  GET       /api/spaces/{space_id}/profile
  GET       /api/spaces/profiles
  GET       /api/spaces/{space_id}/status
  GET       /api/spaces/{space_id}/optimize
  POST      /api/spaces/{space_id}/digest/subscribe
  GET       /api/spaces/{space_id}/digest/subscribe
  GET       /api/spaces/{space_id}/workspace/insights
  POST      /api/spaces/{space_id}/workspace/qa
  POST      /api/spaces/{space_id}/files/chat
  POST      /api/spaces/{space_id}/files/open
"""
from __future__ import annotations

import asyncio
import json
from pathlib import Path

from fastapi import APIRouter, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from sarthak.web.routers.helpers import get_space_or_404, resolve_space_dir, SpaceEntry

router = APIRouter()

# ── Shared helper ─────────────────────────────────────────────────────────────

def _profile_payload(match: dict, profile) -> dict:
    """Serialise a SpaceProfile into the standard API response shape."""
    from sarthak.spaces.models import LEVEL_LABELS, XP_THRESHOLDS
    lr = profile.learner
    threshold = XP_THRESHOLDS.get(lr.skill_level, 9999)
    return {
        "directory":          match.get("directory", ""),
        "name":               match.get("name", ""),
        "domain":             profile.domain,
        "space_type":         profile.space_type.value,
        "xp":                 lr.xp,
        "xp_to_next":         max(0, threshold - lr.xp),
        "streak_days":        lr.streak_days,
        "session_count":      lr.total_sessions,
        "level":              LEVEL_LABELS.get(lr.skill_level, lr.skill_level.value),
        "skill_level":        lr.skill_level.value,
        "mastered_count":     len(lr.mastered_concepts),
        "mastered_concepts":  lr.mastered_concepts[-10:],
        "struggling_concepts": lr.struggling_concepts[:5],
        "badges":             lr.badges,
        "goal":               lr.goal,
        "background":         lr.background,
        "rag_enabled":        profile.rag_enabled,
    }


# ── Profile endpoints ─────────────────────────────────────────────────────────

@router.get("/api/spaces/{space_id}/profile")
async def space_profile_api(space_id: str) -> dict:
    """Full SpaceProfile fields — used by SpaceHome hero stats."""
    from sarthak.spaces.store import load_profile
    match = get_space_or_404(space_id)
    profile = load_profile(Path(match["directory"]))
    if not profile:
        return {"directory": match["directory"], "name": match.get("name", "")}
    return _profile_payload(match, profile)


@router.get("/api/spaces/profiles")
async def space_profiles_api() -> list[dict]:
    """Batch profile summary for all spaces (bounded concurrency to avoid N+1 spikes)."""
    from sarthak.spaces.store import list_spaces, load_profile

    spaces = list_spaces()
    sem = asyncio.Semaphore(10)  # cap concurrent disk reads

    async def _one(s: dict) -> dict:
        d = s.get("directory", "")
        if not d:
            return {"directory": "", "name": s.get("name", "")}
        async with sem:
            try:
                prof = await asyncio.to_thread(load_profile, Path(d))
            except Exception:
                prof = None
        return _profile_payload(s, prof) if prof else {"directory": d, "name": s.get("name", "")}

    return list(await asyncio.gather(*(_one(s) for s in spaces)))


# ── Status endpoint ───────────────────────────────────────────────────────────

@router.get("/api/spaces/{space_id}/status")
async def space_status_api(space_id: str) -> dict:
    from sarthak.spaces.models import LEVEL_LABELS, XP_THRESHOLDS
    from sarthak.spaces.orchestrator import SpacesOrchestrator
    from sarthak.spaces.store import load_profile
    match = get_space_or_404(space_id)
    orch = SpacesOrchestrator(Path(match["directory"]))
    profile = load_profile(Path(match["directory"]))
    profile_data: dict = {}
    if profile:
        lr = profile.learner
        threshold = XP_THRESHOLDS.get(lr.skill_level, 9999)
        profile_data = {
            "xp":           lr.xp,
            "xp_to_next":   max(0, threshold - lr.xp),
            "streak_days":  lr.streak_days,
            "session_count": lr.total_sessions,
            "level":        LEVEL_LABELS.get(lr.skill_level, lr.skill_level.value),
            "domain":       profile.domain,
            "mastered_count": len(lr.mastered_concepts),
            "badges":       lr.badges,
        }
    return {"status": orch.get_status(), **match, **profile_data}


# ── Settings endpoints ────────────────────────────────────────────────────────

class SpaceSettingsUpdate(BaseModel):
    goal: str | None = None
    background: str | None = None
    domain_name: str | None = None
    rag_enabled: bool | None = None
    llm_context: str | None = None
    soul_md: str | None = None
    memory_md: str | None = None
    preferred_style: str | None = None
    daily_goal_minutes: int | None = None
    is_technical: bool | None = None
    mastered_concepts: list[str] | None = None
    struggling_concepts: list[str] | None = None
    badges: list[str] | None = None


@router.get("/api/spaces/{space_id}/settings")
async def get_space_settings(space_id: str) -> dict:
    from sarthak.spaces.store import load_profile, load_space
    match = get_space_or_404(space_id)
    ws_dir = Path(match["directory"])
    profile = load_profile(ws_dir)
    ws = load_space(ws_dir) or {}
    spaces_dir = ws_dir / ".spaces"

    md_files: dict[str, str] = {}
    for fname in ["SOUL.md", "USER.md", "HEARTBEAT.md", "MEMORY.md",
                  "llm_context.md", "Optimal_Learn.md", "directory_structure.md"]:
        p = spaces_dir / fname
        if p.exists():
            md_files[fname] = p.read_text(encoding="utf-8")

    overview_data: dict = {}
    overview_path = spaces_dir / "overview.json"
    if overview_path.exists():
        try:
            overview_data = json.loads(overview_path.read_text(encoding="utf-8"))
        except Exception:
            pass

    lr = profile.learner if profile else None
    return {
        "directory":       str(ws_dir),
        "name":            match.get("name", ""),
        "domain":          profile.domain if profile else "",
        "space_type":      profile.space_type.value if profile else "custom",
        "goal":            lr.goal if lr else ws.get("goal", ""),
        "background":      lr.background if lr else "",
        "rag_enabled":     profile.rag_enabled if profile else False,
        "tags":            ws.get("tags", []),
        "description":     ws.get("description", ""),
        "llm_context":     md_files.get("llm_context.md", ""),
        "soul_md":         md_files.get("SOUL.md", ""),
        "memory_md":       md_files.get("MEMORY.md", ""),
        "user_md":         md_files.get("USER.md", ""),
        "heartbeat_md":    md_files.get("HEARTBEAT.md", ""),
        "md_files":        md_files,
        "preferred_tools": ws.get("preferred_tools", []),
        "preferred_style": lr.preferred_style if lr else "visual + hands-on",
        "daily_goal_minutes": lr.daily_goal_minutes if lr else 30,
        "is_technical":    lr.is_technical if lr else False,
        "skill_level":     lr.skill_level.value if lr else "novice",
        "xp":              lr.xp if lr else 0,
        "streak_days":     lr.streak_days if lr else 0,
        "total_sessions":  lr.total_sessions if lr else 0,
        "mastered_concepts":   lr.mastered_concepts if lr else [],
        "struggling_concepts": lr.struggling_concepts if lr else [],
        "badges":          lr.badges if lr else [],
        "overview":        overview_data,
    }


@router.patch("/api/spaces/{space_id}/settings")
async def update_space_settings(space_id: str, body: SpaceSettingsUpdate) -> dict:
    from sarthak.spaces.store import load_profile, save_profile, update_space
    match = get_space_or_404(space_id)
    ws_dir = Path(match["directory"])
    profile = load_profile(ws_dir)
    spaces_dir = ws_dir / ".spaces"
    spaces_dir.mkdir(exist_ok=True)

    if profile:
        fields = {
            "goal": body.goal, "background": body.background,
            "preferred_style": body.preferred_style,
            "daily_goal_minutes": body.daily_goal_minutes,
            "is_technical": body.is_technical,
            "mastered_concepts": body.mastered_concepts,
            "struggling_concepts": body.struggling_concepts,
            "badges": body.badges,
        }
        for attr, val in fields.items():
            if val is not None:
                setattr(profile.learner, attr, val)
        if body.domain_name is not None:
            profile.domain = body.domain_name
        if body.rag_enabled is not None:
            profile.rag_enabled = body.rag_enabled
        await asyncio.to_thread(save_profile, ws_dir, profile)

    for fname, content in [("llm_context.md", body.llm_context),
                            ("SOUL.md", body.soul_md),
                            ("MEMORY.md", body.memory_md)]:
        if content is not None:
            (spaces_dir / fname).write_text(content, encoding="utf-8")

    patch: dict = {}
    if body.goal is not None:
        patch["goal"] = body.goal
    if body.domain_name is not None:
        patch["name"] = body.domain_name
    if patch:
        update_space(patch, ws_dir)
    return {"ok": True}


# ── Overview endpoint ─────────────────────────────────────────────────────────

@router.get("/api/spaces/{space_id}/overview")
async def get_space_overview(space_id: str) -> dict:
    match = get_space_or_404(space_id)
    spaces_dir = Path(match["directory"]) / ".spaces"
    status_path = spaces_dir / "roadmap_status.json"
    status = "pending"
    if status_path.exists():
        try:
            status = json.loads(status_path.read_text(encoding="utf-8")).get("status", "pending")
        except Exception:
            pass
    overview_path = spaces_dir / "overview.json"
    if overview_path.exists():
        try:
            data = json.loads(overview_path.read_text(encoding="utf-8"))
            data["roadmap_status"] = status
            return data
        except Exception:
            pass
    return {"roadmap_status": status}


@router.get("/api/spaces/{space_id}/roadmap-status")
async def get_roadmap_status(space_id: str) -> dict:
    """Lightweight endpoint to poll roadmap generation status without waiting for overview."""
    match = get_space_or_404(space_id)
    status_path = Path(match["directory"]) / ".spaces" / "roadmap_status.json"
    if status_path.exists():
        try:
            return json.loads(status_path.read_text(encoding="utf-8"))
        except Exception:
            pass
    return {"status": "pending", "error": ""}


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


# ── Digest subscription ───────────────────────────────────────────────────────

class DigestSubscribeReq(BaseModel):
    subscribed: bool


@router.post("/api/spaces/{space_id}/digest/subscribe")
async def digest_subscribe_api(space_id: str, body: DigestSubscribeReq) -> dict:
    from sarthak.spaces.store import update_space
    match = get_space_or_404(space_id)
    update_space({"digest_subscribed": body.subscribed}, Path(match["directory"]))
    return {"ok": True, "subscribed": body.subscribed}


@router.get("/api/spaces/{space_id}/digest/subscribe")
async def digest_subscribe_status_api(space_id: str) -> dict:
    from sarthak.spaces.store import load_space
    match = get_space_or_404(space_id)
    ws = load_space(Path(match["directory"])) or {}
    return {"subscribed": bool(ws.get("digest_subscribed", False))}


# ── Workspace insights (Optimal_Learn.md) ────────────────────────────────────

@router.get("/api/spaces/{space_id}/workspace/insights")
async def workspace_insights(space_id: str, refresh: bool = False) -> dict:
    ws = resolve_space_dir(space_id)
    spaces_dir = ws / ".spaces"
    if refresh:
        from sarthak.spaces.store import load_profile
        from sarthak.spaces.models import SpaceContext
        from sarthak.spaces.agents import WorkspaceAnalyserAgent, detect_platform
        profile = await asyncio.to_thread(load_profile, ws)
        if not profile:
            raise HTTPException(404, "Space profile not found")
        ctx = SpaceContext(workspace_dir=str(ws), profile=profile, platform=detect_platform())
        analyser = WorkspaceAnalyserAgent()
        content = await analyser.analyse(ctx)
        await asyncio.to_thread(analyser.write_optimal_learn, ws, content)
    else:
        optimal = spaces_dir / "Optimal_Learn.md"
        content = optimal.read_text(encoding="utf-8") if optimal.exists() else None

    recs_file = spaces_dir / "recommendations.md"
    recommendations = recs_file.read_text(encoding="utf-8") if recs_file.exists() else None
    return {"content": content, "recommendations": recommendations, "has_content": bool(content)}


# ── Workspace Q&A ─────────────────────────────────────────────────────────────

class WorkspaceQAReq(BaseModel):
    question: str
    history: list[dict] = []


@router.post("/api/spaces/{space_id}/workspace/qa")
async def workspace_qa(space_id: str, body: WorkspaceQAReq) -> StreamingResponse:
    """Agent-based Q&A with workspace tools. Streams SSE tokens."""
    ws = resolve_space_dir(space_id)

    async def _generate():
        import json as _json
        try:
            from sarthak.spaces.workspace_qa import answer_workspace_question
            answer = await answer_workspace_question(ws, body.question)
            chunk_size = 80
            for i in range(0, len(answer), chunk_size):
                yield f"data: {_json.dumps({'delta': answer[i:i + chunk_size]})}\n\n"
        except Exception as exc:
            yield f"data: {_json.dumps({'error': str(exc)})}\n\n"
        finally:
            yield "data: [DONE]\n\n"

    return StreamingResponse(
        _generate(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


# ── File operations ───────────────────────────────────────────────────────────

class FileChatReq(BaseModel):
    path: str
    question: str
    history: list[dict[str, str]] = []
    max_context_chars: int = 12_000


@router.post("/api/spaces/{space_id}/files/chat")
async def chat_with_file_api(space_id: str, body: FileChatReq) -> dict:
    from sarthak.spaces.rag import chat_with_file
    match = get_space_or_404(space_id)
    ws_dir = Path(match["directory"])
    file_path = (ws_dir / body.path).resolve()
    # Prevent path traversal — requires Python 3.9+
    if not file_path.is_relative_to(ws_dir.resolve()):
        raise HTTPException(400, "Invalid path: outside workspace")
    if not file_path.exists():
        raise HTTPException(404, "File not found")
    reply = await chat_with_file(
        file_path, body.question, history=body.history or None,
        max_context_chars=body.max_context_chars,
    )
    return {"reply": reply, "file": body.path}


class FileOpenReq(BaseModel):
    path: str


@router.post("/api/spaces/{space_id}/files/open")
async def open_file_native(space_id: str, body: FileOpenReq) -> dict:
    import subprocess
    import sys
    match = get_space_or_404(space_id)
    ws_dir = Path(match["directory"])
    file_path = (ws_dir / body.path).resolve()
    if not file_path.is_relative_to(ws_dir.resolve()):
        raise HTTPException(400, "Invalid path: outside workspace")
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
