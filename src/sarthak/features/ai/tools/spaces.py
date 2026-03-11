"""
Sarthak Spaces tools — exposed to the orchestrator agent.

All tools are sync wrappers: they use nest_asyncio-compatible asyncio.run()
via a thread-based executor so they are safe to call from within an already-
running event loop (pydantic-ai's async context).
"""
from __future__ import annotations

import asyncio
import concurrent.futures
from pathlib import Path

from sarthak.core.logging import get_logger

log = get_logger(__name__)

_EXECUTOR = concurrent.futures.ThreadPoolExecutor(max_workers=4, thread_name_prefix="spaces")


def _run(coro):
    """Run an async coroutine safely from any context (sync or async)."""
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        loop = None

    if loop and loop.is_running():
        # Called from within an existing event loop (pydantic-ai agent context).
        # Submit to a fresh thread with its own event loop.
        future = _EXECUTOR.submit(asyncio.run, coro)
        return future.result(timeout=120)
    else:
        return asyncio.run(coro)


# ── Session ────────────────────────────────────────────────────────────────────

def tool_spaces_session(space_dir: str = "", space_type: str = "data_science") -> str:
    """Run a Sarthak Spaces learning session. Returns the full learning reply."""
    from sarthak.spaces.orchestrator import SpacesOrchestrator
    from sarthak.spaces.models import SpaceType
    try:
        ws_dir = Path(space_dir).resolve() if space_dir else Path.cwd()
        orch = SpacesOrchestrator(ws_dir)
        try:
            st = SpaceType(space_type)
        except ValueError:
            st = SpaceType.DATA_SCIENCE
        result = _run(orch.next_session(space_type=st))
        return result.reply
    except Exception as exc:
        log.warning("tool_spaces_session_failed", error=str(exc))
        return f"Spaces session failed: {exc}"


# ── Status ─────────────────────────────────────────────────────────────────────

def tool_spaces_status(space_dir: str = "") -> str:
    """Get the learner's mastery status for a space."""
    from sarthak.spaces.orchestrator import SpacesOrchestrator
    try:
        orch = SpacesOrchestrator(Path(space_dir).resolve() if space_dir else Path.cwd())
        return orch.get_status()
    except Exception as exc:
        log.warning("tool_spaces_status_failed", error=str(exc))
        return f"Spaces status failed: {exc}"


# ── Setup ──────────────────────────────────────────────────────────────────────

def tool_spaces_setup(space_dir: str = "") -> str:
    """Set up expert environment for a Sarthak Space (scan + reshape workspace)."""
    from sarthak.spaces.orchestrator import SpacesOrchestrator
    try:
        orch = SpacesOrchestrator(Path(space_dir).resolve() if space_dir else Path.cwd())
        result = _run(orch.setup_environment())
        return result.reply
    except Exception as exc:
        log.warning("tool_spaces_setup_failed", error=str(exc))
        return f"Spaces setup failed: {exc}"


# ── Evaluate ───────────────────────────────────────────────────────────────────

def tool_spaces_evaluate(concept: str, submission: str, space_dir: str = "") -> str:
    """Evaluate learner's work on a concept and update their mastery."""
    from sarthak.spaces.orchestrator import SpacesOrchestrator
    try:
        orch = SpacesOrchestrator(Path(space_dir).resolve() if space_dir else Path.cwd())
        result = _run(orch.evaluate(concept, f"Practice: {concept}", submission))
        return result.reply
    except Exception as exc:
        log.warning("tool_spaces_evaluate_failed", error=str(exc))
        return f"Spaces evaluate failed: {exc}"


# ── Init ───────────────────────────────────────────────────────────────────────

def tool_spaces_init(
    space_dir: str,
    space_type: str = "data_science",
    background: str = "",
    learner_name: str = "",
) -> str:
    """Initialize a Sarthak Space in a directory."""
    from sarthak.spaces.models import SpaceType
    from sarthak.spaces.store import load_space, init_space, init_space_profile
    from sarthak.spaces.workspace_transformer import WorkspaceTransformer
    try:
        ws_dir = Path(space_dir).resolve()
        st = SpaceType(space_type)
        if not load_space(ws_dir):
            domain_label = st.value.replace("_", " ").title()
            init_space(
                ws_dir,
                name=learner_name or domain_label,
                description=f"Sarthak Space: {domain_label}",
                goal=f"Mastery in {domain_label}",
            )
        profile = init_space_profile(ws_dir, st, background=background, learner_name=learner_name)
        transformer = WorkspaceTransformer(ws_dir)
        created = transformer.transform(st)
        return (
            f"Sarthak Space initialized: {profile.domain}\n"
            f"Directory: `{ws_dir}`\n"
            f"{len(created)} files/directories created.\n"
            f"Run `sarthak spaces session --dir {space_dir}` to start learning."
        )
    except Exception as exc:
        log.warning("tool_spaces_init_failed", error=str(exc))
        return f"Spaces init failed: {exc}"


# ── Context (summary for agent injection) ─────────────────────────────────────

def tool_spaces_context(space_dir: str = "") -> str:
    """Return space context: goal/tools/sessions + SOUL + behavioural MEMORY."""
    from sarthak.spaces.store import get_space_context
    from sarthak.spaces.memory import read_context_block
    try:
        ws_dir = Path(space_dir).resolve() if space_dir else None
        space_ctx  = get_space_context(ws_dir) or "No active space."
        memory_ctx = read_context_block(ws_dir or Path.cwd(), max_chars=800) if ws_dir or Path.cwd() else ""
        if memory_ctx:
            return f"{space_ctx}\n\n---\n{memory_ctx}"
        return space_ctx
    except Exception as exc:
        return f"Space context failed: {exc}"


# ── QuickTest ──────────────────────────────────────────────────────────────────

def tool_spaces_quick(space_dir: str = "") -> str:
    """Run a 5-minute micro-learning task."""
    from sarthak.spaces.orchestrator import SpacesOrchestrator
    try:
        orch = SpacesOrchestrator(Path(space_dir).resolve() if space_dir else Path.cwd())
        result = _run(orch.quicktest())
        return result.reply
    except Exception as exc:
        log.warning("tool_spaces_quick_failed", error=str(exc))
        return f"Spaces quicktest failed: {exc}"


# ── List spaces ────────────────────────────────────────────────────────────────

# ── RAG ───────────────────────────────────────────────────────────────────────────────

def tool_spaces_rag_index(space_dir: str = "", full: bool = False) -> str:
    """Index (or re-index) workspace files for RAG search."""
    from sarthak.spaces.rag import index_space
    try:
        ws_dir = Path(space_dir).resolve() if space_dir else Path.cwd()
        n = _run(index_space(ws_dir, incremental=not full))
        return f"Indexed {n} chunks" if n else "All files up to date."
    except Exception as exc:
        return f"RAG index failed: {exc}"


def tool_spaces_rag_search(query: str, space_dir: str = "", top_k: int = 5) -> str:
    """Search indexed workspace files for relevant content (returns file:line refs)."""
    from sarthak.spaces.rag import search_space
    try:
        ws_dir = Path(space_dir).resolve() if space_dir else Path.cwd()
        return _run(search_space(ws_dir, query, top_k=top_k))
    except Exception as exc:
        return f"RAG search failed: {exc}"


# ── Workspace Q&A — answer questions about sessions, RAG, DB, notes, SQL ─────────

def tool_workspace_qa(question: str, space_dir: str = "") -> str:
    """
    Answer any question about the workspace: sessions, notes, RAG index, SRS DB,
    concept progress, activity store, SQL queries, file index, etc.

    Examples:
      "How many sessions did I do this week?"
      "What concepts am I struggling with?"
      "What files are indexed in RAG?"
      "Show me recent notes on linear regression"
      "What quicktests did I fail?"
      "Run a SQL query: SELECT * FROM notes LIMIT 5"
    """
    from sarthak.spaces.workspace_qa import answer_workspace_question
    try:
        ws_dir = Path(space_dir).resolve() if space_dir else Path.cwd()
        return _run(answer_workspace_question(ws_dir, question))
    except Exception as exc:
        log.warning("tool_workspace_qa_failed", error=str(exc))
        return f"Workspace Q&A failed: {exc}"


def tool_workspace_analyse(space_dir: str = "") -> str:
    """Force-refresh Optimal_Learn.md for a space (reads all learner signals + recommendations)."""
    from sarthak.spaces.store import load_profile
    from sarthak.spaces.models import SpaceContext
    from sarthak.spaces.agents import WorkspaceAnalyserAgent, detect_platform
    try:
        ws_dir = Path(space_dir).resolve() if space_dir else Path.cwd()
        profile = load_profile(ws_dir)
        if not profile:
            return "No space found at this directory. Run: sarthak spaces init"
        ctx = SpaceContext(workspace_dir=str(ws_dir), profile=profile, platform=detect_platform())
        analyser = WorkspaceAnalyserAgent()
        content = _run(analyser.analyse(ctx))
        analyser.write_optimal_learn(ws_dir, content)
        return content
    except Exception as exc:
        log.warning("tool_workspace_analyse_failed", error=str(exc))
        return f"Workspace analyse failed: {exc}"


def tool_spaces_list() -> str:
    """List all known Sarthak spaces from the registry."""
    from sarthak.spaces.store import list_spaces, get_active_space
    try:
        all_spaces = list_spaces()
        active = get_active_space()
        active_dir = active.get("directory") if active else None
        if not all_spaces:
            return "No spaces found. Run: sarthak spaces init"
        lines = []
        for s in all_spaces:
            marker = " (active)" if s.get("directory") == active_dir else ""
            lines.append(f"- **{s.get('name', '?')}** `{s.get('directory', '?')}`{marker}")
            if s.get("goal"):
                lines.append(f"  Goal: {s['goal']}")
        return "\n".join(lines)
    except Exception as exc:
        return f"Spaces list failed: {exc}"
