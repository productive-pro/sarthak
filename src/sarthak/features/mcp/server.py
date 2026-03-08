"""
Sarthak AI — MCP server.
Exposes sarthak data to opencode, gemini-cli, claude-code, openclaw, codex.
Uses stdio transport (standard MCP protocol).
Pure functions — no global mutable state.
"""
from __future__ import annotations

import asyncio
import json
from datetime import date

import structlog
from mcp.server import Server
from mcp.server.stdio import stdio_server
from mcp.types import CallToolResult, TextContent, Tool

from sarthak.storage.helpers import get_daily_summary

log = structlog.get_logger(__name__)

_server = Server("sarthak")


def _text(content: str) -> CallToolResult:
    return CallToolResult(content=[TextContent(type="text", text=content)])


def _json_result(data) -> CallToolResult:
    return _text(json.dumps(data, default=str, indent=2))




def _active_space_summary() -> dict | None:
    try:
        from pathlib import Path
        from sarthak.spaces.store import get_active_space, load_space
        active = get_active_space()
        if not active or not active.get("directory"):
            return None
        ws = load_space(Path(active["directory"])) or {}
        profile = ws.get("__profile__", {})
        return {
            "name": active.get("name") or ws.get("name", ""),
            "directory": active.get("directory", ""),
            "domain": profile.get("domain", ""),
            "level": profile.get("level", ""),
            "current_concept": profile.get("current_concept", ""),
            "xp": profile.get("xp", 0),
            "streak_days": profile.get("streak_days", 0),
            "session_count": profile.get("session_count", 0),
        }
    except Exception:
        return None


def _space_status() -> dict:
    try:
        from sarthak.spaces.store import list_spaces
        spaces = list_spaces()
        return {
            "spaces_count": len(spaces),
            "spaces": [
                {
                    "name": s.get("name", ""),
                    "space_type": s.get("space_type", ""),
                    "progress": s.get("progress", 0),
                    "updated_at": s.get("updated_at", ""),
                }
                for s in spaces[:20]
            ],
            "active_space": _active_space_summary(),
        }
    except Exception:
        return {"spaces_count": 0, "spaces": [], "active_space": None}


async def _resume_card_summary() -> str:
    from pathlib import Path
    from sarthak.spaces.store import list_spaces
    from sarthak.spaces.session_tracker import load_sessions

    lines: list[str] = []
    try:
        spaces = list_spaces()
        for space in spaces:
            d = Path(space.get("directory", ""))
            if not d.exists():
                continue
            sessions = load_sessions(d, limit=1)
            if sessions:
                s = sessions[-1]
                lines.append(
                    f"Last space: {space.get('name', d.name)} - "
                    f"{s.concept} ({s.signals.active_seconds // 60} min active)"
                )
                break
    except Exception:
        pass
    return "\n".join(lines) if lines else "No recent Spaces sessions found."


@_server.list_tools()
async def list_tools() -> list[Tool]:
    return [
        Tool(
            name="get_daily_summary",
            description="Get an AI-generated summary of a specific day's activity.",
            inputSchema={
                "type": "object",
                "properties": {
                    "date": {"type": "string", "description": "Date in YYYY-MM-DD format (default: today)"},
                },
            },
        ),
        Tool(
            name="get_resume_card",
            description="Resume card: recent Spaces session summary.",
            inputSchema={
                "type": "object",
                "properties": {
                    "cwd": {"type": "string", "description": "Directory to scope (optional)"},
                },
            },
        ),
        Tool(
            name="get_space_status",
            description="Active space and recent spaces summary.",
            inputSchema={"type": "object", "properties": {}},
        ),
    ]


@_server.call_tool()
async def call_tool(name: str, arguments: dict) -> CallToolResult:
    try:
        return await _dispatch(name, arguments)
    except Exception as exc:
        log.error("mcp_tool_error", tool=name, error=str(exc))
        return _text(f"Error: {exc}")


async def _dispatch(name: str, args: dict) -> CallToolResult:
    if name == "get_daily_summary":
        raw = args.get("date", str(date.today()))
        d = date.fromisoformat(raw)
        cached = await get_daily_summary(d)
        if cached:
            return _json_result(cached)
        return _text(f"No summary found for {d.isoformat()}.")

    if name == "get_resume_card":
        summary = await _resume_card_summary()
        return _text(summary)

    if name == "get_space_status":
        return _json_result(_space_status())

    return _text(f"Unknown tool: {name}")


async def run_mcp_server() -> None:
    """Start the MCP stdio server."""
    log.info("mcp_server_started")
    async with stdio_server() as (read_stream, write_stream):
        await _server.run(read_stream, write_stream, _server.create_initialization_options())


def main() -> None:
    asyncio.run(run_mcp_server())
