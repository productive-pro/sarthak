"""
Sarthak AI — Spaces CLI sub-commands.
All `sarthak spaces` commands live here.
"""
from __future__ import annotations

import click


@click.group()
def spaces() -> None:
    """Sarthak Spaces — mastery engine. Learn any skill like an expert."""


async def _generate_and_save_roadmap(ws_dir, profile, background: str = "") -> None:
    """Generate roadmap and persist to .spaces/sarthak.db (delegates to ensure_roadmap)."""
    from sarthak.spaces.roadmap_init import ensure_roadmap
    generated = await ensure_roadmap(ws_dir, profile)
    if generated:
        click.echo(f"  Roadmap   : generated and saved to .spaces/sarthak.db")
        click.echo(f"  View at   : http://localhost:8000/roadmap?space={profile.domain}")


@spaces.command("init")
@click.option("--dir", "directory", default=".", help="Space directory")
@click.option("--type", "space_type", default="data_science",
              type=click.Choice(["data_science", "ai_engineering", "medicine", "education",
                                 "exam_prep", "business", "research", "custom"]),
              help="Type of space")
@click.option("--background", default="", help="Your background")
@click.option("--goal", default="", help="Your learning goal")
@click.option("--name", default="", help="Your name (for personalization)")
@click.option("--no-roadmap", is_flag=True, default=False, help="Skip AI roadmap generation")
def spaces_init(
    directory: str, space_type: str, background: str, goal: str, name: str, no_roadmap: bool
) -> None:
    """Initialize a Sarthak Space for mastery learning."""
    import asyncio
    from pathlib import Path
    from sarthak.spaces.models import SpaceType
    from sarthak.spaces.store import load_space, init_space, init_space_profile
    from sarthak.spaces.workspace_transformer import WorkspaceTransformer

    ws_dir = Path(directory).resolve()
    st = SpaceType(space_type)

    # For CUSTOM spaces: run domain discovery so we get the right domain + tools
    domain_name = ""
    recommended_tools = None
    discovery: dict = {}
    if st == SpaceType.CUSTOM and (background or goal):
        async def _discover():
            from sarthak.spaces.roadmap_init import discover_custom_domain
            return await discover_custom_domain(background=background, goal=goal)
        discovery = asyncio.run(_discover())
        domain_name = discovery.get("domain_name", "")
        goal = discovery.get("suggested_goal", goal)
        if discovery.get("clarifying_questions"):
            click.echo("\nTo refine your roadmap, consider these questions:")
            for q in discovery["clarifying_questions"]:
                click.echo(f"  • {q}")
        from sarthak.spaces.models import ToolRecommendation
        recommended_tools = [
            ToolRecommendation(name=t["name"], purpose=t.get("purpose", ""), install_linux=t.get("install", ""))
            for t in discovery.get("recommended_tools", []) if t.get("name")
        ]

    domain_label = domain_name or st.value.replace("_", " ").title()
    if not load_space(ws_dir):
        init_space(
            ws_dir,
            name=name or domain_label,
            description=f"Sarthak Space: {domain_label}",
            goal=goal or f"Mastery in {domain_label}",
        )

    profile = init_space_profile(
        ws_dir, st,
        background=background,
        learner_name=name,
        goal=goal,
        domain_name=domain_name,
        recommended_tools=recommended_tools,
    )
    extra_dirs = discovery.get("workspace_folders", []) if st == SpaceType.CUSTOM and (background or goal) else []
    transformer = WorkspaceTransformer(ws_dir)
    created = transformer.transform(st, extra_dirs=extra_dirs)

    click.echo(f"✓ Sarthak Space initialized: {profile.domain}")
    click.echo(f"  Directory : {ws_dir}")
    click.echo(f"  Files     : {len(created)} created")

    if not no_roadmap:
        click.echo("  Generating AI roadmap… (this may take ~15s)")
        asyncio.run(_generate_and_save_roadmap(ws_dir, profile))

    click.echo(f"\nNext: sarthak spaces session --dir {directory}")


@spaces.command("learn")
@click.option("--dir", "directory", default=".", help="Workspace directory")
@click.option("--reshape", is_flag=True, default=False, help="Reshape workspace to expert structure")
def spaces_session(directory: str, reshape: bool) -> None:
    """Run a quick learning session — get your next concept, math, and task (no tracking)."""
    import asyncio
    from pathlib import Path
    from sarthak.spaces.orchestrator import SpacesOrchestrator

    async def _run():
        orch = SpacesOrchestrator(Path(directory).resolve())
        result = await orch.next_session(reshape_workspace=reshape)
        click.echo(result.reply)
        if result.xp_earned:
            click.echo(f"\n+{result.xp_earned} XP earned")
        if result.workspace_changes:
            click.echo(f"{len(result.workspace_changes)} workspace files created")

    asyncio.run(_run())


@spaces.command("status")
@click.option("--dir", "directory", default=".", help="Workspace directory")
def spaces_status(directory: str) -> None:
    """Show your current mastery status."""
    from pathlib import Path
    from sarthak.spaces.orchestrator import SpacesOrchestrator
    orch = SpacesOrchestrator(Path(directory).resolve())
    click.echo(orch.get_status())


@spaces.command("setup")
@click.option("--dir", "directory", default=".", help="Workspace directory")
def spaces_setup(directory: str) -> None:
    """Scan environment and set up expert tools for this space."""
    import asyncio
    from pathlib import Path
    from sarthak.spaces.orchestrator import SpacesOrchestrator

    async def _run():
        orch = SpacesOrchestrator(Path(directory).resolve())
        result = await orch.setup_environment()
        click.echo(result.reply)

    asyncio.run(_run())


@spaces.command("evaluate")
@click.argument("concept")
@click.option("--dir", "directory", default=".", help="Workspace directory")
@click.option("--file", "submission_file", default="", help="File path of submission to evaluate")
def spaces_evaluate(concept: str, directory: str, submission_file: str) -> None:
    """Evaluate your work on a concept and update your mastery."""
    import asyncio
    from pathlib import Path
    from sarthak.spaces.orchestrator import SpacesOrchestrator

    submission = ""
    if submission_file:
        try:
            submission = Path(submission_file).read_text(encoding="utf-8")
        except Exception as e:
            click.echo(f"Could not read file: {e}", err=True)
            return
    else:
        click.echo("Paste your submission (Ctrl+D to finish):")
        submission = click.get_text_stream("stdin").read()

    async def _run():
        orch = SpacesOrchestrator(Path(directory).resolve())
        result = await orch.evaluate(concept, f"Practice: {concept}", submission)
        click.echo(result.reply)

    asyncio.run(_run())


@spaces.command("project")
@click.option("--dir", "directory", default=".", help="Workspace directory")
@click.option("--id", "project_id", default="", help="Project ID to start (optional)")
def spaces_project(directory: str, project_id: str) -> None:
    """Scaffold a real end-to-end project and build something tangible."""
    import asyncio
    from pathlib import Path
    from sarthak.spaces.orchestrator import SpacesOrchestrator

    async def _run():
        orch = SpacesOrchestrator(Path(directory).resolve())
        result = await orch.start_project(project_id=project_id or None)
        click.echo(result.reply)
        if result.workspace_changes:
            click.echo(f"\n{len(result.workspace_changes)} files created")

    asyncio.run(_run())


@spaces.command("quick")
@click.option("--dir", "directory", default=".", help="Workspace directory")
def spaces_quick(directory: str) -> None:
    """5-minute micro-task. Perfect for busy days — consistency beats intensity."""
    import asyncio
    from pathlib import Path
    from sarthak.spaces.orchestrator import SpacesOrchestrator

    async def _run():
        orch = SpacesOrchestrator(Path(directory).resolve())
        result = await orch.quicktest()
        click.echo(result.reply)

    asyncio.run(_run())


@spaces.command("profile")
@click.option("--dir", "directory", default=".", help="Workspace directory")
@click.option("--background", default="", help="Your background")
@click.option("--goal", default="", help="Your learning goal")
@click.option("--name", default="", help="Your name")
def spaces_profile(directory: str, background: str, goal: str, name: str) -> None:
    """Update your learner profile for better personalization."""
    from pathlib import Path
    from sarthak.spaces.orchestrator import SpacesOrchestrator
    orch = SpacesOrchestrator(Path(directory).resolve())
    kwargs = {k: v for k, v in [("background", background), ("goal", goal), ("name", name)] if v}
    if not kwargs:
        click.echo("Provide at least one of: --background, --goal, --name")
        return
    orch.update_learner(**kwargs)
    click.echo("Profile updated.")
    click.echo(orch.get_status())


@spaces.command("refine")
@click.option("--dir", "directory", default=".", help="Workspace directory")
@click.option("--answers", default="", help="Your answers to the clarifying questions (inline)")
def spaces_refine(directory: str, answers: str) -> None:
    """Answer the space's clarifying questions to refine and regenerate the roadmap.

    Run after `sarthak spaces init` when you see clarifying questions printed.
    Paste your answers inline with --answers or interactively via stdin.

    Example:
      sarthak spaces refine --dir . --answers "I am a complete beginner, focusing on practical application"
    """
    import asyncio
    from pathlib import Path
    from sarthak.spaces.roadmap_init import refine_roadmap
    from sarthak.spaces.store import load_profile

    ws_dir = Path(directory).resolve()
    profile = load_profile(ws_dir)
    if profile is None:
        click.echo("Error: No space found. Run: sarthak spaces init", err=True)
        return

    if not answers:
        click.echo("Answer the clarifying questions below (Ctrl+D when done):")
        answers = click.get_text_stream("stdin").read()

    if not answers.strip():
        click.echo("No answers provided — roadmap unchanged.")
        return

    click.echo("Regenerating roadmap with your answers… (this may take ~20s)")

    async def _run():
        return await refine_roadmap(ws_dir, profile, answers)

    ok = asyncio.run(_run())
    if ok:
        click.echo("✓ Roadmap refined and saved to .spaces/sarthak.db and .spaces/roadmap.json")
    else:
        click.echo("Roadmap regeneration failed — check logs for details.", err=True)


@spaces.command("list")
def spaces_list() -> None:
    """List all known Sarthak spaces."""
    from sarthak.spaces.store import list_spaces, get_active_space
    all_spaces = list_spaces()
    active = get_active_space()
    active_dir = active.get("directory") if active else None
    if not all_spaces:
        click.echo("No spaces found. Run: sarthak spaces init")
        return
    for s in all_spaces:
        marker = " *" if s.get("directory") == active_dir else ""
        click.echo(f"{s.get('name', '?')} [{s.get('directory', '?')}]{marker}")
        if s.get("goal"):
            click.echo(f"  Goal: {s['goal']}")


@spaces.command("activate")
@click.option("--dir", "directory", default=".", help="Space directory")
def spaces_activate(directory: str) -> None:
    """Set a space as the active context."""
    from pathlib import Path
    from sarthak.spaces.store import set_active_space
    ws = set_active_space(Path(directory).resolve())
    click.echo(f"Active space: {ws.get('name', 'space')}")


@spaces.command("context")
@click.option("--dir", "directory", default="", help="Space directory (default: cwd)")
def spaces_context(directory: str) -> None:
    """Print the active space context summary."""
    from pathlib import Path
    from sarthak.spaces.store import get_space_context
    ctx = get_space_context(Path(directory).resolve() if directory else None)
    click.echo(ctx or "No active space found. Run: sarthak spaces init")


@spaces.command("rag")
@click.argument("action", type=click.Choice(["index", "search", "status", "watch"]))
@click.option("--dir", "directory", default=".", help="Space directory")
@click.option("--query", "query", default="", help="Search query (for 'search' action)")
@click.option("--full", is_flag=True, default=False, help="Full re-index (ignore mtimes)")
@click.option("--top-k", default=5, show_default=True, help="Results to return (for 'search')")
def spaces_rag(action: str, directory: str, query: str, full: bool, top_k: int) -> None:
    """
    RAG (Retrieval-Augmented Generation) index management.

    \b
    Actions:
      index   - Index / re-index workspace files into vector DB
      search  - Search the index (requires --query)
      status  - Show index status (doc count, files tracked)
      watch   - Start watchdog auto-indexer (runs until Ctrl+C)

    \b
    Examples:
      sarthak spaces rag index --dir ~/my-space
      sarthak spaces rag search --dir ~/my-space --query "numpy array operations"
      sarthak spaces rag status --dir ~/my-space
      sarthak spaces rag watch  --dir ~/my-space
    """
    import asyncio
    import time as _time
    from pathlib import Path
    from sarthak.spaces.rag import index_space, search_space, rag_status, start_watcher, stop_watcher

    ws_dir = Path(directory).resolve()

    if action == "index":
        click.echo(f"Indexing {ws_dir} {'(full)' if full else '(incremental)'}...")
        try:
            n = asyncio.run(index_space(ws_dir, incremental=not full))
            if n == 0:
                click.secho("✓ Nothing to update (all files up to date).", fg="green")
            else:
                click.secho(f"✓ Indexed {n} chunks.", fg="green")
        except RuntimeError as exc:
            raise click.ClickException(str(exc))

    elif action == "search":
        if not query:
            raise click.ClickException("Provide --query for search.")
        result = asyncio.run(search_space(ws_dir, query, top_k=top_k))
        click.echo(result)

    elif action == "status":
        status = rag_status(ws_dir)
        if not status["enabled"]:
            click.secho("RAG index: not initialized", fg="yellow")
            click.echo(f"  Run: sarthak spaces rag index --dir {directory}")
        else:
            click.secho("RAG index: active", fg="green")
            click.echo(f"  Chunks:        {status['indexed_chunks']}")
            click.echo(f"  Files tracked: {status['indexed_files']}")
            click.echo(f"  DB size:       {status['db_size_kb']} KB")
            click.echo(f"  DB path:       {status['db_path']}")

    elif action == "watch":
        click.echo(f"Starting RAG watcher for {ws_dir} (Ctrl+C to stop)...")
        observer = start_watcher(ws_dir)
        if observer is None:
            raise click.ClickException("watchdog not installed. Run: uv add watchdog")
        try:
            while True:
                _time.sleep(1)
        except KeyboardInterrupt:
            click.echo("\nStopping watcher...")
        finally:
            stop_watcher(observer)
            click.secho("✓ Watcher stopped.", fg="green")


# ── Practice commands ────────────────────────────────────────────────────────

@spaces.command("practice")
@click.option("--dir", "directory", default=".", help="Workspace directory")
@click.option("--type", "test_type",
              type=click.Choice(["concept", "topic", "full_space"]),
              default="concept", show_default=True,
              help="Scope of the test")
@click.option("--scope", default="",
              help="Concept/topic name to test (required for concept/topic tests)")
@click.option("--source",
              type=click.Choice(["llm", "rag", "prompt"]),
              default="llm", show_default=True,
              help="Question source: LLM-generated, from your space files, or custom prompt")
@click.option("--prompt", "source_prompt", default="",
              help="Custom prompt for question generation (used with --source prompt)")
@click.option("--questions", "n_questions", type=int, default=None,
              help="Number of questions (auto-selected if omitted)")
@click.option("--time", "seconds_per_question", type=int, default=120,
              show_default=True, help="Seconds allowed per question")
def spaces_practice(
    directory: str,
    test_type: str,
    scope: str,
    source: str,
    source_prompt: str,
    n_questions: int | None,
    seconds_per_question: int,
) -> None:
    """
    Run a timed practice test.

    \b
    Examples:
      # 8 questions on one concept, 2 min each, LLM-generated
      sarthak spaces practice --type concept --scope "gradient descent"

      # 15 questions from YOUR notes in the space folder
      sarthak spaces practice --type topic --scope beginner --source rag

      # Custom focus: tricky edge cases
      sarthak spaces practice --source prompt --prompt "Focus on common pitfalls in backpropagation"

      # Full exam simulation, 90 sec per question
      sarthak spaces practice --type full_space --time 90
    """
    import asyncio
    import time as _time
    from pathlib import Path
    from sarthak.spaces.orchestrator import SpacesOrchestrator

    _PRIORITY_LABELS = {"high": "[HIGH]", "medium": "[MED]", "low": "[LOW]"}

    ws_dir = Path(directory).resolve()

    async def _run():
        orch = SpacesOrchestrator(ws_dir)
        result = await orch.run_practice(
            test_type=test_type,
            scope=scope,
            source=source,
            source_prompt=source_prompt,
            n_questions=n_questions,
            seconds_per_question=seconds_per_question,
            interactive=True,
        )
        click.echo(result.reply)
        if result.xp_earned:
            click.echo(f"\n+{result.xp_earned} XP earned")
        if result.optimizations:
            click.echo("\n" + "-" * 50)
            for o in result.optimizations:
                label = _PRIORITY_LABELS.get(o.priority, "")
                click.echo(f"{label} {o.recommendation}")

    asyncio.run(_run())


@spaces.command("session")
@click.option("--dir", "directory", default=".", help="Workspace directory")
@click.option("--concept", default="",
              help="Concept to work on (auto-selected if omitted)")
@click.option("--minutes", "planned_minutes", type=int, default=30,
              show_default=True, help="Planned session length")
@click.option("--reshape", is_flag=True, default=False,
              help="Reshape workspace to expert structure before session")
@click.option("--type", "session_type",
              type=click.Choice(["new_concept", "review", "struggle_fix", "project_step"]),
              default="new_concept", show_default=True)
def spaces_tracked_session(
    directory: str,
    concept: str,
    planned_minutes: int,
    reshape: bool,
    session_type: str,
) -> None:
    """
    Start a tracked learning session.

    Tracks active time, file edits, git commits, and collects a
    3-question self-report at the end. Produces a SpaceSession record
    used by the optimizer to generate personalized recommendations.

    \b
    Examples:
      sarthak spaces session --concept "gradient descent" --minutes 45
      sarthak spaces session --type struggle_fix --concept "backpropagation"
    """
    import asyncio
    from pathlib import Path
    from sarthak.spaces.orchestrator import SpacesOrchestrator
    from sarthak.spaces.models import SelfReport

    ws_dir = Path(directory).resolve()

    async def _run():
        orch = SpacesOrchestrator(ws_dir)

        # Start session + get learning content
        result = await orch.next_session(
            reshape_workspace=reshape,
            planned_minutes=planned_minutes,
            concept_override=concept or None,
            track_session=True,
        )
        click.echo(result.reply)
        click.echo(f"\n⏱  Session tracking started. Planned: {planned_minutes} min.")
        click.echo("Work on the task above, then come back and press Enter to finish.")
        click.echo("(Ctrl+C to end without recording)\n")

        try:
            input()
        except (KeyboardInterrupt, EOFError):
            click.echo("\nSession ended without recording.")
            return

        # Self-report collection
        click.echo("\n── End of Session ──────────────────────────")
        completed = click.confirm("Did you finish the task?", default=True)
        rating = click.prompt(
            "Understanding rating (1=confused, 5=solid)",
            type=click.IntRange(1, 5), default=3,
        )
        stuck_raw = click.prompt(
            "Any concepts you got stuck on? (comma-separated, or Enter to skip)",
            default="", show_default=False,
        )
        breakthrough = click.prompt(
            "Any 'aha moment'? (optional)",
            default="", show_default=False,
        )

        stuck_list = [c.strip() for c in stuck_raw.split(",") if c.strip()]
        report = SelfReport(
            task_completed=completed,
            understanding_rating=rating,
            stuck_on=stuck_list,
            breakthrough=breakthrough,
        )

        # End tracked session and get optimizations
        end_result = await orch.end_session(report)
        click.echo(end_result.reply)
        if end_result.xp_earned:
            click.echo(f"\n+{end_result.xp_earned} XP earned")
        if end_result.optimizations:
            click.echo("\n── Insights ────────────────────────────────")
            for o in end_result.optimizations[:3]:
                icon = {"high": "🔴", "medium": "🟡", "low": "🟢"}.get(o.priority, "")
                click.echo(f"{icon} {o.recommendation}")

    asyncio.run(_run())


@spaces.command("optimize")
@click.option("--dir", "directory", default=".", help="Workspace directory")
@click.option("--last", "recent_n", type=int, default=10,
              show_default=True, help="Number of recent sessions to analyze")
def spaces_optimize(directory: str, recent_n: int) -> None:
    """
    Analyze your recent sessions and show personalized recommendations.

    Reads notes, test results, session self-reports, and proxy signals
    to surface the highest-impact optimizations.
    """
    import asyncio
    from pathlib import Path
    from sarthak.spaces.store import load_profile
    from sarthak.spaces.optimizer import SignalOptimizer
    from sarthak.spaces.learner_context import build_learner_context

    ws_dir  = Path(directory).resolve()
    profile = load_profile(ws_dir)
    if not profile:
        click.echo("No space found. Run: sarthak spaces init")
        return

    async def _run():
        lc = await build_learner_context(ws_dir, profile, days=recent_n * 2)
        optimizer = SignalOptimizer()
        opts = optimizer.analyze_from_context(ws_dir, profile, lc)
        click.echo(optimizer.format_optimizations(opts))

    asyncio.run(_run())


@spaces.command("resume")
def spaces_resume() -> None:
    """Resume card: recent Spaces session summary."""
    import asyncio
    from pathlib import Path
    from sarthak.spaces.store import list_spaces
    from sarthak.spaces.session_tracker import load_sessions

    async def _run():
        try:
            spaces_list = list_spaces()
            for space in spaces_list:
                d = Path(space.get("directory", ""))
                if not d.exists():
                    continue
                sessions = load_sessions(d, limit=1)
                if sessions:
                    s = sessions[-1]
                    click.echo(
                        f"Last space : {space.get('name', d.name)} - "
                        f"{s.concept} ({s.signals.active_seconds // 60} min active)"
                    )
                    break
        except Exception:
            pass

    asyncio.run(_run())


# ── Roadmap commands ──────────────────────────────────────────────────────────

@spaces.command("roadmap")
@click.option("--dir", "directory", default=".", help="Space directory")
@click.option("--regen", is_flag=True, default=False, help="Regenerate roadmap via LLM")
def spaces_roadmap(directory: str, regen: bool) -> None:
    """Show or regenerate the AI-generated curriculum roadmap."""
    import asyncio
    from pathlib import Path
    from sarthak.spaces.store import load_profile
    from sarthak.spaces.roadmap.db import RoadmapDB

    ws_dir = Path(directory).resolve()

    async def _run():
        db = RoadmapDB(ws_dir)
        await db.init()

        if regen:
            profile = load_profile(ws_dir)
            if not profile:
                raise click.ClickException("Space not initialized. Run: sarthak spaces init")
            click.echo("Regenerating roadmap via AI…")
            await _generate_and_save_roadmap(ws_dir, profile, profile.learner.background)
            return

        roadmap = await db.load_roadmap()
        if roadmap is None:
            click.secho("No roadmap yet. Run: sarthak spaces roadmap --regen", fg="yellow")
            return

        click.echo(f"\n🗺  Roadmap: {roadmap.space}\n")
        for ch in roadmap.chapters:
            pct = ch.compute_progress()
            bar = "█" * int(pct / 5) + "░" * (20 - int(pct / 5))
            click.echo(f"  [{bar}] {pct:5.1f}%  Ch{ch.order + 1}: {ch.title}")
            for tp in ch.topics:
                done = sum(1 for c in tp.concepts if c.status.value == "completed")
                click.echo(f"    ├─ {tp.title}  ({done}/{len(tp.concepts)} concepts)")

    asyncio.run(_run())


@spaces.command("roadmap-sync")
@click.option("--dir", "directory", default=".", help="Space directory")
def spaces_roadmap_sync(directory: str) -> None:
    """Index workspace files and rebuild RAG vectors for this space."""
    import asyncio
    from pathlib import Path
    from sarthak.spaces.roadmap.db import RoadmapDB
    from sarthak.spaces.rag import index_space

    async def _run():
        ws_dir = Path(directory).resolve()
        db = RoadmapDB(ws_dir)
        await db.init()
        file_count = await db.index_workspace_files()
        chunk_count = await index_space(ws_dir)
        click.echo(f"✓ Indexed {file_count} files, {chunk_count} RAG chunks")

    asyncio.run(_run())
