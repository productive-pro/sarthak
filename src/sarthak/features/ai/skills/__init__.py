"""
Skills registry — Markdown knowledge files injected into agent system prompts.

Resolution order (first-wins per name):
  1. Space-scoped  : <space_dir>/.spaces/skills/*.md   (set at runtime via set_space_dir)
  2. User skills   : <user_data_dir>/skills/*.md
  3. Built-in      : src/sarthak/data/skills/*.md      (ships with the package)

Front-matter schema (all fields optional):
    ---
    name: "git-workflow"
    description: "Team branching and commit conventions"
    tags: [git, workflow]
    ---
    <Markdown content>
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path

from sarthak.core.logging import get_logger

log = get_logger(__name__)

# Built-in skills ship with the package (cross-platform, relative to this file)
_BUILTIN_SKILLS_DIR = Path(__file__).parent.parent.parent.parent / "data" / "skills"

# Resolved from user's platform-appropriate data dir
_USER_SKILLS_DIR: Path | None = None
# Optional runtime space-scoped override
_SPACE_SKILLS_DIR: Path | None = None

_FM_RE = re.compile(r"^---\s*\n(.*?)\n---\s*\n", re.DOTALL)


def _get_user_skills_dir() -> Path:
    """Return platform-appropriate user skills directory (lazy, cached)."""
    global _USER_SKILLS_DIR
    if _USER_SKILLS_DIR is None:
        from sarthak.core.config import load_config
        try:
            cfg = load_config()
            base = Path(getattr(cfg, "data_dir", Path.home() / ".sarthak_ai"))
        except Exception:
            base = Path.home() / ".sarthak_ai"
        _USER_SKILLS_DIR = base / "skills"
    return _USER_SKILLS_DIR


def set_space_skills_dir(space_dir: str | Path | None) -> None:
    """Set the active space's skills directory for the current process."""
    global _SPACE_SKILLS_DIR
    _SPACE_SKILLS_DIR = Path(space_dir) / ".spaces" / "skills" if space_dir else None


@dataclass
class Skill:
    name: str
    description: str
    tags: list[str]
    content: str
    path: Path
    source: str = "user"   # "builtin" | "user" | "space"


# ── Internal helpers ──────────────────────────────────────────────────────────

def _parse(path: Path, source: str = "user") -> Skill | None:
    try:
        raw = path.read_text(encoding="utf-8")
        m = _FM_RE.match(raw)
        if not m:
            return Skill(name=path.stem, description="", tags=[], content=raw.strip(),
                         path=path, source=source)
        name, description, tags = path.stem, "", []
        for line in m.group(1).splitlines():
            if line.startswith("name:"):
                name = line.split(":", 1)[1].strip().strip('"')
            elif line.startswith("description:"):
                description = line.split(":", 1)[1].strip().strip('"')
            elif line.startswith("tags:"):
                raw_tags = line.split(":", 1)[1].strip()
                tags = [t.strip().strip("[]\"'") for t in raw_tags.split(",") if t.strip()]
        return Skill(name=name, description=description, tags=tags,
                     content=raw[m.end():].strip(), path=path, source=source)
    except Exception as exc:
        log.warning("skill_parse_failed", path=str(path), error=str(exc))
        return None


def _load_dir(d: Path, source: str) -> list[Skill]:
    if not d or not d.is_dir():
        return []
    return [s for p in sorted(d.glob("*.md")) if (s := _parse(p, source))]


# ── Public API ────────────────────────────────────────────────────────────────

def list_skills() -> list[Skill]:
    """
    Return merged skill list in resolution order:
    space-scoped → user → built-in.
    Names are deduplicated (first-wins).
    """
    seen: set[str] = set()
    result: list[Skill] = []
    for skills in (
        _load_dir(_SPACE_SKILLS_DIR, "space"),
        _load_dir(_get_user_skills_dir(), "user"),
        _load_dir(_BUILTIN_SKILLS_DIR, "builtin"),
    ):
        for s in skills:
            key = s.name.lower()
            if key not in seen:
                seen.add(key)
                result.append(s)
    return result


def get_skill(name: str) -> Skill | None:
    slug = name.lower().replace(" ", "-")
    return next(
        (s for s in list_skills()
         if slug in s.name.lower() or slug in s.description.lower()),
        None,
    )


def save_skill(name: str, description: str, content: str,
               tags: list[str] | None = None, space_dir: str | Path | None = None) -> Skill:
    """Save to space skills dir if space_dir given, else user skills dir."""
    if space_dir:
        target = Path(space_dir) / ".spaces" / "skills"
    else:
        target = _get_user_skills_dir()
    target.mkdir(parents=True, exist_ok=True)
    slug = name.lower().replace(" ", "-")
    tags_str = ", ".join(tags or [])
    path = target / f"{slug}.md"
    path.write_text(
        f'---\nname: "{name}"\ndescription: "{description}"\ntags: [{tags_str}]\n---\n\n{content}',
        encoding="utf-8",
    )
    source = "space" if space_dir else "user"
    log.info("skill_saved", name=name, source=source)
    return Skill(name=name, description=description, tags=tags or [],
                 content=content, path=path, source=source)


def delete_skill(name: str) -> bool:
    slug = name.lower().replace(" ", "-")
    for s in list_skills():
        if slug in s.name.lower() and s.source != "builtin":
            s.path.unlink()
            log.info("skill_deleted", name=s.name)
            return True
    return False


def build_context_block(skills: list[Skill], include_content: bool = False) -> str:
    """
    Build skills block for system prompt injection.
    Summary-only by default (token-efficient); full content only when explicitly requested.
    """
    if not skills:
        return ""
    lines = ["## Available Skills (use read_skill_tool to read full content)\n"]
    for s in skills:
        desc = f" — {s.description}" if s.description else ""
        tags = f" [{', '.join(s.tags)}]" if s.tags else ""
        if include_content:
            lines += [f"### {s.name}{desc}{tags}", s.content, ""]
        else:
            lines.append(f"- **{s.name}**{desc}{tags}")
    return "\n".join(lines)


# ── Tool wrappers ─────────────────────────────────────────────────────────────

def tool_list_skills() -> str:
    skills = list_skills()
    if not skills:
        return "No skills saved yet."
    return "\n".join(
        f"**{s.name}** [{s.source}] — {s.description}" + (f" [{', '.join(s.tags)}]" if s.tags else "")
        for s in skills
    )


def tool_read_skill(name: str) -> str:
    s = get_skill(name)
    if not s:
        return f"Skill '{name}' not found."
    return f"**{s.name}** ({s.source})\n_{s.description}_\n\n{s.content}"


def tool_save_skill(name: str, description: str, content: str, tags: str = "") -> str:
    tag_list = [t.strip() for t in tags.split(",") if t.strip()]
    s = save_skill(name=name, description=description, content=content, tags=tag_list)
    return f"Skill '{s.name}' saved."


def tool_delete_skill(name: str) -> str:
    return "Skill deleted." if delete_skill(name) else f"Skill '{name}' not found or is built-in."
