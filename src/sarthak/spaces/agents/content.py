from __future__ import annotations

import json
import uuid
from pathlib import Path

from sarthak.features.ai.agents._base import parse_json_response, run_llm
from sarthak.spaces.agents._common import _call_llm_json
from sarthak.spaces.models import LearningTask, ProjectRecord, SkillLevel, SpaceContext


class MathAgent:
    """
    Explains mathematical foundations.
    Novice: intuition + analogy. Expert: full derivation + proof.
    Always connects math → code (numpy/Python equivalent).
    For non-technical: domain analogies first (doctor → clinical, teacher → classroom).
    """

    SYSTEM = """You are a mathematical foundations expert for Sarthak Spaces.
Build GENUINE understanding — never just memorization.

Rules:
- Intuition first: geometric, physical, or domain-specific analogy.
- Step-by-step derivation matching learner level.
- Code connection: numpy/Python equivalent for every formula.
- LaTeX: $...$ inline, $$...$$ block.
- For non-technical learners: use domain analogies (doctor → sensitivity/specificity, teacher → learning curves).
- Call out the 2 most common misconceptions explicitly.

Output ONLY valid JSON:
{
  "intuition": "plain-English analogy tailored to learner background",
  "key_formulas": [{"name": "...", "latex": "...", "meaning": "..."}],
  "derivation_steps": ["step1 with explanation", "step2", "..."],
  "numpy_equivalent": "# Python code showing the math\nimport numpy as np\n...",
  "common_misconceptions": ["misconception 1", "misconception 2"],
  "deeper_reading": ["author - title - year"]
}"""

    async def explain(
        self,
        concept: str,
        level: SkillLevel,
        background: str = "",
        is_technical: bool = True,
    ) -> dict:
        prompt = (
            f"Concept: {concept}\n"
            f"Learner level: {level.value}\n"
            f"Learner background: {background or 'technical professional'}\n"
            f"Technical background: {is_technical}\n"
            "Return mathematical explanation as JSON."
        )
        return await _call_llm_json(self.SYSTEM, prompt, {
            "intuition": f"Core idea of {concept}",
            "key_formulas": [],
            "derivation_steps": [],
            "numpy_equivalent": f"# {concept}\n# See documentation",
            "common_misconceptions": [],
        }, tag="math_agent")


class TaskBuilderAgent:
    """
    Builds hands-on tasks with real-world hooks.
    Always includes: starter code, hints, bonus challenge, math connection.
    For non-technical learners: includes no_code_version (Jupyter widgets / spreadsheet).
    """

    SYSTEM = """You are a hands-on learning task designer for Sarthak Spaces.
Learning happens through DOING. Every task must feel achievable AND meaningful.

Principles:
- Open with a real-world problem the learner actually cares about.
- Include the MATH — even non-coders should see the formula.
- Starter code with # TODO markers guides without giving away the solution.
- Non-technical version uses visual tools (Jupyter widgets, spreadsheets).
- 3 hints: first is gentle, last nearly solves it.
- Bonus challenge for fast finishers.

Output ONLY valid JSON:
{
  "title": "Task title",
  "real_world_hook": "Why this matters right now (1-2 sentences)",
  "instructions": "Step-by-step in Markdown with ## headers and code blocks",
  "starter_code": "Python with # TODO markers",
  "no_code_version": "Version for non-technical learners using spreadsheets or widgets",
  "expected_outcome": "Concrete success definition",
  "math_foundation": "LaTeX key formula",
  "hints": ["gentle hint", "stronger hint", "almost-solution hint"],
  "bonus_challenge": "Harder extension",
  "resources": ["url or book:chapter"],
  "estimated_minutes": 30
}"""

    async def build(
        self,
        concept: str,
        ctx: SpaceContext,
        math_context: dict,
    ) -> LearningTask:
        from sarthak.spaces.agents._common import is_technical
        p = ctx.profile.learner
        technical = is_technical(p.background or "")
        prompt = (
            f"Concept: {concept}\n"
            f"Domain: {ctx.profile.domain}\n"
            f"Level: {p.skill_level.value}\n"
            f"Background: {p.background or 'technical professional'}\n"
            f"Technical: {technical}\n"
            f"Goal: {p.goal or 'mastery'}\n"
            f"Math formulas: {json.dumps(math_context.get('key_formulas', [])[:2])}\n"
            "Build hands-on task. Return JSON."
        )
        xp_map = {
            SkillLevel.NOVICE: 8,
            SkillLevel.BEGINNER: 12,
            SkillLevel.INTERMEDIATE: 18,
            SkillLevel.ADVANCED: 25,
            SkillLevel.EXPERT: 35,
        }
        xp = xp_map.get(p.skill_level, 10)
        fallback = {
            "title": f"Practice: {concept}",
            "instructions": f"Implement **{concept}** from scratch.\nUnderstand the math, then code it.",
            "expected_outcome": "Working implementation with 2 test cases",
        }
        data = await _call_llm_json(self.SYSTEM, prompt, fallback, tag="task_builder")
        return LearningTask(
            task_id=str(uuid.uuid4())[:8],
            title=data.get("title", concept),
            concept=concept,
            difficulty=p.skill_level,
            task_type="implement",
            instructions=data.get("instructions", ""),
            expected_outcome=data.get("expected_outcome", ""),
            hints=data.get("hints", []),
            resources=data.get("resources", []),
            math_foundation=data.get("math_foundation", ""),
            real_world_hook=data.get("real_world_hook", ""),
            starter_code=data.get("starter_code", ""),
            no_code_version=data.get("no_code_version", ""),
            bonus_challenge=data.get("bonus_challenge", ""),
            estimated_minutes=int(data.get("estimated_minutes", 30)),
            xp_reward=xp,
        )


class ProjectAgent:
    """
    The most powerful learning accelerator: REAL projects.
    Scaffolds project directories, generates step-by-step milestones,
    and guides the learner through building something they're proud of.

    Projects are far more effective than isolated tasks because:
    - Integration: learner applies multiple concepts together
    - Motivation: tangible artifact to show/share
    - Retention: memory anchors to real work
    """

    SYSTEM_SCAFFOLD = """You are a project architect for Sarthak Spaces.
Design a complete, buildable project for the learner.

Output ONLY valid JSON:
{
  "title": "Project title",
  "elevator_pitch": "One sentence: what it does and why it's impressive",
  "directory_structure": {
    "relative/path/file.py": "# starter code or description of what goes here"
  },
  "milestones": [
    {
      "id": "m1",
      "title": "Step 1: ...",
      "concepts_applied": ["concept1"],
      "instructions": "...",
      "starter_code": "...",
      "expected_outcome": "...",
      "estimated_minutes": 45
    }
  ],
  "demo_command": "python src/main.py",
  "stretch_goals": ["add feature X", "deploy to Y"],
  "concepts_reinforced": ["concept1", "concept2"]
}"""

    async def scaffold(
        self,
        project_info: dict,
        ctx: SpaceContext,
        workspace_dir: Path,
    ) -> tuple[ProjectRecord, list[str]]:
        """Create project directory structure. Returns (record, created_paths)."""
        p = ctx.profile.learner
        prompt = (
            f"Project: {project_info['title']}\n"
            f"Description: {project_info['description']}\n"
            f"Domain: {ctx.profile.domain}\n"
            f"Level: {p.skill_level.value}\n"
            f"Background: {p.background or 'technical'}\n"
            f"Mastered concepts: {json.dumps(p.mastered_concepts[-8:])}\n"
            "Design the complete project. Return JSON."
        )
        created: list[str] = []
        raw = await run_llm(self.SYSTEM_SCAFFOLD, prompt)
        data = parse_json_response(raw)

        project_dir = workspace_dir / "projects" / project_info["id"]
        project_dir.mkdir(parents=True, exist_ok=True)

        for rel_path, content in data.get("directory_structure", {}).items():
            target = project_dir / rel_path
            target.parent.mkdir(parents=True, exist_ok=True)
            if not target.exists():
                target.write_text(content, encoding="utf-8")
                created.append(str(target))

        roadmap_content = f"# {data.get('title', project_info['title'])} — Project Roadmap\n\n"
        roadmap_content += f"**{data.get('elevator_pitch', '')}**\n\n"
        roadmap_content += f"Run: `{data.get('demo_command', 'python main.py')}`\n\n"
        for i, ms in enumerate(data.get("milestones", []), 1):
            roadmap_content += f"## Milestone {i}: {ms.get('title', '')}\n"
            roadmap_content += f"{ms.get('instructions', '')}\n\n"
        roadmap_path = project_dir / "ROADMAP.md"
        roadmap_path.write_text(roadmap_content, encoding="utf-8")
        created.append(str(roadmap_path))

        record = ProjectRecord(
            project_id=project_info["id"],
            title=data.get("title", project_info["title"]),
            domain=ctx.profile.domain,
            concepts_applied=data.get("concepts_reinforced", []),
            repo_path=str(project_dir),
            description=data.get("elevator_pitch", project_info.get("description", "")),
        )
        return record, created


class EngagementAgent:
    """
    The voice of Sarthak. Makes dry content magnetic and motivating.
    Adapts tone, analogies, and vocabulary to the learner's exact background.
    Doctors get clinical analogies. Teachers get classroom analogies.
    Non-technical users see WHY first, code last.
    """

    SYSTEM = """You are the master learning experience voice of Sarthak.
Transform structured content into engaging Markdown that feels like
a brilliant friend who happens to be an expert.

Rules:
- HOOK: Open with a surprising fact, real application, or question that creates curiosity.
- Adapt ALL analogies to the learner's background (doctor → clinical, teacher → classroom).
- For non-technical learners: lead with WHY it matters; code is secondary.
- Make math approachable: connect formulas to intuition BEFORE showing symbols.
- Celebrate progress specifically (never generic "great job!").
- If novel approach: 2-3 word appreciation ("Elegant shortcut." / "Creative pivot.").
- End with ONE compelling question to think about.
- Tone: warm, direct, never condescending. Like a mentor who believes in them.
- No emojis.

Return ONLY the final Markdown. No JSON, no preamble."""

    async def render(
        self,
        content: dict,
        learner_background: str,
        xp_earned: int,
        novel_approach: bool = False,
        is_technical: bool = True,
    ) -> str:
        prompt = (
            f"Learner background: {learner_background or 'technical professional'}\n"
            f"Technical: {is_technical}\n"
            f"XP earned: {xp_earned}\n"
            f"Novel approach: {novel_approach}\n"
            f"Content:\n{json.dumps(content, indent=2)}\n\n"
            "Create the engaging Markdown learning message."
        )
        try:
            return await run_llm(self.SYSTEM, prompt)
        except Exception:
            return f"# Learning Session\n\n{json.dumps(content, indent=2)}\n\n*+{xp_earned} XP*"
