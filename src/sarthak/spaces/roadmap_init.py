"""
Sarthak Spaces — Roadmap bootstrap helper.

Single reusable function: ensure_roadmap(space_dir, profile)
Called from any entry point (web, TUI, Telegram bot, CLI) after a space is created
or whenever the roadmap blob is missing from the DB.

Also exports: discover_custom_domain() — collaborative LLM-based domain discovery
for CUSTOM spaces, returns a dict with domain details and clarifying questions.
"""
from __future__ import annotations

from pathlib import Path

import asyncio

from sarthak.core.logging import get_logger

log = get_logger(__name__)
_ROADMAP_LOCKS: dict[str, asyncio.Lock] = {}
_ROADMAP_LOCKS_GUARD = asyncio.Lock()


async def _get_roadmap_lock(space_dir: Path) -> asyncio.Lock:
    key = str(space_dir.resolve())
    async with _ROADMAP_LOCKS_GUARD:
        if key not in _ROADMAP_LOCKS:
            _ROADMAP_LOCKS[key] = asyncio.Lock()
        return _ROADMAP_LOCKS[key]


def write_directory_structure(
    space_dir: Path,
    domain_name: str,
    workspace_folders: list[str],
    folder_descriptions: dict[str, str] | None = None,
) -> None:
    """
    Write two structure docs:
      - space_structure.md at the space root (user-facing overview)
      - .spaces/directory_structure.md (LLM context injection)
    Called after space creation so agents always have workspace context.
    """
    from datetime import datetime
    lines = [
        f"# Workspace Structure: {domain_name}",
        f"*Generated: {datetime.now().strftime('%Y-%m-%d')}*",
        "",
        "This file documents the purpose of each folder in your learning workspace.",
        "Sarthak agents use this file for workspace context.",
        "",
        "## Directory Layout",
        "",
    ]
    default_descs = {
        "notes": "Your personal notes — concept explanations, insights, summaries.",
        "resources": "Reference materials, PDFs, links, and external content.",
        "projects": "Hands-on projects you build to apply what you learn.",
        "reflections": "Journaling, self-assessment, and learning reflections.",
        "data": "Datasets and data files used in exercises.",
        "notebooks": "Interactive notebooks for exploration and tutorials.",
        "src": "Production-quality code extracted from notebooks.",
        "experiments": "Tracked experiments with results and metadata.",
        "models": "Saved model weights and metadata.",
        "reports": "Final analyses and publication-ready outputs.",
        "flashcards": "Spaced repetition flashcard decks.",
        "mock_tests": "Timed practice tests and results.",
        "weak_areas": "Error log and targeted drilling materials.",
        "subjects": "Subject-by-subject organized study materials.",
        ".spaces": "Sarthak AI learning state — do not delete.",
    }
    descs = {**default_descs, **(folder_descriptions or {})}

    for folder in workspace_folders:
        desc = descs.get(folder, f"Files and materials related to {folder}.")
        actual = space_dir / folder
        lines.append(f"### `{folder}/`")
        lines.append(desc)
        if actual.exists():
            sub = [f.name for f in actual.iterdir() if not f.name.startswith('.')][:5]
            if sub:
                lines.append(f"*Key files: {', '.join(sub)}*")
        lines.append("")

    lines += [
        "## Sarthak State (`.spaces/`)",
        "",
        "| File | Purpose |",
        "|------|---------|",
        "| `sarthak.db` | Roadmap, notes, SRS cards (SQLite) |",
        "| `rag/` | Vector search index |",
        "| `notes/` | OCR-processed concept notes |",
        "| `progress.md` | Mastery tracker (auto-updated) |",
        "| `directory_structure.md` | This file |",
        "",
    ]
    content = "\n".join(lines)
    # Write to .spaces/ for LLM context injection
    hidden = space_dir / ".spaces" / "directory_structure.md"
    hidden.parent.mkdir(parents=True, exist_ok=True)
    hidden.write_text(content, encoding="utf-8")
    # Write user-facing space_structure.md at space root
    root_doc = space_dir / "space_structure.md"
    root_doc.write_text(content, encoding="utf-8")
    log.info("directory_structure_written", path=str(root_doc))


async def ensure_roadmap(
    space_dir: Path,
    profile,  # SpaceProfile
    *,
    force: bool = False,
) -> bool:
    """
    Generate and persist a roadmap if one doesn't exist yet.

    Returns True if a new roadmap was generated, False if one already existed.
    Safe to call multiple times — idempotent unless force=True.
    """
    from sarthak.agents.roadmap_agents import generate_roadmap
    from sarthak.spaces.roadmap.db import RoadmapDB

    lock = await _get_roadmap_lock(space_dir)
    async with lock:
        db = RoadmapDB(space_dir)
        await db.init()

        if not force:
            existing = await db.load_roadmap()
            if existing is not None:
                log.debug("roadmap_already_exists", space=str(space_dir))
                return False

        domain = profile.domain or profile.space_type.value.replace("_", " ").title()
        background = profile.learner.background or "general learner"
        goal = profile.learner.goal or f"master {domain}"
        space_name = space_dir.name

        log.info("roadmap_generating", space=space_name, domain=domain)
        try:
            from sarthak.agents.roadmap_agents import generate_space_overview
            roadmap, overview = await asyncio.gather(
                generate_roadmap(
                    space_name=space_name,
                    domain=domain,
                    background=background,
                    goal=goal,
                ),
                generate_space_overview(
                    domain=domain,
                    background=background,
                    goal=goal,
                ),
            )
            await db.save_roadmap(roadmap)
            # Export a human-readable snapshot alongside SQLite for transparency
            _write_roadmap_json(space_dir, roadmap)
            # Save space overview for the frontend to display
            if overview:
                import json as _json
                overview_path = space_dir / ".spaces" / "overview.json"
                overview_path.write_text(_json.dumps(overview, indent=2), encoding="utf-8")
            log.info("roadmap_saved", space=space_name, chapters=len(roadmap.chapters))
            return True
        except Exception as exc:
            log.error("roadmap_generation_failed", space=space_name, error=str(exc))
            return False


def _write_roadmap_json(space_dir: Path, roadmap) -> None:
    """Write .spaces/roadmap.json — human-readable snapshot of the SQLite roadmap.

    This file is NOT the source of truth (SQLite is), but exists for:
    - Human inspection and debugging
    - LLM context injection without querying the DB
    - Offline tools and editors
    """
    out = space_dir / ".spaces" / "roadmap.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(
        roadmap.model_dump_json(indent=2),
        encoding="utf-8",
    )
    log.debug("roadmap_json_written", path=str(out))


async def discover_custom_domain(
    background: str,
    goal: str,
    extra_context: str = "",
) -> dict:
    """
    For CUSTOM spaces: LLM-based collaborative domain discovery.

    Returns dict with:
      - domain_name: str
      - description: str
      - suggested_goal: str
      - clarifying_questions: list[str]
      - concept_outline: list[str]   — top-level themes for roadmap seeding
      - workspace_folders: list[str]
      - recommended_tools: list[dict]
    """
    import json
    from sarthak.features.ai.agents._base import run_llm

    system = (
        "You are an expert learning architect. A user is creating a custom learning space. "
        "Understand what they want to learn and design a personalised, domain-specific space.\n\n"
        "Output ONLY valid JSON (no prose, no markdown fences):\n"
        "{\n"
        '  "domain_name": "Clear, specific domain name (e.g. Bhagavad Gita: Philosophy & Application)",\n'
        '  "description": "1-2 sentences about this learning space",\n'
        '  "suggested_goal": "Refined, specific version of their goal",\n'
        '  "clarifying_questions": ["question1", "question2"],\n'
        '  "concept_outline": ["Major theme 1", "Major theme 2", "Major theme 3", "Major theme 4", "Major theme 5"],\n'
        '  "workspace_folders": ["folder1", "folder2", "folder3", "folder4"],\n'
        '  "recommended_tools": [{"name": "tool", "purpose": "why", "install": "how"}]\n'
        "}\n\n"
        "Rules:\n"
        "- domain_name must clearly reflect the actual subject (never generic like Custom Space)\n"
        "- concept_outline: 5 major themes specific to THIS domain (not generic like Foundation)\n"
        "- workspace_folders: 4-6 folders that make sense FOR THIS domain specifically\n"
        "- recommended_tools: only tools that genuinely help this domain (0-5); "
        "do NOT recommend data science tools for non-technical domains\n"
        "- clarifying_questions: only 2 questions that would significantly change the roadmap"
    )

    user = (
        f"Background: {background or 'not specified'}\n"
        f"Goal: {goal or 'not specified'}\n"
        + (f"Additional context: {extra_context}\n" if extra_context else "")
    )

    fallback = {
        "domain_name": goal or "Custom Learning Space",
        "description": f"A personalised learning space focused on: {goal}",
        "suggested_goal": goal,
        "clarifying_questions": [
            "What is your current familiarity with this subject?",
            "What specific outcome would make this learning a success for you?",
        ],
        "concept_outline": [
            "Historical & Cultural Context",
            "Core Teachings",
            "Philosophical Concepts",
            "Practical Application",
            "Integration with Modern Life",
        ],
        "workspace_folders": ["notes", "resources", "reflections", "projects"],
        "recommended_tools": [],
    }

    from sarthak.features.ai.agents._base import parse_json_response
    raw = await run_llm(system, user)
    try:
        return parse_json_response(raw)
    except Exception:
        log.warning("discover_custom_domain_parse_failed", raw=raw[:200])
        return fallback


async def refine_roadmap(
    space_dir: Path,
    profile,  # SpaceProfile
    clarification_answers: str,
) -> bool:
    """
    Regenerate the roadmap incorporating user answers to clarifying questions.

    Accepts free-form text answers that refine the goal/scope/approach.
    Forces regeneration even if a roadmap already exists.
    Returns True on success.
    """
    if clarification_answers.strip():
        # Enrich the profile goal with the user's answers so the LLM uses them (transient only)
        refined_goal = f"{profile.learner.goal}\n\nRefinement: {clarification_answers.strip()}"
        profile = profile.model_copy(update={"learner": profile.learner.model_copy(
            update={"goal": refined_goal}
        )})
        # Do NOT persist the refined_goal — the original goal stays clean in the store;

    return await ensure_roadmap(space_dir, profile, force=True)
