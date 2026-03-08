"""Space tools — context and management."""
from __future__ import annotations

from sarthak.core.logging import get_logger

log = get_logger(__name__)


def tool_space_context(directory: str = "") -> str:
    """Return the active space context (goal, notes, recent sessions)."""
    try:
        from pathlib import Path
        from sarthak.spaces.store import get_space_context
        return get_space_context(Path(directory) if directory else None) or "No active space."
    except Exception as exc:
        return f"Space context failed: {exc}"


def tool_space_init(
    directory: str, name: str, description: str, goal: str, tags: str = ""
) -> str:
    """Initialise a new Sarthak space in a directory."""
    try:
        from pathlib import Path
        from sarthak.spaces.store import init_space
        tag_list = [t.strip() for t in tags.split(",") if t.strip()]
        cfg = init_space(Path(directory), name, description, goal, tag_list)
        return f"Space '{cfg['name']}' created in {directory}."
    except Exception as exc:
        return f"Space init failed: {exc}"


def tool_space_list() -> list[dict]:
    """Return known spaces from the registry."""
    try:
        from sarthak.spaces.store import list_spaces
        return list_spaces()
    except Exception as exc:
        return [{"error": str(exc)}]


def tool_space_activate(directory: str) -> str:
    """Set the active space by directory."""
    try:
        from pathlib import Path
        from sarthak.spaces.store import set_active_space
        ws = set_active_space(Path(directory))
        return f"Active space: {ws.get('name', 'space')} ({ws.get('directory', directory)})"
    except Exception as exc:
        return f"Space activate failed: {exc}"


def tool_space_deactivate() -> str:
    """Clear the active space."""
    try:
        from sarthak.spaces.store import clear_active_space
        clear_active_space()
        return "Active space cleared."
    except Exception as exc:
        return f"Space deactivate failed: {exc}"


def tool_space_remove(directory: str) -> str:
    """Remove a space from the registry."""
    try:
        from pathlib import Path
        from sarthak.spaces.store import remove_space
        removed = remove_space(Path(directory))
        return f"Removed space: {directory}" if removed else "No matching space found."
    except Exception as exc:
        return f"Space remove failed: {exc}"


def tool_space_rename(directory: str, name: str) -> str:
    """Rename a space."""
    try:
        from pathlib import Path
        from sarthak.spaces.store import rename_space
        ws = rename_space(Path(directory), name)
        return f"Renamed space to '{ws.get('name', name)}'."
    except Exception as exc:
        return f"Space rename failed: {exc}"


def tool_space_set_goal(directory: str, goal: str) -> str:
    """Update space goal."""
    try:
        from pathlib import Path
        from sarthak.spaces.store import set_space_goal
        ws = set_space_goal(Path(directory), goal)
        return f"Updated goal for '{ws.get('name', 'space')}'."
    except Exception as exc:
        return f"Space goal update failed: {exc}"


def tool_space_set_tags(directory: str, tags: str) -> str:
    """Update space tags (comma-separated)."""
    try:
        from pathlib import Path
        from sarthak.spaces.store import set_space_tags
        tag_list = [t.strip() for t in tags.split(",") if t.strip()]
        ws = set_space_tags(Path(directory), tag_list)
        return f"Updated tags for '{ws.get('name', 'space')}'."
    except Exception as exc:
        return f"Space tag update failed: {exc}"


# ── Backwards-compat aliases (for any agent code still using old names) ───────
tool_workspace_context  = tool_space_context
tool_workspace_init     = tool_space_init
tool_workspace_list     = tool_space_list
tool_workspace_activate = tool_space_activate
tool_workspace_deactivate = tool_space_deactivate
tool_workspace_remove   = tool_space_remove
tool_workspace_rename   = tool_space_rename
tool_workspace_set_goal = tool_space_set_goal
tool_workspace_set_tags = tool_space_set_tags
