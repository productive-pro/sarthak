"""
spaces/tools/__init__.py — Pure-logic tools for the Spaces subsystem

These are NOT agents. They are stateless, reusable functions with no LLM calls.
Any agent, scheduler, or CLI can import and call them directly.

  srs             — SM-2 spaced repetition scheduling
  badges          — achievement milestone logic
  env_scan        — OS tool/package detection
  external_tools  — filesystem-based external tool detection
  workspace_apply — materialise workspace design onto disk
"""
from sarthak.spaces.tools.srs import get_due_reviews, update_after_review
from sarthak.spaces.tools.badges import check_and_award, BADGES
from sarthak.spaces.tools.env_scan import scan_environment
from sarthak.spaces.tools.external_tools import (
    detect_external_tools,
    get_domain_recommendations,
    format_guidance,
)
from sarthak.spaces.tools.workspace_apply import apply_workspace_design

__all__ = [
    # SRS
    "get_due_reviews", "update_after_review",
    # Badges
    "check_and_award", "BADGES",
    # Environment
    "scan_environment",
    # External tools
    "detect_external_tools", "get_domain_recommendations", "format_guidance",
    # Workspace
    "apply_workspace_design",
]
