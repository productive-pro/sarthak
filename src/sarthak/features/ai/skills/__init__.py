"""
Skills registry — Markdown knowledge files the agent can read, write, and delete.

Skills live in  ~/.sarthak_ai/skills/*.md  with optional YAML front-matter.

Front-matter schema:
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

SKILLS_DIR = Path.home() / ".sarthak_ai" / "skills"
_FM_RE = re.compile(r"^---\s*\n(.*?)\n---\s*\n", re.DOTALL)


@dataclass
class Skill:
    name: str
    description: str
    tags: list[str]
    content: str
    path: Path


# ── Internal helpers ──────────────────────────────────────────────────────────

def _ensure_dir() -> None:
    SKILLS_DIR.mkdir(parents=True, exist_ok=True)


def _parse(path: Path) -> Skill | None:
    try:
        raw = path.read_text(encoding="utf-8")
        m = _FM_RE.match(raw)
        if not m:
            return Skill(name=path.stem, description="", tags=[], content=raw.strip(), path=path)

        name, description, tags = path.stem, "", []
        for line in m.group(1).splitlines():
            if line.startswith("name:"):
                name = line.split(":", 1)[1].strip().strip('"')
            elif line.startswith("description:"):
                description = line.split(":", 1)[1].strip().strip('"')
            elif line.startswith("tags:"):
                raw_tags = line.split(":", 1)[1].strip()
                tags = [t.strip().strip("[]\"'") for t in raw_tags.split(",") if t.strip()]

        return Skill(name=name, description=description, tags=tags, content=raw[m.end():].strip(), path=path)
    except Exception as exc:
        log.warning("skill_parse_failed", path=str(path), error=str(exc))
        return None


# ── Public API ────────────────────────────────────────────────────────────────

def list_skills() -> list[Skill]:
    _ensure_dir()
    return [s for p in sorted(SKILLS_DIR.glob("*.md")) if (s := _parse(p))]


def get_skill(name: str) -> Skill | None:
    slug = name.lower().replace(" ", "-")
    exact = SKILLS_DIR / f"{slug}.md"
    if exact.exists():
        return _parse(exact)
    return next((s for s in list_skills() if slug in s.name.lower() or slug in s.description.lower()), None)


def save_skill(name: str, description: str, content: str, tags: list[str] | None = None) -> Skill:
    _ensure_dir()
    slug = name.lower().replace(" ", "-")
    tags_str = ", ".join(tags or [])
    path = SKILLS_DIR / f"{slug}.md"
    path.write_text(
        f'---\nname: "{name}"\ndescription: "{description}"\ntags: [{tags_str}]\n---\n\n{content}',
        encoding="utf-8",
    )
    log.info("skill_saved", name=name, path=str(path))
    return Skill(name=name, description=description, tags=tags or [], content=content, path=path)


def delete_skill(name: str) -> bool:
    slug = name.lower().replace(" ", "-")
    path = SKILLS_DIR / f"{slug}.md"
    if path.exists():
        path.unlink()
        log.info("skill_deleted", name=name)
        return True
    for s in list_skills():
        if slug in s.name.lower():
            s.path.unlink()
            log.info("skill_deleted", name=s.name)
            return True
    return False


def build_context_block(skills: list[Skill], include_content: bool = False) -> str:
    """Build a skills context block for injection into a system prompt.

    By default (include_content=False) only skill name + description are listed
    so the system prompt stays small (~1 line per skill).  Full content is only
    included when a skill is explicitly read via ``read_skill_tool``.
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


# ── Tool wrappers (used by agents) ────────────────────────────────────────────

def tool_list_skills() -> str:
    skills = list_skills()
    if not skills:
        return "No skills saved yet."
    return "\n".join(
        f"**{s.name}** — {s.description}" + (f" [{', '.join(s.tags)}]" if s.tags else "")
        for s in skills
    )


def tool_read_skill(name: str) -> str:
    s = get_skill(name)
    if not s:
        return f"Skill '{name}' not found."
    return f"**{s.name}**\n_{s.description}_\n\n{s.content}"


def tool_save_skill(name: str, description: str, content: str, tags: str = "") -> str:
    tag_list = [t.strip() for t in tags.split(",") if t.strip()]
    s = save_skill(name=name, description=description, content=content, tags=tag_list)
    return f"Skill '{s.name}' saved."


def tool_delete_skill(name: str) -> str:
    return "Skill deleted." if delete_skill(name) else f"Skill '{name}' not found."
