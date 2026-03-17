"""
Sarthak Spaces — WorkspaceTransformer.

Applies expert workspace templates loaded from data/workspace_templates.yaml.
Non-destructive: never deletes, only adds.
Idempotent: safe to run multiple times.

Template resolution order for any SpaceType:
  1. shared   — base dirs / readme_files / starter_files merged into every template
  2. domain   — domain-specific content (may use `extends` to inherit another domain)
  3. extra_dirs — custom directories appended last (CUSTOM spaces from discover_custom_domain)

New behaviours vs old hardcoded version:
  - All template content lives in data/workspace_templates.yaml — no Python changes needed
  - `extends` key: ai_engineering inherits data_science without duplication
  - .gitkeep written to every created directory (git tracks empty dirs)
  - progress.md content is domain-specific for all domains (not just DS + exam_prep)
  - space_structure.md written at space root and .spaces/ for LLM context injection
  - Per-folder README files generated for CUSTOM `extra_dirs` with generic content
  - Lazy-loaded + cached — YAML is parsed once per process
"""
from __future__ import annotations

import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import yaml

from sarthak.core.logging import get_logger
from sarthak.spaces.models import SpaceType

log = get_logger(__name__)

# ── Template file location ─────────────────────────────────────────────────────

_PKG_ROOT = Path(__file__).parent          # src/sarthak/spaces/
_TMPL_FILE = _PKG_ROOT.parent / "data" / "workspace_templates.yaml"  # src/sarthak/data/

_cache_lock: threading.Lock = threading.Lock()
_templates_cache: dict[str, Any] | None = None


# ── YAML loader ───────────────────────────────────────────────────────────────

def _load_raw() -> dict[str, Any]:
    global _templates_cache
    if _templates_cache is not None:
        return _templates_cache
    with _cache_lock:
        if _templates_cache is not None:
            return _templates_cache
        if not _TMPL_FILE.exists():
            raise FileNotFoundError(
                f"workspace_templates.yaml not found: {_TMPL_FILE}\n"
                f"Run 'sarthak space setup' to restore data files."
            )
        try:
            data = yaml.safe_load(_TMPL_FILE.read_text(encoding="utf-8")) or {}
        except yaml.YAMLError as exc:
            log.error("workspace_templates_parse_error", error=str(exc))
            raise
        _templates_cache = data
        return data


def _resolve_template(key: str, raw: dict, _stack: frozenset[str] | None = None) -> dict:
    """
    Resolve a template by key, merging shared + parent (via `extends`) + own.
    Returns a flat dict: {directories, readme_files, starter_files, progress_md}
    """
    stack = _stack or frozenset()
    own   = raw.get(key, {})

    # Handle `extends` (e.g. ai_engineering extends data_science)
    parent: dict = {}
    parent_key = own.get("extends")
    if parent_key and parent_key not in stack:
        parent = _resolve_template(parent_key, raw, stack | {key})
    elif parent_key:
        log.warning("workspace_template_circular_extends", key=key, parent=parent_key)

    shared = raw.get("shared", {})

    # Merge: shared ← parent ← own  (later wins for scalar keys, dicts are merged)
    result: dict = {
        "directories":   [],
        "readme_files":  {},
        "starter_files": {},
        "progress_md":   "",
    }

    for src in (shared, parent, own):
        result["directories"]   = list(dict.fromkeys(
            result["directories"] + list(src.get("directories", []))
        ))
        result["readme_files"]  = {**result["readme_files"],  **src.get("readme_files",  {})}
        result["starter_files"] = {**result["starter_files"], **src.get("starter_files", {})}
        if src.get("progress_md"):
            result["progress_md"] = src["progress_md"]

    return result


def _get_template(space_type: SpaceType) -> dict:
    raw = _load_raw()
    key = space_type.value  # e.g. "data_science"
    if key not in raw:
        log.warning("workspace_template_missing", space_type=key, fallback="custom")
        key = "custom"
    return _resolve_template(key, raw)


# ── Generic README for unknown custom dirs ─────────────────────────────────────

_GENERIC_FOLDER_DESCS: dict[str, str] = {
    "notes":        "Your personal notes — concept explanations, insights, summaries.",
    "resources":    "Reference materials, PDFs, links, and external content.",
    "projects":     "Hands-on projects you build to apply what you learn.",
    "reflections":  "Journaling, self-assessment, and learning reflections.",
    "data":         "Datasets and data files used in exercises.",
    "notebooks":    "Interactive notebooks for exploration and tutorials.",
    "src":          "Production-quality code extracted from notebooks.",
    "experiments":  "Tracked experiments with results and metadata.",
    "models":       "Saved model weights and metadata.",
    "reports":      "Final analyses and publication-ready outputs.",
    "flashcards":   "Spaced repetition flashcard decks.",
    "mock_tests":   "Timed practice tests and results.",
    "weak_areas":   "Error log and targeted drilling materials.",
    "subjects":     "Subject-by-subject organized study materials.",
    "literature":   "Research papers and reading log.",
    "analysis":     "Analytical work and findings.",
    "writing":      "Writing drafts and documents.",
    "presentations":"Slides and presentation materials.",
    "curriculum":   "Curriculum design documents.",
    "lessons":      "Lesson materials and activities.",
    "assessments":  "Assessment and quiz materials.",
}

def _auto_readme(folder: str) -> str:
    """Generate a README for a custom folder with no explicit template entry."""
    desc = _GENERIC_FOLDER_DESCS.get(folder, f"Files and materials related to {folder}.")
    title = folder.replace("_", " ").title()
    return f"# {title}\n\n{desc}\n"


# ── WorkspaceTransformer ───────────────────────────────────────────────────────

class WorkspaceTransformer:
    """
    Applies the expert workspace template for a SpaceType.
    Safe to run multiple times — fully idempotent.

    What it does on transform():
      1. Creates all template directories (mkdir -p, never removes)
      2. Writes .gitkeep into each new empty directory so git tracks them
      3. Writes README files (skips if file already exists)
      4. Writes starter files (skips if file already exists)
      5. Writes .spaces/progress.md (domain-specific roadmap tracker, skips if exists)
      6. Writes space_structure.md at root and .spaces/ for LLM context injection
    """

    def __init__(self, workspace_dir: str | Path):
        self.workspace_dir = Path(workspace_dir).resolve()

    def transform(
        self,
        space_type: SpaceType = SpaceType.DATA_SCIENCE,
        extra_dirs: list[str] | None = None,
    ) -> list[str]:
        """
        Apply expert workspace template. Returns list of created paths.

        extra_dirs: additional directories to create (used for CUSTOM spaces
        where discover_custom_domain() returns workspace_folders).
        Each extra dir also gets an auto-generated README if not in template.
        """
        template = _get_template(space_type)
        created: list[str] = []

        # Merge in extra_dirs (deduplicated, preserving order)
        all_dirs = list(dict.fromkeys(
            template["directories"] + (extra_dirs or [])
        ))

        # 1. Create directories + .gitkeep
        for d in all_dirs:
            target = self.workspace_dir / d
            is_new = not target.exists()
            target.mkdir(parents=True, exist_ok=True)
            if is_new:
                created.append(str(target))
            # .gitkeep — only for leaf dirs that have no other files
            gitkeep = target / ".gitkeep"
            if not gitkeep.exists() and not any(
                f for f in target.iterdir() if f.name != ".gitkeep"
            ) if target.exists() else True:
                gitkeep.touch()

        # 2. README files from template
        readme_map: dict[str, str] = dict(template["readme_files"])

        # Auto-generate README for extra_dirs that have no entry in the template
        for d in (extra_dirs or []):
            top_level = d.split("/")[0]
            readme_key = f"{top_level}/README.md"
            if readme_key not in readme_map:
                readme_map[readme_key] = _auto_readme(top_level)

        for rel, content in readme_map.items():
            target = self.workspace_dir / rel
            target.parent.mkdir(parents=True, exist_ok=True)
            if not target.exists():
                target.write_text(content, encoding="utf-8")
                created.append(str(target))

        # 3. Starter files
        for rel, content in template["starter_files"].items():
            target = self.workspace_dir / rel
            target.parent.mkdir(parents=True, exist_ok=True)
            if not target.exists():
                target.write_text(content, encoding="utf-8")
                created.append(str(target))

        # 4. Progress tracker (.spaces/progress.md) — idempotent
        self._write_progress(template["progress_md"])

        # 5. Directory structure doc (root + .spaces/) — always refresh
        self._write_structure_doc(space_type, all_dirs, readme_map)

        log.info(
            "workspace_transformed",
            space_type=space_type.value,
            created=len(created),
            workspace=str(self.workspace_dir),
        )
        return created

    # ── Private helpers ────────────────────────────────────────────────────────

    def _write_progress(self, content: str) -> None:
        """Write .spaces/progress.md if it doesn't exist yet."""
        progress = self.workspace_dir / ".spaces" / "progress.md"
        progress.parent.mkdir(parents=True, exist_ok=True)
        if not progress.exists():
            progress.write_text(
                content or "# Mastery Roadmap\n\nAuto-updated by Sarthak after each session.\n",
                encoding="utf-8",
            )

    def _write_structure_doc(
        self,
        space_type: SpaceType,
        all_dirs: list[str],
        readme_map: dict[str, str],
    ) -> None:
        """
        Write space_structure.md at workspace root and .spaces/directory_structure.md.
        Replaces the old write_directory_structure() function in roadmap_init.py.
        Always refreshed so it stays current with actual workspace contents.
        """
        domain_name = space_type.value.replace("_", " ").title()
        date_str = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        lines = [
            f"# Workspace Structure: {domain_name}",
            f"*Generated: {date_str}*",
            "",
            "This file documents the purpose of each folder in your learning workspace.",
            "Sarthak agents use `.spaces/directory_structure.md` for workspace context.",
            "",
            "## Directory Layout",
            "",
        ]

        # Top-level dirs only (skip .spaces internals from this doc)
        seen_tops: set[str] = set()
        for d in all_dirs:
            top = d.split("/")[0]
            if top in seen_tops or top == ".spaces":
                continue
            seen_tops.add(top)
            readme_key = f"{top}/README.md"
            desc = ""
            if readme_key in readme_map:
                # First non-empty, non-heading line of the README
                for ln in readme_map[readme_key].splitlines():
                    ln = ln.strip()
                    if ln and not ln.startswith("#"):
                        desc = ln[:120]
                        break
            if not desc:
                desc = _GENERIC_FOLDER_DESCS.get(top, f"Files and materials for {top}.")
            lines.append(f"### `{top}/`")
            lines.append(desc)
            # List existing files (for already-populated spaces)
            actual = self.workspace_dir / top
            if actual.exists():
                sub = sorted(
                    f.name for f in actual.iterdir()
                    if not f.name.startswith(".") and f.name != ".gitkeep"
                )[:5]
                if sub:
                    lines.append(f"*Contains: {', '.join(sub)}*")
            lines.append("")

        lines += [
            "## Sarthak State (`.spaces/`)",
            "",
            "| File | Purpose |",
            "|------|---------|",
            "| `sarthak.db` | Roadmap, notes, SRS cards (SQLite) |",
            "| `rag/` | Vector search index |",
            "| `tasks/` | Current and past learning tasks |",
            "| `progress.md` | Mastery tracker (auto-updated) |",
            "| `SOUL.md` | Agent identity for this space |",
            "| `MEMORY.md` | Long-term learner patterns |",
            "| `HEARTBEAT.md` | SRS due cards + streak |",
            "| `directory_structure.md` | This file |",
            "",
        ]
        content = "\n".join(lines)

        # .spaces/ copy for LLM context injection
        hidden = self.workspace_dir / ".spaces" / "directory_structure.md"
        hidden.parent.mkdir(parents=True, exist_ok=True)
        hidden.write_text(content, encoding="utf-8")

        # Root copy for human visibility
        root_doc = self.workspace_dir / "space_structure.md"
        root_doc.write_text(content, encoding="utf-8")

        log.debug("structure_doc_written", path=str(root_doc))


def invalidate_template_cache() -> None:
    """Clear the in-process template cache. Call after editing workspace_templates.yaml."""
    global _templates_cache
    with _cache_lock:
        _templates_cache = None
    log.info("workspace_template_cache_invalidated")
