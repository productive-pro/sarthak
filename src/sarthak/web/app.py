"""
Sarthak Web — FastAPI backend.

Route ordering is critical:
  Fixed-path routes (/api/spaces/init, /api/spaces/rag/*, etc.) MUST be
  registered BEFORE the roadmap router whose wildcard /{space}/... would
  otherwise swallow them as space names.
"""

from __future__ import annotations

import os
from contextlib import asynccontextmanager
from pathlib import Path
from typing import AsyncIterator

import tomlkit
from fastapi import FastAPI, File, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse, HTMLResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from sarthak.core.config import load_config
from sarthak.core.logging import get_logger

log = get_logger(__name__)


def _resolve_react_dist() -> Path:
    """
    Locate the bundled React dist directory.

    Works in three environments:
      1. Installed wheel  — importlib.resources (Python 3.11+ Traversable)
      2. Source checkout  — __file__-relative path
      3. PyInstaller binary — sys._MEIPASS-relative path
    """
    import importlib.resources
    import sys

    # PyInstaller one-file binary
    base = getattr(sys, "_MEIPASS", None)
    if base:
        p = Path(base) / "sarthak" / "web" / "react_dist"
        if p.is_dir():
            return p

    # Installed wheel or editable install — use importlib.resources
    try:
        ref = importlib.resources.files("sarthak.web") / "react_dist"
        # Materialise to a real filesystem path (works for zip-safe wheels too)
        with importlib.resources.as_file(ref) as p:
            if Path(p).is_dir():
                return Path(p)
    except Exception:
        pass

    # Source-tree fallback
    p = Path(__file__).parent / "react_dist"
    return p


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Ensure built-in system agents are registered on startup."""
    try:
        from sarthak.agents.scheduler import ensure_builtin_agents

        ensure_builtin_agents()
    except Exception as e:
        log.warning("startup_agents_failed", error=str(e))
    yield


app = FastAPI(title="Sarthak", docs_url=None, redoc_url=None, lifespan=lifespan)


# ── Helpers ───────────────────────────────────────────────────────────────────


def _config_path() -> Path:
    env = os.environ.get("SARTHAK_CONFIG", "").strip()
    return Path(env) if env else Path.home() / ".sarthak_ai" / "config.toml"


# ── SPA ───────────────────────────────────────────────────────────────────────

_REACT_DIST = _resolve_react_dist()
_REACT_HTML = _REACT_DIST / "index.html"

_HTML = _REACT_HTML

_MISSING_FRONTEND_HTML = """
<!DOCTYPE html><html><head><title>Sarthak — Frontend Not Found</title>
<style>body{font-family:sans-serif;max-width:640px;margin:60px auto;padding:0 20px;}
pre{background:#f4f4f4;padding:12px;border-radius:4px;overflow-x:auto;}</style>
</head><body>
<h2>Frontend assets not found</h2>
<p>The React frontend was not bundled with this installation.<br>
Run the following to build it, then restart the server:</p>
<pre>cd /path/to/sarthak-repo\nbash rebuild_frontend.sh\nuv pip install -e .</pre>
<p>If you installed from PyPI and see this message, please
<a href="https://github.com/productive-pro/sarthak/issues">open an issue</a>.</p>
</body></html>
"""


def _read_spa_html() -> str:
    if _REACT_HTML.exists():
        return _REACT_HTML.read_text(encoding="utf-8")
    return _MISSING_FRONTEND_HTML


@app.get("/", response_class=HTMLResponse)
async def spa():
    return _read_spa_html()


@app.get("/roadmap", response_class=HTMLResponse)
async def roadmap_ui():
    # Roadmap is served by the React SPA — same index.html with hash routing
    return _read_spa_html()


# ── Dashboard ─────────────────────────────────────────────────────────────────


@app.get("/api/dashboard")
async def dashboard(hours: int = 24) -> dict:
    from pathlib import Path
    from sarthak.spaces.store import get_active_space, list_spaces, load_space

    data: dict = {
        "active_space": None,
        "spaces_count": 0,
        "spaces": [],
    }

    try:
        active = get_active_space()
        if active and active.get("directory"):
            ws_dir = Path(active["directory"])
            ws = load_space(ws_dir) or {}
            profile = ws.get("__profile__", {})

            from sarthak.spaces.models import XP_THRESHOLDS, LEVEL_ORDER
            xp = profile.get("xp", 0)
            _thresholds = [0] + [XP_THRESHOLDS[lvl] for lvl in LEVEL_ORDER]
            cur_lvl_xp = next((t for t in reversed(_thresholds) if xp >= t), 0)
            next_lvl_xp = next((t for t in _thresholds if t > xp), _thresholds[-1])
            progress_pct = (
                round((xp - cur_lvl_xp) / max(next_lvl_xp - cur_lvl_xp, 1) * 100)
                if next_lvl_xp > cur_lvl_xp
                else 100
            )

            data["active_space"] = {
                "name": active.get("name") or ws.get("name", ""),
                "directory": active["directory"],
                "space_type": ws.get("space_type", ""),
                "domain": profile.get("domain", ""),
                "level": profile.get("level", ""),
                "xp": xp,
                "xp_to_next": next_lvl_xp - xp,
                "progress_pct": progress_pct,
                "streak_days": profile.get("streak_days", 0),
                "session_count": profile.get("session_count", 0),
                "skills": (profile.get("skills") or [])[-5:],
                "current_concept": profile.get("current_concept", ""),
                "activated_at": active.get("activated_at", ""),
            }
    except Exception:
        pass

    try:
        spaces = list_spaces()
        data["spaces_count"] = len(spaces)
        data["spaces"] = [
            {
                "name": s.get("name", ""),
                "space_type": s.get("space_type", ""),
                "progress": s.get("progress", 0),
                "updated_at": s.get("updated_at", ""),
            }
            for s in spaces[:5]
        ]
    except Exception:
        pass

    return data


# ── Chat (SSE streaming) ──────────────────────────────────────────────────────


class ChatReq(BaseModel):
    message: str
    session_id: str | None = None
    history: list[dict[str, str]] = []


async def _stream_chat(message: str, session_id: str | None) -> AsyncIterator[str]:
    import uuid

    from sarthak.features.channels import (
        load_history_messages,
        save_chat_turn,
        stream_dispatch,
    )

    sid = session_id
    if not sid:
        from sarthak.storage.helpers import get_latest_chat_session_id

        try:
            sid = await get_latest_chat_session_id()
        except Exception:
            pass
    if not sid:
        sid = str(uuid.uuid4())

    history = await load_history_messages(sid)
    full_reply = ""
    try:
        async for partial_reply in stream_dispatch(
            message, session_id=sid, message_history=history
        ):
            full_reply = partial_reply
            yield f"data: {partial_reply}\n\n"
    except Exception as exc:
        yield f"data: [Error: {exc}]\n\n"

    if full_reply:
        try:
            await save_chat_turn(sid, message, full_reply)
        except Exception:
            pass

    yield f"data: [SESSION:{sid}]\n\n"
    yield "data: [DONE]\n\n"


@app.post("/api/chat")
async def chat(req: ChatReq):
    return StreamingResponse(
        _stream_chat(req.message, req.session_id),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@app.get("/api/chat/session")
async def get_chat_session():
    import uuid

    from sarthak.storage.helpers import get_latest_chat_session_id

    try:
        sid = await get_latest_chat_session_id()
        return {"session_id": sid or str(uuid.uuid4())}
    except Exception:
        return {"session_id": str(uuid.uuid4())}


@app.get("/api/chat/history")
async def get_chat_history_api(session_id: str, limit: int = 40):
    from sarthak.storage.helpers import get_chat_history

    try:
        rows = await get_chat_history(session_id, limit=limit)
        return {
            "session_id": session_id,
            "messages": [
                {"role": r["role"], "content": r["content"], "ts": r.get("ts")}
                for r in rows
            ],
        }
    except Exception as exc:
        raise HTTPException(500, str(exc))


@app.get("/api/chat/sessions")
async def list_chat_sessions(limit: int = 20):
    from sarthak.storage.helpers import get_chat_sessions

    try:
        sessions = await get_chat_sessions(limit=limit)
        return {
            "sessions": [
                {
                    "session_id": s["session_id"],
                    "last_ts": s.get("last_ts"),
                    "msg_count": s.get("msg_count", 0),
                }
                for s in sessions
            ]
        }
    except Exception as exc:
        raise HTTPException(500, str(exc))


# ── Config ────────────────────────────────────────────────────────────────────


@app.get("/api/config")
async def get_config() -> dict:
    path = _config_path()
    if not path.exists():
        raise HTTPException(404, "Config not found")
    return {"path": str(path), "content": path.read_text(encoding="utf-8")}


class ConfigSave(BaseModel):
    content: str


@app.put("/api/config")
async def save_config(body: ConfigSave) -> dict:
    try:
        tomlkit.parse(body.content)
    except Exception as exc:
        raise HTTPException(400, f"Invalid TOML: {exc}")
    path = _config_path()
    path.write_text(body.content, encoding="utf-8")
    return {"ok": True, "path": str(path)}


# ── Spaces — fixed paths MUST come BEFORE roadmap_router include ──────────────
# FastAPI matches in registration order. roadmap_router registers /{space}/...
# which would match "init", "rag", "session", "quick", "profile" as space names.


@app.get("/api/spaces")
async def list_spaces_api() -> list[dict]:
    from sarthak.spaces.store import get_active_space, list_spaces

    active = get_active_space()
    active_dir = active.get("directory", "") if active else ""
    spaces = list_spaces()
    for s in spaces:
        s["is_active"] = s.get("directory", "") == active_dir
    return spaces


@app.get("/api/spaces/active")
async def get_active_space_api() -> dict:
    from sarthak.spaces.store import get_active_space

    active = get_active_space()
    return active or {}


class ActivateReq(BaseModel):
    directory: str


@app.post("/api/spaces/activate")
async def activate_space_api(body: ActivateReq) -> dict:
    from sarthak.spaces.store import set_active_space

    ws = Path(body.directory).expanduser().resolve()
    try:
        space = set_active_space(ws)
        return {"ok": True, "name": space.get("name", ""), "directory": str(ws)}
    except FileNotFoundError as exc:
        raise HTTPException(404, str(exc))


class SpaceInit(BaseModel):
    directory: str
    space_type: str = "data_science"
    background: str = ""
    name: str = ""
    goal: str = ""
    rag_enabled: bool = False


@app.post("/api/spaces/init")
async def init_space_api(body: SpaceInit) -> dict:
    """Initialize a space: create config, apply workspace template, and prime the SQLite DB.

    WorkspaceTransformer.transform and RoadmapDB.init are sync I/O — run them
    in a thread so they don't block the event loop, and parallelise with asyncio.gather.
    """
    import asyncio

    from sarthak.spaces.models import SpaceType
    from sarthak.spaces.roadmap.db import RoadmapDB
    from sarthak.spaces.store import (
        init_space,
        init_space_profile,
        load_space,
        save_profile,
    )
    from sarthak.spaces.workspace_transformer import WorkspaceTransformer

    ws = Path(body.directory).expanduser().resolve()
    st = SpaceType(body.space_type)

    # Sync config writes — fast, no thread needed
    if not load_space(ws):
        init_space(
            ws,
            name=body.name or st.value.replace("_", " ").title(),
            description=f"Sarthak Space: {st.value}",
            goal=body.goal,
        )
    profile = init_space_profile(
        ws, st, background=body.background, learner_name=body.name
    )

    # Parallelize: workspace template I/O  +  SQLite schema init
    def _transform() -> list[str]:
        return WorkspaceTransformer(ws).transform(st)

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

    return {
        "domain": profile.domain,
        "directory": str(ws),
        "files_created": len(created),
        "rag_enabled": body.rag_enabled,
    }


class SessionReq(BaseModel):
    directory: str
    reshape: bool = False


@app.post("/api/spaces/session")
async def run_session(body: SessionReq) -> dict:
    from sarthak.spaces.orchestrator import SpacesOrchestrator

    orch = SpacesOrchestrator(Path(body.directory).expanduser().resolve())
    result = await orch.next_session(reshape_workspace=body.reshape)
    return {
        "reply": result.reply,
        "xp_earned": result.xp_earned,
        "workspace_changes": result.workspace_changes or [],
    }


@app.post("/api/spaces/quick")
async def quicktest(body: SessionReq) -> dict:
    from sarthak.spaces.orchestrator import SpacesOrchestrator

    orch = SpacesOrchestrator(Path(body.directory).expanduser().resolve())
    result = await orch.quicktest()
    return {"reply": result.reply}


# RAG legacy endpoints — body takes {directory} instead of URL space param.
# Returns same shape as roadmap router so frontend code is uniform.


@app.post("/api/spaces/rag/index")
async def rag_index_legacy(body: SessionReq) -> dict:
    from sarthak.spaces.rag import index_space

    ws = Path(body.directory).expanduser().resolve()
    count = await index_space(ws)
    return {"chunks_indexed": count, "directory": str(ws)}


@app.get("/api/spaces/rag/status")
async def rag_status_legacy(directory: str) -> dict:
    from sarthak.spaces.rag import rag_status as _status

    return _status(Path(directory).expanduser().resolve())


class RagQuery(BaseModel):
    directory: str
    query: str
    top_k: int = 5


@app.post("/api/spaces/rag/search")
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


@app.post("/api/spaces/profile")
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


# ── Agents ────────────────────────────────────────────────────────────────────


@app.get("/api/agents")
async def list_agents_api() -> list[dict]:
    from sarthak.agents.store import list_agents

    return [s.model_dump() for s in list_agents()]


class AgentCreate(BaseModel):
    description: str
    directory: str = ""
    notify_telegram: bool = False


@app.post("/api/agents")
async def create_agent_api(body: AgentCreate) -> dict:
    from sarthak.agents.creator import create_agent_from_description

    space_dir = Path(body.directory).resolve() if body.directory else None
    spec = await create_agent_from_description(
        body.description,
        space_dir=space_dir,
        notify_telegram=body.notify_telegram or None,
    )
    return spec.model_dump()


@app.post("/api/agents/{agent_id}/run")
async def run_agent_api(agent_id: str) -> dict:
    from sarthak.agents.runner import run_agent
    from sarthak.agents.store import load_agent

    spec = load_agent(agent_id)
    if not spec:
        raise HTTPException(404, "Agent not found")
    run = await run_agent(spec)
    return {
        "success": run.success,
        "output": run.output,
        "error": run.error,
        "run_id": run.run_id,
    }


@app.get("/api/agents/{agent_id}/logs")
async def agent_logs_api(agent_id: str, limit: int = 5) -> list[dict]:
    from sarthak.agents.store import load_runs

    return [r.model_dump() for r in load_runs(agent_id, limit=limit)]


@app.delete("/api/agents/{agent_id}")
async def delete_agent_api(agent_id: str) -> dict:
    from sarthak.agents.store import delete_agent

    if not delete_agent(agent_id):
        raise HTTPException(404, "Agent not found")
    return {"ok": True}


@app.patch("/api/agents/{agent_id}")
async def patch_agent_api(agent_id: str, body: dict) -> dict:
    from sarthak.agents.store import update_agent

    spec = update_agent(agent_id, **body)
    if not spec:
        raise HTTPException(404, "Agent not found")
    return spec.model_dump()


# ── Space agents ───────────────────────────────────────────────────────────────────────


@app.get("/api/spaces/{space_id}/agents")
async def list_space_agents_api(space_id: str) -> list[dict]:
    import urllib.parse

    from sarthak.agents.store import list_agents
    from sarthak.spaces.store import list_spaces

    decoded = urllib.parse.unquote(space_id)
    spaces = list_spaces()
    match = next(
        (
            s
            for s in spaces
            if s.get("name") in (space_id, decoded)
            or s.get("directory", "").endswith(decoded)
        ),
        None,
    )
    if not match:
        raise HTTPException(404, "Space not found")
    agents = list_agents(space_dir=Path(match["directory"]))
    return [s.model_dump() for s in agents]


class SpaceAgentCreate(BaseModel):
    description: str
    notify_telegram: bool = False


@app.post("/api/spaces/{space_id}/agents")
async def create_space_agent_api(space_id: str, body: SpaceAgentCreate) -> dict:
    import urllib.parse

    from sarthak.agents.creator import create_agent_from_description
    from sarthak.spaces.store import list_spaces

    decoded = urllib.parse.unquote(space_id)
    spaces = list_spaces()
    match = next(
        (
            s
            for s in spaces
            if s.get("name") in (space_id, decoded)
            or s.get("directory", "").endswith(decoded)
        ),
        None,
    )
    if not match:
        raise HTTPException(404, "Space not found")
    space_dir = Path(match["directory"])
    spec = await create_agent_from_description(
        body.description,
        space_dir=space_dir,
        notify_telegram=body.notify_telegram or None,
    )
    return spec.model_dump()


# ── AG-UI ─────────────────────────────────────────────────────────────────────


@app.post("/api/ag-ui")
async def ag_ui_endpoint(request: Request):
    from pydantic_ai.ui.ag_ui import AGUIAdapter

    from sarthak.features.channels import make_orchestrator_agent_and_deps

    agent, deps = make_orchestrator_agent_and_deps()
    return await AGUIAdapter.dispatch_request(request, agent=agent, deps=deps)


# ── Per-space roadmap router — MUST come after all fixed /api/spaces/... paths ─

from sarthak.spaces.roadmap.router import _set_base as _set_roadmap_base
from sarthak.spaces.roadmap.router import roadmap_router  # noqa: E402

app.include_router(roadmap_router, prefix="/api/spaces")

_spaces_root_env = os.environ.get("SARTHAK_SPACES_DIR", "").strip()
if _spaces_root_env:
    _set_roadmap_base(Path(_spaces_root_env))


# ── Session end endpoint ──────────────────────────────────────────────────────


class SessionEndReq(BaseModel):
    task_completed: bool = True
    understanding_rating: int = 3
    stuck_on: list[str] = []
    breakthrough: str = ""
    session_id: str = ""


@app.post("/api/spaces/{space_id}/session/end")
async def end_session_api(space_id: str, body: SessionEndReq) -> dict:
    from sarthak.spaces.models import SelfReport
    from sarthak.spaces.orchestrator import SpacesOrchestrator
    from sarthak.spaces.store import list_spaces

    spaces = list_spaces()
    match = next(
        (
            s
            for s in spaces
            if s.get("directory", "").endswith(space_id) or s.get("name") == space_id
        ),
        None,
    )
    if not match:
        raise HTTPException(404, "Space not found")

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


# ── Practice test endpoints ────────────────────────────────────────────────────


def _resolve_space_dir(space_id: str, body_directory: str = "") -> Path:
    """Resolve the workspace directory from body or space_id URL param.

    body_directory takes precedence (backward-compat).  When omitted,
    the space_id is matched against the registry by name or directory suffix,
    mirroring the lookup used by all other /spaces/{space_id}/… endpoints.
    """
    if body_directory.strip():
        return Path(body_directory).expanduser().resolve()
    # Resolve from URL space_id via registry
    import urllib.parse

    from sarthak.spaces.store import list_spaces

    decoded = urllib.parse.unquote(space_id)
    spaces = list_spaces()
    match = next(
        (
            s
            for s in spaces
            if s.get("name") in (space_id, decoded)
            or s.get("directory", "").endswith(decoded)
        ),
        None,
    )
    if not match:
        raise HTTPException(404, f"Space '{space_id}' not found")
    return Path(match["directory"])


class PracticeGenerateReq(BaseModel):
    directory: str = ""  # optional — resolved from space_id if omitted
    test_type: str = "concept"
    scope: str = ""
    source: str = "llm"
    source_prompt: str = ""
    seconds_per_question: int = 120
    n_questions: int | None = None


@app.post("/api/spaces/{space_id}/practice/generate")
async def practice_generate_api(space_id: str, body: PracticeGenerateReq) -> dict:
    from sarthak.spaces.orchestrator import SpacesOrchestrator

    ws = _resolve_space_dir(space_id, body.directory)
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


@app.post("/api/spaces/{space_id}/practice/grade")
async def practice_grade_api(space_id: str, body: PracticeGradeReq) -> dict:

    from sarthak.spaces.orchestrator import SpacesOrchestrator
    from sarthak.spaces.practice import PracticeEngine

    space_dir = _resolve_space_dir(space_id, body.directory)
    orch = SpacesOrchestrator(space_dir)

    # Load saved test from .spaces/tests.jsonl
    tests_file = space_dir / ".spaces" / "tests.jsonl"
    if not tests_file.exists():
        raise HTTPException(404, "No tests found")

    from sarthak.spaces.models import PracticeTest

    test = None
    for line in tests_file.read_text().splitlines():
        try:
            t = PracticeTest.model_validate_json(line)
            if t.test_id == body.test_id:
                test = t
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
            },
        )
    except Exception:
        pass

    # Update SRS/profile
    profile = orch._load_or_init()
    for concept in result.strong_concepts:
        if concept not in profile.learner.mastered_concepts:
            profile.learner.mastered_concepts.append(concept)
        profile = orch._srs.update_after_review(profile, concept, recalled=True)
    for concept in result.weak_concepts:
        if concept not in profile.learner.struggling_concepts:
            profile.learner.struggling_concepts.append(concept)
        profile = orch._srs.update_after_review(profile, concept, recalled=False)

    from sarthak.spaces.models import award_xp

    profile, _ = award_xp(profile, result.xp_earned)
    orch._save(profile)

    return result.model_dump()


# ── Space profile endpoint ──────────────────────────────────────────────────────

# ── Digest subscribe endpoint ─────────────────────────────────────────────────


class DigestSubscribeReq(BaseModel):
    subscribed: bool


@app.post("/api/spaces/{space_id}/digest/subscribe")
async def digest_subscribe_api(space_id: str, body: DigestSubscribeReq) -> dict:
    """Persist digest subscription preference in .spaces.json."""
    from sarthak.spaces.store import list_spaces, update_space

    spaces = list_spaces()
    match = next(
        (
            s
            for s in spaces
            if s.get("directory", "").endswith(space_id) or s.get("name") == space_id
        ),
        None,
    )
    if not match:
        raise HTTPException(404, "Space not found")

    update_space({"digest_subscribed": body.subscribed}, Path(match["directory"]))
    return {"ok": True, "subscribed": body.subscribed}


@app.get("/api/spaces/{space_id}/digest/subscribe")
async def digest_subscribe_status_api(space_id: str) -> dict:
    """Return current digest subscription status."""
    from sarthak.spaces.store import list_spaces, load_space

    spaces = list_spaces()
    match = next(
        (
            s
            for s in spaces
            if s.get("directory", "").endswith(space_id) or s.get("name") == space_id
        ),
        None,
    )
    if not match:
        raise HTTPException(404, "Space not found")

    ws = load_space(Path(match["directory"])) or {}
    return {"subscribed": bool(ws.get("digest_subscribed", False))}


# ── Optimize endpoint ──────────────────────────────────────────────────────────


@app.get("/api/spaces/{space_id}/optimize")
async def optimize_api(space_id: str, recent_n: int = 10) -> list[dict]:
    from sarthak.spaces.learner_context import build_learner_context
    from sarthak.spaces.optimizer import SignalOptimizer
    from sarthak.spaces.store import list_spaces, load_profile

    spaces = list_spaces()
    match = next(
        (
            s
            for s in spaces
            if s.get("directory", "").endswith(space_id) or s.get("name") == space_id
        ),
        None,
    )
    if not match:
        raise HTTPException(404, "Space not found")

    ws_dir = Path(match["directory"])
    profile = load_profile(ws_dir)
    if not profile:
        return []

    lc = await build_learner_context(ws_dir, profile, days=recent_n * 2)
    optimizer = SignalOptimizer()
    opts = optimizer.analyze_from_context(ws_dir, profile, lc)
    return [o.model_dump() for o in opts]


@app.get("/api/spaces/{space_id}/profile")
async def space_profile_api(space_id: str) -> dict:
    """Return full structured SpaceProfile fields — used by SpaceHome hero stats."""
    import urllib.parse

    from sarthak.spaces.models import LEVEL_LABELS, XP_THRESHOLDS
    from sarthak.spaces.store import list_spaces, load_profile

    decoded = urllib.parse.unquote(space_id)
    spaces = list_spaces()
    match = next(
        (
            s
            for s in spaces
            if s.get("name") in (space_id, decoded)
            or s.get("directory", "").endswith(decoded)
        ),
        None,
    )
    if not match:
        raise HTTPException(404, "Space not found")

    profile = load_profile(Path(match["directory"]))
    if not profile:
        return {"directory": match["directory"], "name": match.get("name", "")}

    lr = profile.learner
    threshold = XP_THRESHOLDS.get(lr.skill_level, 9999)
    return {
        "directory": match["directory"],
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


@app.get("/api/spaces/{space_id}/status")
async def space_status_api(space_id: str) -> dict:
    import urllib.parse

    from sarthak.spaces.store import list_spaces, load_profile

    decoded = urllib.parse.unquote(space_id)
    spaces = list_spaces()
    match = next(
        (
            s
            for s in spaces
            if s.get("name") in (space_id, decoded)
            or s.get("directory", "").endswith(decoded)
        ),
        None,
    )
    if not match:
        raise HTTPException(404, "Space not found")
    from sarthak.spaces.models import LEVEL_LABELS, XP_THRESHOLDS
    from sarthak.spaces.orchestrator import SpacesOrchestrator

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


@app.post("/api/spaces/{space_id}/files/chat")
async def chat_with_file_api(space_id: str, body: FileChatReq) -> dict:
    from sarthak.spaces.rag import chat_with_file
    from sarthak.spaces.store import list_spaces

    spaces = list_spaces()
    match = next(
        (
            s
            for s in spaces
            if s.get("directory", "").endswith(space_id) or s.get("name") == space_id
        ),
        None,
    )
    if not match:
        raise HTTPException(404, "Space not found")

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


# ── Files: open in native app ────────────────────────────────────────────────


class FileOpenReq(BaseModel):
    path: str


@app.post("/api/spaces/{space_id}/files/open")
async def open_file_native(space_id: str, body: FileOpenReq) -> dict:
    import subprocess
    import sys

    from sarthak.spaces.store import list_spaces

    spaces = list_spaces()
    match = next(
        (
            s
            for s in spaces
            if s.get("directory", "").endswith(space_id) or s.get("name") == space_id
        ),
        None,
    )
    if not match:
        raise HTTPException(404, "Space not found")

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


# ── Space RAG endpoints ────────────────────────────────────────────────────────


@app.get("/api/spaces/{space_id}/rag/walk")
async def space_rag_walk(space_id: str) -> dict:
    from sarthak.spaces.rag import rag_status, walk_space

    ws = _resolve_space_dir(space_id)
    files = walk_space(ws)
    st = rag_status(ws)
    return {
        "files": files,
        "total_files": len(files),
        "indexed_files": st.get("indexed_files", 0),
        "indexed_chunks": st.get("indexed_chunks", 0),
    }


@app.get("/api/spaces/{space_id}/rag/files")
async def space_rag_files(space_id: str) -> dict:
    from sarthak.spaces.rag import list_indexed_files, rag_status

    ws = _resolve_space_dir(space_id)
    st = rag_status(ws)
    return {
        "files": [{"path": p} for p in list_indexed_files(ws)],
        "indexed_files": st.get("indexed_files", 0),
        "indexed_chunks": st.get("indexed_chunks", 0),
    }


class RagIndexPathsReq(BaseModel):
    paths: list[str]
    pipeline: str = "text"


@app.post("/api/spaces/{space_id}/rag/index-paths/stream")
async def space_rag_index_stream(space_id: str, body: RagIndexPathsReq):
    from sarthak.spaces.rag import index_paths_streaming

    ws = _resolve_space_dir(space_id)
    return StreamingResponse(
        index_paths_streaming(ws, body.paths, pipeline=body.pipeline),
        media_type="text/event-stream",
    )


@app.post("/api/spaces/{space_id}/rag/export-activities")
async def space_rag_export_activities(space_id: str) -> dict:
    from sarthak.spaces.rag import export_activities_to_markdown

    ws = _resolve_space_dir(space_id)
    written = await export_activities_to_markdown(ws)
    return {"written": len(written), "paths": written}


@app.post("/api/spaces/{space_id}/rag/upload")
async def space_rag_upload(
    space_id: str,
    pipeline: str = "text",
    file: UploadFile = File(...),
) -> dict:
    from sarthak.spaces.rag import index_paths, rag_status

    ws = _resolve_space_dir(space_id)

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


@app.post("/api/spaces/{space_id}/rag/search")
async def space_rag_search(space_id: str, body: SpaceRagQuery) -> dict:
    from sarthak.spaces.rag import search_space_structured

    ws = _resolve_space_dir(space_id)
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


@app.get("/api/spaces/{space_id}/rag/status")
async def space_rag_status(space_id: str) -> dict:
    from sarthak.spaces.rag import rag_status

    ws = _resolve_space_dir(space_id)
    return rag_status(ws)


class RagChatReq(BaseModel):
    question: str
    history: list[dict] = []
    top_k: int = 5


@app.post("/api/spaces/{space_id}/rag/chat")
async def space_rag_chat(space_id: str, body: RagChatReq) -> dict:
    from sarthak.spaces.rag import search_space_structured
    from sarthak.core.ai_utils.multi_provider import call_llm

    ws = _resolve_space_dir(space_id)
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


# ── User Activity ─────────────────────────────────────────────────────────────


class ActivityRecord(BaseModel):
    activity_type: str  # 'audio_note'|'video_note'|'code_run'|'chat'|'file_upload'|'practice_test'|'quicktest'|'note'
    space_dir: str = ""
    concept_id: str = ""
    concept_title: str = ""
    session_id: str = ""
    content_text: str = ""
    media_path: str = ""
    metadata: dict = {}


@app.post("/api/activity")
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


@app.get("/api/activity")
async def list_activity(
    space_dir: str = "",
    activity_type: str = "",
    concept_title: str = "",
    days: int = 30,
    limit: int = 100,
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


@app.get("/api/activity/summary")
async def activity_summary_api(space_dir: str, days: int = 7) -> dict:
    """Per-type activity counts for a space — used by the digest and dashboard."""
    from sarthak.storage.activity_store import activity_summary
    return await activity_summary(space_dir, days=days)


# ── Static (before catch-all) ─────────────────────────────────────────────────

_STATIC = Path(__file__).parent / "static"
_STATIC.mkdir(exist_ok=True)
app.mount("/static", StaticFiles(directory=str(_STATIC)), name="static")

# React build assets (hashed filenames like /assets/index-abc123.js)
if _REACT_DIST.exists():
    _REACT_ASSETS = _REACT_DIST / "assets"
    if _REACT_ASSETS.exists():
        app.mount(
            "/assets", StaticFiles(directory=str(_REACT_ASSETS)), name="react_assets"
        )
    # Serve other root-level static files from react_dist (favicon, svg, etc.)
    app.mount(
        "/ui", StaticFiles(directory=str(_REACT_DIST)), name="react_root"
    )


# ── SPA catch-all (last) ──────────────────────────────────────────────────────


@app.get("/{full_path:path}", response_class=HTMLResponse, include_in_schema=False)
async def spa_fallback(full_path: str):
    if full_path.startswith("api/"):
        raise HTTPException(404)
    if _REACT_DIST.exists():
        candidate = (_REACT_DIST / full_path).resolve()
        if candidate.is_file() and _REACT_DIST in candidate.parents:
            return FileResponse(candidate)
    return _read_spa_html()


# ── Launch ────────────────────────────────────────────────────────────────────


def launch_web(host: str = "127.0.0.1", port: int = 7860) -> None:
    import uvicorn

    cfg = load_config()
    project_name = cfg.get("general", {}).get("project_name", "Sarthak")

    # ── Print URL banner ──────────────────────────────────────────────────────
    OR = "\033[38;5;214m"; CY = "\033[38;5;87m"; GR = "\033[38;5;82m"
    BD = "\033[1m";        RS = "\033[0m"
    display_host = "localhost" if host in ("127.0.0.1", "0.0.0.0") else host
    url = f"http://{display_host}:{port}"
    print(f"\n{OR}{BD}  {project_name} Web UI{RS}")
    print(f"  {GR}→{RS}  {CY}{BD}{url}{RS}")
    print(f"  {GR}→{RS}  Press Ctrl-C to stop\n")

    log.info("web_start", host=host, port=port, url=url, project=project_name)
    uvicorn.run(app, host=host, port=port, log_level="warning")
