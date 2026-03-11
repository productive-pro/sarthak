"""
sarthak storage CLI — manage storage backends and run migrations.

Commands:
    sarthak storage status          — show active backends
    sarthak storage migrate         — migrate data between backends
    sarthak storage benchmark       — run a quick read/write benchmark
"""
from __future__ import annotations

import asyncio
import time

import click


@click.group("storage")
def storage_cli() -> None:
    """Storage backend management and migration."""


@storage_cli.command("status")
def cmd_status() -> None:
    """Show active storage and cache backends."""
    async def _run() -> None:
        from sarthak.storage.migrate import status
        info = await status()
        click.echo("Storage Status")
        click.echo("─" * 30)
        for k, v in info.items():
            click.echo(f"  {k}: {v}")
    asyncio.run(_run())


@storage_cli.command("migrate")
@click.option("--to", "to_backend", required=True,
              type=click.Choice(["sqlite", "postgres", "duckdb"]),
              help="Destination backend.")
@click.option("--from", "from_backend", default="sqlite",
              type=click.Choice(["sqlite", "postgres", "duckdb"]),
              show_default=True, help="Source backend.")
@click.option("--batch-size", default=500, show_default=True,
              help="Rows per batch.")
def cmd_migrate(to_backend: str, from_backend: str, batch_size: int) -> None:
    """Migrate user_activity data between storage backends."""
    if from_backend == to_backend:
        click.echo("Source and destination are the same — nothing to do.", err=True)
        return

    async def _run() -> None:
        from sarthak.core.config import load_config
        from sarthak.storage.migrate import migrate_activity

        cfg = load_config().get("storage", {})
        click.echo(f"Migrating {from_backend} → {to_backend} …")
        report = await migrate_activity(
            from_backend=from_backend,
            to_backend=to_backend,
            cfg=cfg,
            batch_size=batch_size,
        )
        click.echo(str(report))
        if report.errors:
            click.echo("Errors (first 5):")
            for e in report.errors[:5]:
                click.echo(f"  {e}", err=True)

    asyncio.run(_run())


@storage_cli.command("benchmark")
@click.option("--rows", default=1000, show_default=True,
              help="Number of test rows to insert then query.")
def cmd_benchmark(rows: int) -> None:
    """Quick read/write benchmark against the configured backend."""
    async def _run() -> None:
        from sarthak.storage.factory import get_activity_repo
        repo = get_activity_repo()
        click.echo(f"Benchmarking {type(repo).__name__} with {rows} rows …")

        t0 = time.monotonic()
        tasks = [
            repo.write(
                activity_type="code_run",
                space_dir="/tmp/bench",
                concept_title=f"concept_{i % 10}",
                session_id="bench",
                metadata={"success": i % 3 != 0},
            )
            for i in range(rows)
        ]
        await asyncio.gather(*tasks)
        write_s = time.monotonic() - t0
        click.echo(f"  Write {rows} rows: {write_s:.2f}s ({rows/write_s:.0f} rows/s)")

        t1 = time.monotonic()
        await repo.summary("/tmp/bench", days=1)
        read_s = time.monotonic() - t1
        click.echo(f"  Summary query:   {read_s*1000:.1f} ms")

    asyncio.run(_run())
