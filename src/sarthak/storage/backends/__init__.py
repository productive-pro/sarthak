"""
backends/__init__.py — re-exports all ActivityRepository implementations.

Import via factory, not directly. This module exists so type checkers
can resolve the union type without needing a full factory call.
"""
from __future__ import annotations

from sarthak.storage.backends.sqlite import SQLiteActivityRepo

__all__ = ["SQLiteActivityRepo"]

# Optional backends — only exported if their driver is installed
try:
    from sarthak.storage.backends.postgres import PostgresActivityRepo
    __all__ += ["PostgresActivityRepo"]
except ImportError:
    pass

try:
    from sarthak.storage.backends.duckdb import DuckDBActivityRepo
    __all__ += ["DuckDBActivityRepo"]
except ImportError:
    pass

try:
    from sarthak.storage.backends.libsql import LibSQLActivityRepo
    __all__ += ["LibSQLActivityRepo"]
except ImportError:
    pass
