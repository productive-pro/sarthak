"""
Sarthak AI — Agents CLI sub-commands.
All `sarthak agents` commands live here.
"""
from __future__ import annotations

import click


@click.group()
def agents() -> None:
    """Sarthak Agents — create and manage scheduled automation agents."""


@agents.command("create")
@click.argument("description")
@click.option("--dir", "directory", default="", help="Space directory (scopes agent to that space)")
@click.option("--telegram", "notify_telegram", is_flag=True, default=False,
              help="Send results to Telegram")
def agents_create(description: str, directory: str, notify_telegram: bool) -> None:
    """Create a new agent from a natural-language description."""
    import asyncio
    from pathlib import Path
    from sarthak.agents.creator import create_agent_from_description

    space_dir = Path(directory).resolve() if directory else None

    async def _run():
        spec = await create_agent_from_description(
            description, space_dir=space_dir,
            notify_telegram=notify_telegram or None,
        )
        click.secho(f"✓ Agent created: {spec.name}", fg="green")
        click.echo(f"  ID:       {spec.agent_id}")
        click.echo(f"  Schedule: {spec.schedule}")
        click.echo(f"  Tools:    {', '.join(t.value for t in spec.tools) or 'none'}")
        click.echo(f"  Telegram: {spec.notify_telegram}")
        click.echo(f"  Next run: {spec.next_run_at[:19] if spec.next_run_at else 'unknown'}")
        if spec.scope.value == 'space':
            click.echo(f"  Space:    {spec.space_dir}")

    asyncio.run(_run())


@agents.command("list")
@click.option("--dir", "directory", default="", help="Filter by space directory")
def agents_list(directory: str) -> None:
    """List all known agents."""
    from pathlib import Path
    from sarthak.agents.store import list_agents

    space_dir = Path(directory).resolve() if directory else None
    all_agents = list_agents(space_dir)
    if not all_agents:
        click.echo("No agents found. Run: sarthak agents create '<description>'")
        return
    for spec in all_agents:
        status = "enabled" if spec.enabled else "disabled"
        scope  = f"[{spec.scope.value}]" + (f" {spec.space_dir}" if spec.space_dir else "")
        click.echo(f"{'●' if spec.enabled else '○'} {spec.agent_id}  {spec.name}")
        click.echo(f"    Schedule: {spec.schedule}  Status: {status}  {scope}")
        if spec.last_run_at:
            click.echo(f"    Last run: {spec.last_run_at[:19]}")


@agents.command("run")
@click.argument("agent_id")
def agents_run(agent_id: str) -> None:
    """Run an agent immediately (ignores schedule)."""
    import asyncio
    from sarthak.agents.store import load_agent
    from sarthak.agents.runner import run_agent

    spec = load_agent(agent_id)
    if not spec:
        raise click.ClickException(f"Agent not found: {agent_id}")

    async def _run():
        click.echo(f"Running agent '{spec.name}'...")
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
@click.option("--force", is_flag=True)
def agents_delete(agent_id: str, force: bool) -> None:
    """Delete an agent."""
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
        click.secho(f"✓ Enabled: {spec.name}", fg="green")
    else:
        raise click.ClickException(f"Agent not found: {agent_id}")


@agents.command("disable")
@click.argument("agent_id")
def agents_disable(agent_id: str) -> None:
    """Disable an agent (keeps schedule, skips execution)."""
    from sarthak.agents.store import update_agent
    spec = update_agent(agent_id, enabled=False)
    if spec:
        click.secho(f"✓ Disabled: {spec.name}", fg="yellow")
    else:
        raise click.ClickException(f"Agent not found: {agent_id}")
