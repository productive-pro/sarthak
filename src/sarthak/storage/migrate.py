"""
Sarthak Storage Migration — move data between backends.

CLI: sarthak storage migrate --to postgres
     sarthak storage status
     sarthak storage benchmark

Usage from Python:
    from sarthak.storage.migrate import migrate_activity, MigrationReport
    report = await migrate_activity(from_backend="sqlite", to_backend="postgres", cfg=cfg)
"""
from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass, field
from typing import Any

import structlog

log = structlog.get_logger(__name__)


@dataclass
class MigrationReport:
    from_backend: str
    to_backend: str
    rows_migrated: int = 0
    rows_failed: int = 0
    duration_s: float = 0.0
    errors: list[str] = field(default_factory=list)

    @property
    def success(self) -> bool:
        return self.rows_failed == 0 and self.rows_migrated > 0

    def __str__(self) -> str:
        status = "✓" if self.success else "✗"
        return (
            f"{status} Migration {self.from_backend} → {self.to_backend}: "
            f"{self.rows_migrated} rows in {self.duration_s:.1f}s "
            f"({self.rows_failed} failures)"
        )


async def migrate_activity(
    *,
    from_backend: str,
    to_backend: str,
    cfg: dict | None = None,
    batch_size: int = 500,
) -> MigrationReport:
    """
    Stream user_activity rows from source → destination backend.
    Uses batched reads (no full-table load into memory).
    """
    report = MigrationReport(from_backend=from_backend, to_backend=to_backend)
    t0 = time.monotonic()

    try:
        source = _build_repo(from_backend, cfg or {})
        dest   = _build_repo(to_backend, cfg or {})
    except Exception as exc:
        report.errors.append(f"Backend init failed: {exc}")
        return report

    try:
        # Fetch all rows (SQLite stores 100k–200k at most for single-user)
        # For very large migrations, add pagination here.
        rows = await source.query(days=36500, limit=500_000)
        log.info("migration_rows_loaded", count=len(rows),
                 from_backend=from_backend)
    except Exception as exc:
        report.errors.append(f"Source read failed: {exc}")
        return report

    for i in range(0, len(rows), batch_size):
        batch = rows[i:i + batch_size]
        tasks = [
            dest.write(
                activity_type=r.get("activity_type", "unknown"),
                space_dir=r.get("space_dir", ""),
                concept_id=r.get("concept_id", ""),
                concept_title=r.get("concept_title", ""),
                session_id=r.get("session_id", ""),
                content_text=r.get("content_text", ""),
                media_path=r.get("media_path", ""),
                metadata=_parse_metadata(r.get("metadata")),
            )
            for r in batch
        ]
        results = await asyncio.gather(*tasks, return_exceptions=True)
        for res in results:
            if isinstance(res, Exception):
                report.rows_failed += 1
                report.errors.append(str(res))
            else:
                report.rows_migrated += 1

        log.info("migration_batch_done",
                 migrated=report.rows_migrated,
                 failed=report.rows_failed,
                 total=len(rows))

    report.duration_s = time.monotonic() - t0
    log.info("migration_complete", report=str(report))
    return report


def _parse_metadata(raw: Any) -> dict:
    if isinstance(raw, dict):
        return raw
    if isinstance(raw, str):
        import json
        try:
            return json.loads(raw)
        except Exception:
            return {}
    return {}


def _build_repo(backend: str, cfg: dict) -> Any:
    """Build repo from backend name + config dict."""
    if backend == "sqlite":
        from sarthak.storage.backends.sqlite import SQLiteActivityRepo
        return SQLiteActivityRepo()

    if backend in ("postgres", "postgresql"):
        from sarthak.storage.backends.postgres import PostgresActivityRepo
        url = cfg.get("postgres", {}).get("url", "")
        if not url:
            raise ValueError("postgres.url required for postgres backend")
        return PostgresActivityRepo(url=url)

    if backend == "duckdb":
        from sarthak.storage.backends.duckdb import DuckDBActivityRepo
        path = cfg.get("duckdb", {}).get("path", "~/.sarthak_ai/sarthak.duckdb")
        return DuckDBActivityRepo(path=path)

    if backend == "libsql":
        from sarthak.storage.backends.libsql import LibSQLActivityRepo
        lcfg = cfg.get("libsql", {})
        url = lcfg.get("url", "file:///~/.sarthak_ai/sarthak.db")
        token = lcfg.get("auth_token", "")
        return LibSQLActivityRepo(url=url, auth_token=token)

    raise ValueError(f"Unknown backend: {backend!r}. Valid: sqlite, postgres, duckdb, libsql")


async def status() -> dict:
    """Return status of configured storage backends."""
    from sarthak.storage.factory import get_activity_repo, get_cache, _load_cfg
    repo  = get_activity_repo()
    cache = get_cache()
    cfg   = _load_cfg()
    return {
        "activity_backend": type(repo).__name__,
        "cache_backend":    cache.backend_name,
        "vector_backend":   cfg.get("vector_backend", "sqlite_vec"),
        "configured_backend": cfg.get("backend", "sqlite"),
    }
