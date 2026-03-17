"""
Sarthak AI — Agents CLI sub-commands.

Two agent types:
  System agents  — global, not tied to any space.
                   Created with: sarthak agents create --system "<description>"
  Space agents   — scoped to a space directory.
                   Created with: sarthak agents create --space --dir <path> "<description>"
"""
from __future__ import annotations

import click


@click.group()
def agents() -> None:
    """Sarthak Agents — create and manage scheduled automation agents."""


@agents.command("create")
@click.argument("description")
@click.option(
    "--system", "agent_type", flag_value="system", default=True,
    help="Create a global system agent (default)",
)
@click.option(
    "--space", "agent_type", flag_value="space",
    help="Create a space-scoped agent (requires --dir)",
)
@click.option("--dir", "directory", default="",
              help="Space directory — required when creating a space agent")
@click.option("--telegram", "notify_telegram", is_flag=True, default=False,
              help="Send results to Telegram")
def agents_create(
    description: str, agent_type: str, directory: str, notify_telegram: bool
) -> None:
    """Create a new agent from a natural-language description.

    \b
    Examples:
      # System agent (global)
      sarthak agents create --system "Every morning, search for AI news and summarise"

      # Space agent
      sarthak agents create --space --dir ~/my-space "Daily summary of my notes"
    """
    import asyncio
    from pathlib import Path
    from sarthak.agents.creator import create_agent_from_description
    from sarthak.agents.models import AgentScope

    if agent_type == "space" and not directory:
        raise click.ClickException(
            "Space agents require --dir <space_directory>. "
            "Use --system to create a global agent instead."
        )

    scope = AgentScope.SPACE if agent_type == "space" else AgentScope.GLOBAL
    space_dir = Path(directory).resolve() if directory else None

    async def _run():
        spec = await create_agent_from_description(
            description,
            scope=scope,
            space_dir=space_dir,
            notify_telegram=notify_telegram or None,
        )
        click.secho(f"✓ Agent created: {spec.name}", fg="green")
        click.echo(f"  ID:       {spec.agent_id}")
        click.echo(f"  Type:     {spec.scope.value}")
        click.echo(f"  Schedule: {spec.schedule}")
        click.echo(f"  Tools:    {', '.join(t.value for t in spec.tools) or 'none'}")
        click.echo(f"  Telegram: {spec.notify_telegram}")
        click.echo(f"  Next run: {spec.next_run_at[:19] if spec.next_run_at else 'unknown'}")
        if spec.scope.value == "space":
            click.echo(f"  Space:    {spec.space_dir}")

    asyncio.run(_run())


@agents.command("list")
@click.option(
    "--system", "filter_type", flag_value="system",
    help="Show only system (global) agents",
)
@click.option(
    "--space", "filter_type", flag_value="space",
    help="Show only space agents",
)
@click.option("--dir", "directory", default="",
              help="Filter space agents by directory")
def agents_list(filter_type: str, directory: str) -> None:
    """List known agents.

    \b
    Examples:
      sarthak agents list              # all agents
      sarthak agents list --system     # system agents only
      sarthak agents list --space      # all space agents
      sarthak agents list --dir ~/ws   # space agents for one space
    """
    from pathlib import Path
    from sarthak.agents.models import AgentScope
    from sarthak.agents.store import list_agents

    space_dir = Path(directory).resolve() if directory else None
    scope_filter = None
    if filter_type == "system":
        scope_filter = AgentScope.GLOBAL
    elif filter_type == "space":
        scope_filter = AgentScope.SPACE

    all_agents = list_agents(space_dir=space_dir, scope=scope_filter)
    if not all_agents:
        click.echo("No agents found.")
        return

    for spec in all_agents:
        status = "enabled" if spec.enabled else "disabled"
        type_tag = f"[{spec.scope.value}]"
        space_tag = f" → {spec.space_dir}" if spec.space_dir else ""
        click.echo(f"{'●' if spec.enabled else '○'} {spec.agent_id}  {spec.name}  {type_tag}{space_tag}")
        click.echo(f"    Schedule: {spec.schedule}  Status: {status}")
        if spec.last_run_at:
            click.echo(f"    Last run: {spec.last_run_at[:19]}")


@agents.command("run")
@click.argument("agent_id")
def agents_run(agent_id: str) -> None:
    """Run an agent immediately (ignores schedule)."""
    import asyncio
    from sarthak.agents.runner import run_agent
    from sarthak.agents.store import load_agent

    spec = load_agent(agent_id)
    if not spec:
        raise click.ClickException(f"Agent not found: {agent_id}")

    async def _run():
        click.echo(f"Running {spec.scope.value} agent '{spec.name}'...")
        run = await run_agent(spec)
        if run.success:
            click.secho(f"✓ Done (run {run.run_id})", fg="green")
            click.echo(run.output[:2000])
        else:
            click.secho(f"✗ Failed: {run.error}", fg="red")

    asyncio.run(_run())


@agents.command("logs")
@click.argument("agent_id")
@click.option("--limit", default=5, show_default=True, help="Number of recent runs")
def agents_logs(agent_id: str, limit: int) -> None:
    """Show recent run history for an agent."""
    from sarthak.agents.store import load_agent, load_runs
    spec = load_agent(agent_id)
    if not spec:
        raise click.ClickException(f"Agent not found: {agent_id}")
    runs = load_runs(agent_id, limit=limit)
    if not runs:
        click.echo("No runs yet.")
        return
    for r in runs:
        icon = "✓" if r.success else "✗"
        click.echo(f"{icon} [{r.run_id}] {r.started_at[:19]}")
        if r.output:
            click.echo(r.output[:500])
        if r.error:
            click.secho(f"  Error: {r.error}", fg="red")
        click.echo()


@agents.command("delete")
@click.argument("agent_id")
@click.option("--force", is_flag=True, help="Skip confirmation prompt")
def agents_delete(agent_id: str, force: bool) -> None:
    """Delete an agent by ID."""
    from sarthak.agents.store import delete_agent
    if not force:
        click.confirm(f"Delete agent '{agent_id}'?", abort=True)
    if delete_agent(agent_id):
        click.secho(f"✓ Deleted: {agent_id}", fg="green")
    else:
        raise click.ClickException(f"Agent not found: {agent_id}")


@agents.command("enable")
@click.argument("agent_id")
def agents_enable(agent_id: str) -> None:
    """Enable a disabled agent."""
    from sarthak.agents.store import update_agent
    spec = update_agent(agent_id, enabled=True)
    if spec:
        click.secho(f"✓ Enabled: {spec.name} [{spec.scope.value}]", fg="green")
    else:
        raise click.ClickException(f"Agent not found: {agent_id}")


@agents.command("disable")
@click.argument("agent_id")
def agents_disable(agent_id: str) -> None:
    """Disable an agent (keeps schedule, skips execution)."""
    from sarthak.agents.store import update_agent
    spec = update_agent(agent_id, enabled=False)
    if spec:
        click.secho(f"✓ Disabled: {spec.name} [{spec.scope.value}]", fg="yellow")
    else:
        raise click.ClickException(f"Agent not found: {agent_id}")
