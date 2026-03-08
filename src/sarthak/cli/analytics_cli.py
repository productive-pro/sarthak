"""
Sarthak AI — Analytics CLI sub-commands.
"""
from __future__ import annotations

import click


@click.command()
def resume() -> None:
    """Resume card: recent Spaces session summary."""
    import asyncio
    from pathlib import Path
    from sarthak.spaces.store import list_spaces
    from sarthak.spaces.session_tracker import load_sessions

    async def _run():
        try:
            spaces = list_spaces()
            for space in spaces:
                d = Path(space.get("directory", ""))
                if not d.exists():
                    continue
                sessions = load_sessions(d, limit=1)
                if sessions:
                    s = sessions[-1]
                    click.echo(
                        f"Last space : {space.get('name', d.name)} — "
                        f"{s.concept} ({s.signals.active_seconds // 60} min active)"
                    )
                    break
        except Exception:
            pass

    asyncio.run(_run())
