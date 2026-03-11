"""
repositories/chat.py — ChatRepository backed by the global SQLite DB.

Chat history is always stored locally in the global sarthak.db.
No pluggable backend for chat — it's session-local data.

Queries: storage/sql/sqlite/queries_chat.sql
"""
from __future__ import annotations

from sarthak.storage.sql_loader import load_queries
from sarthak.storage.db import connect

_Q = load_queries("sqlite", "queries_chat")


class ChatRepo:
    """Read/write chat_history rows."""

    async def write_message(
        self, session_id: str, role: str, content: str
    ) -> None:
        async with connect() as db:
            await db.execute(_Q["insert_message"], (session_id, role, content))
            await db.commit()

    async def get_history(
        self, session_id: str, limit: int = 100
    ) -> list[dict]:
        async with connect() as db:
            async with db.execute(
                _Q["get_history"], (session_id, limit)
            ) as cur:
                rows = await cur.fetchall()
        return [dict(r) for r in rows]

    async def get_sessions(self, limit: int = 20) -> list[dict]:
        async with connect() as db:
            async with db.execute(_Q["get_sessions"], (limit,)) as cur:
                rows = await cur.fetchall()
        return [dict(r) for r in rows]

    async def latest_session_id(self) -> str | None:
        async with connect() as db:
            async with db.execute(_Q["latest_session_id"]) as cur:
                row = await cur.fetchone()
        return row["session_id"] if row else None


# Process-level default instance
default = ChatRepo()
