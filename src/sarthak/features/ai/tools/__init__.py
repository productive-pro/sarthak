"""
AI tools package — all @agent.tool function implementations.

Web search is handled by pydantic-ai's built-in duckduckgo_search_tool()
registered on agents directly.
"""
from sarthak.features.ai.tools.activity import (
    tool_query_activity,
    tool_get_summary,
    tool_get_tips,
    tool_save_tip,
)
from sarthak.features.ai.tools.shell import tool_run_shell, is_safe_command
from sarthak.features.ai.tools.system import (
    tool_service_status,
    tool_restart_service,
)
# Skills tools live in features/ai/skills — imported directly (no shim layer)
from sarthak.features.ai.skills import (
    tool_list_skills,
    tool_read_skill,
    tool_save_skill,
    tool_delete_skill,
)
from sarthak.features.ai.tools.spaces import (
    tool_spaces_session,
    tool_spaces_session_isolated,
    tool_spaces_status,
    tool_spaces_setup,
    tool_spaces_evaluate,
    tool_spaces_init,
    tool_spaces_context,
    tool_spaces_context_hierarchical,
    tool_spaces_quick,
    tool_spaces_list,
    tool_spaces_rag_index,
    tool_spaces_rag_search,
    tool_workspace_qa,
    tool_workspace_analyse,
)

__all__ = [
    "tool_query_activity", "tool_get_summary", "tool_get_tips", "tool_save_tip",
    "tool_run_shell", "is_safe_command",
    "tool_service_status", "tool_restart_service",
    "tool_list_skills", "tool_read_skill", "tool_save_skill", "tool_delete_skill",
    "tool_spaces_session", "tool_spaces_session_isolated",
    "tool_spaces_status", "tool_spaces_setup",
    "tool_spaces_evaluate", "tool_spaces_init",
    "tool_spaces_context", "tool_spaces_context_hierarchical",
    "tool_spaces_quick", "tool_spaces_list",
    "tool_spaces_rag_index", "tool_spaces_rag_search",
    "tool_workspace_qa", "tool_workspace_analyse",
]
