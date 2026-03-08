"""
Sarthak Spaces — Auto-reindex watcher (Feature 1).

Uses `watchfiles` to monitor a space directory for changes. On any text-file
save, re-embeds only the changed file's chunks into sqlite-vec. No manual sync needed.

Usage (called from router startup / CLI):
    watcher = SpaceWatcher(space_dir)
    await watcher.start()          # non-blocking background task
    await watcher.stop()
"""
from __future__ import annotations

import asyncio
from pathlib import Path

from sarthak.core.logging import get_logger

log = get_logger(__name__)

_TEXT_EXTS = {
    ".txt", ".md", ".rst", ".py", ".js", ".ts", ".json", ".toml", ".yaml",
    ".yml", ".csv", ".html", ".xml", ".sh", ".r", ".ipynb", ".tex",
}
_DEBOUNCE_SECS = 2.0


class SpaceWatcher:
    """Background task: watches space_dir, re-indexes changed files via sqlite-vec."""

    def __init__(self, space_dir: Path) -> None:
        self._dir   = space_dir
        self._task: asyncio.Task | None = None
        self._stop  = asyncio.Event()

    async def start(self) -> None:
        if self._task and not self._task.done():
            return
        self._stop.clear()
        self._task = asyncio.create_task(self._run(), name=f"watcher:{self._dir.name}")
        log.info("watcher_started", dir=str(self._dir))

    async def stop(self) -> None:
        self._stop.set()
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
        log.info("watcher_stopped", dir=str(self._dir))

    async def _run(self) -> None:
        try:
            from watchfiles import Change, awatch
        except ImportError:
            log.warning("watchfiles_missing", hint="uv add watchfiles")
            return

        pending: set[Path] = set()
        flush_task: asyncio.Task | None = None

        async def _flush() -> None:
            await asyncio.sleep(_DEBOUNCE_SECS)
            if not pending:
                return
            paths = list(pending)
            pending.clear()
            await self._reindex(paths)

        skip_dirs = {".spaces", ".git", "__pycache__", "node_modules", ".venv"}

        async for changes in awatch(str(self._dir), stop_event=self._stop):
            for change, path_str in changes:
                path = Path(path_str)
                if change not in (Change.modified, Change.added):
                    continue
                if any(p in skip_dirs for p in path.parts[len(self._dir.parts):]):
                    continue
                if path.suffix.lower() not in _TEXT_EXTS:
                    continue
                pending.add(path)

            if flush_task is None or flush_task.done():
                flush_task = asyncio.create_task(_flush())

    async def _reindex(self, paths: list[Path]) -> None:
        from .rag import index_space
        try:
            n = await index_space(self._dir, incremental=True)
            log.info("watcher_reindexed", files=len(paths), chunks=n)
        except Exception as exc:
            log.warning("watcher_reindex_error", error=str(exc))


# ── Global registry: one watcher per active space dir ─────────────────────────

_watchers: dict[str, SpaceWatcher] = {}


async def ensure_watcher(space_dir: Path) -> SpaceWatcher:
    key = str(space_dir.resolve())
    if key not in _watchers:
        w = SpaceWatcher(space_dir)
        await w.start()
        _watchers[key] = w
    return _watchers[key]


async def stop_all() -> None:
    for w in _watchers.values():
        await w.stop()
    _watchers.clear()
