"""
SQL Loader — load and parse .sql files from storage/sql/.

Single source of truth: all SQL lives in .sql files.
Python backends load queries at import time via this module.

Usage:
    from sarthak.storage.sql_loader import load_schema, load_queries

    # Get full schema DDL as a string
    schema = load_schema("sqlite", "schema_activity")

    # Get dict of named queries parsed from :name directives
    Q = load_queries("sqlite", "queries_activity")
    Q["insert_activity"]   # → raw SQL string

Query file format:
    -- :name query_name
    SELECT ...
    FROM ...

    -- :name another_query
    INSERT ...

Multiple queries per file, separated by -- :name <name> directives.
Blank lines between queries are ignored during parsing.
"""
from __future__ import annotations

import re
from functools import lru_cache
from pathlib import Path

_SQL_ROOT = Path(__file__).parent / "sql"
_NAME_RE = re.compile(r"^\s*--\s*:name\s+(\w+)\s*$")


def _sql_file(dialect: str, filename: str) -> Path:
    """Resolve path to a .sql file. Adds .sql extension if missing."""
    name = filename if filename.endswith(".sql") else f"{filename}.sql"
    return _SQL_ROOT / dialect / name


@lru_cache(maxsize=64)
def load_schema(dialect: str, filename: str) -> str:
    """
    Load a schema .sql file as a single string.
    Result is cached for the process lifetime (schemas never change at runtime).

    Args:
        dialect:  "sqlite" | "postgres" | "duckdb" | "vector"
        filename: base name without extension, e.g. "schema_activity"
    """
    path = _sql_file(dialect, filename)
    if not path.exists():
        raise FileNotFoundError(
            f"SQL schema not found: {path}. "
            f"Expected at storage/sql/{dialect}/{filename}.sql"
        )
    return path.read_text(encoding="utf-8")


@lru_cache(maxsize=64)
def load_queries(dialect: str, filename: str) -> dict[str, str]:
    """
    Parse a queries .sql file into a name→SQL dict.
    Result is cached for the process lifetime.

    Sections are delimited by lines matching:  -- :name <query_name>
    Whitespace is stripped from each query.

    Args:
        dialect:  "sqlite" | "postgres" | "duckdb" | "vector"
        filename: base name without extension, e.g. "queries_activity"

    Returns:
        {"insert_activity": "INSERT INTO ...", "summary": "SELECT ...", ...}
    """
    path = _sql_file(dialect, filename)
    if not path.exists():
        raise FileNotFoundError(
            f"SQL queries not found: {path}. "
            f"Expected at storage/sql/{dialect}/{filename}.sql"
        )

    raw = path.read_text(encoding="utf-8")
    queries: dict[str, str] = {}
    current_name: str | None = None
    current_lines: list[str] = []

    for line in raw.splitlines():
        m = _NAME_RE.match(line)
        if m:
            # Flush previous query
            if current_name is not None:
                sql = "\n".join(current_lines).strip()
                if sql:
                    queries[current_name] = sql
            current_name = m.group(1)
            current_lines = []
        else:
            if current_name is not None:
                current_lines.append(line)

    # Flush last query
    if current_name is not None:
        sql = "\n".join(current_lines).strip()
        if sql:
            queries[current_name] = sql

    return queries


def get_query(dialect: str, filename: str, name: str) -> str:
    """
    Convenience: load_queries(...)[name] with a clear error on miss.

    Args:
        dialect:  "sqlite" | "postgres" | "duckdb"
        filename: query file base name
        name:     query name as defined by -- :name <name>
    """
    queries = load_queries(dialect, filename)
    if name not in queries:
        available = ", ".join(sorted(queries))
        raise KeyError(
            f"Query {name!r} not found in {dialect}/{filename}.sql. "
            f"Available: {available}"
        )
    return queries[name]
