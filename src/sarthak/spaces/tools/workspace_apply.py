"""
spaces/tools/workspace_apply.py — Apply workspace design to disk

Pure I/O. No LLM. Takes the JSON design produced by the workspace-designer skill
and materialises it as directories + files on disk.

Public API:
    apply_workspace_design(design, workspace_dir) → list[str]  (created paths)
"""
from __future__ import annotations

from pathlib import Path


def apply_workspace_design(design: dict, workspace_dir: Path) -> list[str]:
    """
    Apply a workspace design dict to disk. Non-destructive — only creates, never deletes.

    design keys:
        directories:  list[str]       — relative paths to create
        readme_files: dict[str, str]  — path → content (only creates if not exists)
        starter_files: dict[str, str] — path → content (only creates if not exists)

    Returns list of created paths.
    """
    created: list[str] = []

    for d in design.get("directories", []):
        t = workspace_dir / d
        t.mkdir(parents=True, exist_ok=True)
        created.append(str(t))

    for rel, content in design.get("readme_files", {}).items():
        t = workspace_dir / rel
        t.parent.mkdir(parents=True, exist_ok=True)
        if not t.exists():
            t.write_text(content, encoding="utf-8")
            created.append(str(t))

    for rel, content in design.get("starter_files", {}).items():
        t = workspace_dir / rel
        t.parent.mkdir(parents=True, exist_ok=True)
        if not t.exists():
            t.write_text(content, encoding="utf-8")
            created.append(str(t))

    return created
