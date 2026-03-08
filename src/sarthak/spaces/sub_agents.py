"""
Sarthak Spaces — Sub-agents.

Each agent has ONE sharp responsibility. All are stateless.
Pass SpaceContext or primitives in, get structured output back.

Agents:
  EnvironmentAgent         → scan real OS, detect tools, generate install commands
  CurriculumAgent          → adaptive ZPD-based concept selection
  MathAgent                → deep mathematical explanation at the right level
  TaskBuilderAgent         → hands-on tasks with real-world hooks
  ProjectAgent             → scaffold real projects the learner builds end-to-end
  EngagementAgent          → transform dry content into magnetic Markdown
  AssessmentAgent          → evaluate submissions; detect novel approaches
  WorkspaceAgent           → reshape directory to mirror expert environment
  SpacedRepetitionAgent    → SM-2 review scheduling
  BadgeAgent               → achievement system
  QuickTestAgent           → 5-minute QuickTests
  OnboardingAgent          → detect background + personalize first session
  WorkspaceAnalyserAgent   → read workspace state; produce Optimal_Learn.md for orchestrator
  ExternalToolsAgent       → detect and suggest external tools (VS Code, Google Colab, etc.)
"""
from __future__ import annotations

import json
import shutil
import sys
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path

from sarthak.core.logging import get_logger
from sarthak.features.ai.agents._base import parse_json_response, run_llm
from sarthak.spaces.models import (
    ConceptMastery,
    LearningTask,
    ProjectRecord,
    SkillLevel,
    SpaceContext,
    SpaceProfile,
)

log = get_logger(__name__)


def detect_platform() -> str:
    """Return 'windows', 'darwin', or 'linux'."""
    s = sys.platform
    if s.startswith("win"):
        return "windows"
    if s == "darwin":
        return "darwin"
    return "linux"


def is_technical(background: str) -> bool:
    """Return True when the learner background string suggests a technical role."""
    keywords = {"engineer", "developer", "programmer", "coder", "cs", "tech",
                "software", "data", "analyst", "researcher", "scientist"}
    return any(k in background.lower() for k in keywords)


async def _call_llm_json(system: str, prompt: str, fallback: dict, *, tag: str) -> dict:
    """Call LLM and parse JSON response. Returns fallback on any error."""
    try:
        raw = await run_llm(system, prompt)
        return parse_json_response(raw)
    except Exception as exc:
        log.warning(f"{tag}_failed", error=str(exc))
        return fallback


# ══════════════════════════════════════════════════════════════════════════════
# EnvironmentAgent — real OS scan + tool recommendations
# ══════════════════════════════════════════════════════════════════════════════

class EnvironmentAgent:
    """
    Scans the REAL OS: PATH, Python packages, system tools.
    No guessing — uses shutil.which + importlib.
    LLM only for recommendations and install commands.
    """

    CLI_TOOLS = [
        "uv", "python", "python3", "jupyter", "pip", "conda", "ruff",
        "git", "docker", "node", "mlflow", "dvc", "marimo", "anki", "obsidian",
    ]
    PYTHON_PACKAGES = [
        "numpy", "pandas", "polars", "scikit-learn", "torch", "tensorflow",
        "matplotlib", "seaborn", "duckdb", "mlflow", "hypothesis", "rich",
        "plotly", "xgboost", "lightgbm", "transformers", "datasets",
        "pydantic", "fastapi", "httpx", "lifelines", "pydicom", "gradio",
        "streamlit", "pytest",
    ]

    SYSTEM = """You are an expert environment architect.
Given a REAL scan of installed tools, output ONLY valid JSON:
{
  "missing": [
    {
      "name": "polars",
      "priority": "high",
      "category": "speed",
      "install_linux": "uv add polars",
      "install_mac": "uv add polars",
      "install_windows": "uv add polars",
      "why": "10-50x faster than pandas"
    }
  ],
  "config_snippets": {"pyproject.toml": "..."},
  "summary": "2-sentence summary"
}
Prioritize high-impact tools for the domain and skill level."""

    async def scan(self, ctx: SpaceContext) -> dict:
        os_platform = detect_platform()

        installed_cli = [t for t in self.CLI_TOOLS if shutil.which(t)]
        installed_pkg: list[str] = []
        import importlib.util
        for pkg in self.PYTHON_PACKAGES:
            try:
                if importlib.util.find_spec(pkg.replace("-", "_")):
                    installed_pkg.append(pkg)
            except Exception:
                pass

        all_installed = sorted(set(installed_cli + installed_pkg))
        recommended = [t.name for t in ctx.profile.recommended_tools]
        missing = [n for n in recommended if n not in all_installed]

        prompt = (
            f"Domain: {ctx.profile.domain}\n"
            f"Level: {ctx.profile.learner.skill_level.value}\n"
            f"Platform: {os_platform}\n"
            f"Installed: {json.dumps(all_installed)}\n"
            f"Missing from recommended: {json.dumps(missing[:12])}\n"
            "Return JSON with prioritized missing tools and install commands."
        )
        result = await _call_llm_json(self.SYSTEM, prompt, {
            "missing": [
                {"name": n, "priority": "medium", "category": "core",
                 "install_linux": f"uv add {n}", "install_mac": f"uv add {n}",
                 "install_windows": f"uv add {n}", "why": ""}
                for n in missing[:6]
            ],
            "config_snippets": {},
            "summary": f"Found {len(all_installed)} tools. {len(missing)} expert tools missing.",
        }, tag="environment_agent")
        result["installed"] = all_installed
        result["platform"] = os_platform
        return result


# ══════════════════════════════════════════════════════════════════════════════
# OnboardingAgent — detect background, set personalization
# ══════════════════════════════════════════════════════════════════════════════

class OnboardingAgent:
    """
    On first session, detects learner background from free-form text,
    sets is_technical flag, infers goal, recommends starting level.
    Critical for non-technical users (doctors, teachers) who need
    completely different framing.
    """

    SYSTEM = """You are a learning diagnostic expert.
From a learner's self-description, infer their profile.
Output ONLY valid JSON:
{
  "background_category": "doctor|teacher|engineer|student|manager|researcher|other",
  "is_technical": true|false,
  "inferred_goal": "specific goal from their description",
  "recommended_start_level": "novice|beginner|intermediate|advanced",
  "first_concept": "exact concept name to start with",
  "learning_style_hint": "visual|textual|hands-on|problem-first",
  "motivating_hook": "one compelling sentence that will excite THIS person about the domain",
  "welcome_message": "warm 2-3 sentence personalized welcome (use their background for analogy)"
}"""

    async def analyze(self, background: str, goal: str, domain: str) -> dict:
        prompt = (
            f"Domain they want to learn: {domain}\n"
            f"Their background: {background}\n"
            f"Their stated goal: {goal or 'not specified'}\n"
            "Analyze and return JSON."
        )
        return await _call_llm_json(self.SYSTEM, prompt, {
            "background_category": "other",
            "is_technical": False,
            "inferred_goal": goal or "mastery",
            "recommended_start_level": "novice",
            "first_concept": "basics",
            "learning_style_hint": "visual",
            "motivating_hook": f"You're about to unlock {domain}.",
            "welcome_message": f"Welcome! Let's start your {domain} journey.",
        }, tag="onboarding_agent")


# ══════════════════════════════════════════════════════════════════════════════
# CurriculumAgent — adaptive ZPD-based concept selection
# ══════════════════════════════════════════════════════════════════════════════

class CurriculumAgent:
    """
    Selects the optimal next concept using Zone of Proximal Development.
    Priority: struggling concepts > review due > new concepts.
    Adapts path to learner goal (exam prep vs projects vs mastery).
    """

    SYSTEM = """You are a world-class adaptive curriculum designer for Sarthak Spaces.
Select the SINGLE BEST next concept using Zone of Proximal Development.

Priority rules:
1. Struggling concepts → fix the gap before moving forward
2. Spaced repetition reviews → weave them in naturally
3. just beyond current mastery, building on what they know
4. If learner goal is exam prep → bias toward high-frequency exam topics
5. If learner goal is projects → bias toward immediately applicable concepts
6. If activity context shows low focus/high distraction → recommend QuickTest or review session
7. If activity context shows long learning session → advance to harder concept

Output ONLY valid JSON:
{
  "next_concept": "exact concept name from available list",
  "why_now": "one sentence: why this concept at this moment for this learner",
  "review_concept": "concept to review (or empty string)",
  "estimated_mastery_time": "e.g. 2 sessions",
  "learning_path": ["next_after_this", "then_this", "then_this"],
  "session_type": "new_concept|review|struggle_fix|project_step|quicktest",
  "suggest_project": true|false
}"""

    async def plan(
        self,
        ctx: SpaceContext,
        available: list[str],
        review_due: list[str],
        activity_context: str = "",
    ) -> dict:
        p = ctx.profile.learner
        prompt = (
            f"Domain: {ctx.profile.domain}\n"
            f"Background: {p.background or 'not specified'}\n"
            f"Goal: {p.goal or 'mastery'}\n"
            f"Level: {p.skill_level.value}\n"
            f"Style: {p.preferred_style}\n"
            f"Mastered (last 6): {json.dumps(p.mastered_concepts[-6:])}\n"
            f"Struggling: {json.dumps(p.struggling_concepts)}\n"
            f"Available new: {json.dumps(available)}\n"
            f"Review due: {json.dumps(review_due)}\n"
            f"Total sessions: {p.total_sessions}\n"
        )
        if activity_context:
            prompt += f"\n{activity_context}\n"
        prompt += "Return JSON."
        return await _call_llm_json(self.SYSTEM, prompt, {
            "next_concept": available[0] if available else "review basics",
            "why_now": "Continuing your learning path.",
            "review_concept": review_due[0] if review_due else "",
            "session_type": "new_concept",
            "suggest_project": False,
        }, tag="curriculum_agent")


# ══════════════════════════════════════════════════════════════════════════════
# MathAgent — mathematical foundations at exactly the right depth
# ══════════════════════════════════════════════════════════════════════════════

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
  "numpy_equivalent": "# Python code showing the math\\nimport numpy as np\\n...",
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


# ══════════════════════════════════════════════════════════════════════════════
# TaskBuilderAgent — concrete hands-on tasks
# ══════════════════════════════════════════════════════════════════════════════

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


# ══════════════════════════════════════════════════════════════════════════════
# ProjectAgent — scaffold and guide real end-to-end projects
# ══════════════════════════════════════════════════════════════════════════════

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


# ══════════════════════════════════════════════════════════════════════════════
# EngagementAgent — transform content into magnetic Markdown
# ══════════════════════════════════════════════════════════════════════════════

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


# ══════════════════════════════════════════════════════════════════════════════
# AssessmentAgent — evaluate submissions honestly
# ══════════════════════════════════════════════════════════════════════════════

class AssessmentAgent:
    """
    Evaluates submitted work. Honest, specific, never vague.
    Detects novel approaches — creative thinking must be recognized.
    """

    SYSTEM = """You are a precise, honest learning assessor for Sarthak Spaces.
Vague feedback ("good job") is useless. Be specific.

Check:
- Does it show UNDERSTANDING or just copying?
- Is the math correctly applied?
- Is there a novel or creative approach? (Recognize it explicitly)
- What specifically is missing or incorrect?

Output ONLY valid JSON:
{
  "mastered": true|false,
  "score": 0-100,
  "strengths": ["specific strength with line reference if code"],
  "gaps": ["specific gap with fix suggestion"],
  "concept_mastered": "concept name if truly mastered, else empty string",
  "concept_struggling": "concept name if clearly struggling, else empty",
  "novel_approach": true|false,
  "novel_approach_description": "what they did creatively (2-3 words if detected)",
  "feedback": "2-3 sentences: honest + constructive + actionable",
  "next_step": "one concrete action"
}"""

    async def evaluate(
        self, task: LearningTask, submission: str
    ) -> dict:
        prompt = (
            f"Task: {task.title}\n"
            f"Concept: {task.concept}\n"
            f"Expected: {task.expected_outcome}\n"
            f"Math foundation: {task.math_foundation}\n"
            f"Submission:\n{submission}\n"
            "Evaluate. Return JSON."
        )
        return await _call_llm_json(self.SYSTEM, prompt, {
            "mastered": False, "score": 0,
            "feedback": "Assessment failed.", "gaps": [], "strengths": [],
            "novel_approach": False, "concept_mastered": "", "concept_struggling": "",
        }, tag="assessment_agent")


# ══════════════════════════════════════════════════════════════════════════════
# WorkspaceAgent — reshape directory to mirror expert environment
# ══════════════════════════════════════════════════════════════════════════════

class WorkspaceAgent:
    """
    Non-destructive workspace reshaper.
    Adds expert-level structure, README files with real expert tips,
    and starter configs. Never deletes existing content.
    Cross-platform: generates both .sh and .ps1 setup scripts.
    """

    SYSTEM = """You are a workspace architect for Sarthak Spaces.
Design a directory structure mirroring how a SENIOR EXPERT organizes their work.

Rules:
- Non-destructive: only add, never delete.
- README files must contain REAL expert tips, not generic descriptions.
- Include setup scripts for Linux (.sh) and Windows (.ps1).
- For DS/AI: notebooks/{exploration,tutorials}/, experiments/, src/, data/{raw,processed,external}/, models/, reports/figures/, scripts/, projects/, .spaces/
- Adapt to domain.

Output ONLY valid JSON:
{
  "directories": ["relative/path"],
  "readme_files": {"path/README.md": "content with real expert tips"},
  "starter_files": {"path/file": "content"},
  "rationale": "why this mirrors expert practice"
}"""

    async def design(self, ctx: SpaceContext) -> dict:
        ws = Path(ctx.workspace_dir)
        existing = [p.name for p in ws.iterdir() if p.is_dir()] if ws.exists() else []
        prompt = (
            f"Domain: {ctx.profile.domain}\n"
            f"Level: {ctx.profile.learner.skill_level.value}\n"
            f"Platform: {detect_platform()}\n"
            f"Existing dirs: {existing}\n"
            "Design expert workspace. Return JSON."
        )
        return await _call_llm_json(self.SYSTEM, prompt,
            {"directories": [], "readme_files": {}, "starter_files": {}, "rationale": "LLM unavailable."},
            tag="workspace_agent")

    async def apply(self, design: dict, workspace_dir: Path) -> list[str]:
        """Apply design. Returns list of created paths."""
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


# ══════════════════════════════════════════════════════════════════════════════
# SpacedRepetitionAgent — SM-2 review scheduling
# ══════════════════════════════════════════════════════════════════════════════

class SpacedRepetitionAgent:
    """SM-2 inspired spaced repetition. Determines which concepts need review."""

    def get_due_reviews(
        self,
        profile: SpaceProfile,
        max_reviews: int = 2,
    ) -> list[str]:
        now = datetime.now(timezone.utc)
        due: list[str] = []
        for concept, mastery in profile.learner.concept_mastery_map.items():
            try:
                if datetime.fromisoformat(mastery.next_review_due) <= now:
                    due.append(concept)
            except Exception:
                pass
        # Fallback: mastered concepts not yet in the map
        if not due:
            for concept in profile.learner.mastered_concepts[-10:]:
                if concept not in profile.learner.concept_mastery_map:
                    due.append(concept)
                if len(due) >= max_reviews:
                    break
        return due[:max_reviews]

    def update_after_review(
        self,
        profile: SpaceProfile,
        concept: str,
        recalled: bool,
    ) -> SpaceProfile:
        now = datetime.now(timezone.utc)
        mastery = profile.learner.concept_mastery_map.get(concept) or ConceptMastery(concept=concept)
        mastery.review_count += 1
        mastery.last_reviewed = now.isoformat()
        if recalled:
            mastery.strength = min(1.0, mastery.strength + 0.2)
            interval_days = min(2 ** mastery.review_count, 30)
        else:
            mastery.strength = max(0.0, mastery.strength - 0.3)
            interval_days = 1
        mastery.next_review_due = (now + timedelta(days=interval_days)).isoformat()
        profile.learner.concept_mastery_map[concept] = mastery
        return profile


# ══════════════════════════════════════════════════════════════════════════════
# BadgeAgent — achievement system
# ══════════════════════════════════════════════════════════════════════════════

class BadgeAgent:
    """Awards achievement badges. Milestones create motivation."""

    BADGES = {
        "first_session":         ("First Step", "Completed first session"),
        "streak_3":              ("On Fire", "3-day streak"),
        "streak_7":              ("Week Warrior", "7-day streak"),
        "streak_30":             ("Diamond Streak", "30-day streak"),
        "level_beginner":        ("Leveling Up", "Reached Beginner"),
        "level_intermediate":    ("Intermediate", "Reached Intermediate"),
        "level_advanced":        ("Advanced", "Reached Advanced"),
        "level_expert":          ("Expert", "Reached Expert"),
        "concepts_10":           ("Explorer", "Mastered 10 concepts"),
        "concepts_25":           ("Deep Thinker", "Mastered 25 concepts"),
        "concepts_50":           ("Thought Leader", "Mastered 50 concepts"),
        "first_project":         ("Builder", "Completed first project"),
        "projects_3":            ("Maker", "Completed 3 projects"),
        "novel_approach":        ("Innovator", "Solved in a novel way"),
        "math_5":                ("Math Master", "Completed 5 math derivations"),
        "quick_streak_5":        ("Sprint Master", "5 quicktests in a row"),
    }

    def check_and_award(
        self,
        profile: SpaceProfile,
        context: dict,
    ) -> list[str]:
        earned: list[str] = []
        existing = set(profile.learner.badges)

        def award(badge_id: str) -> None:
            name, _ = self.BADGES[badge_id]
            if name not in existing:
                profile.learner.badges.append(name)
                earned.append(name)

        s = profile.learner.total_sessions
        streak = profile.learner.streak_days
        mc = len(profile.learner.mastered_concepts)
        level = profile.learner.skill_level
        projects = len(profile.learner.completed_projects)

        if s == 1:
            award("first_session")
        if streak >= 3:
            award("streak_3")
        if streak >= 7:
            award("streak_7")
        if streak >= 30:
            award("streak_30")
        if mc >= 10:
            award("concepts_10")
        if mc >= 25:
            award("concepts_25")
        if mc >= 50:
            award("concepts_50")
        if level == SkillLevel.BEGINNER:
            award("level_beginner")
        if level == SkillLevel.INTERMEDIATE:
            award("level_intermediate")
        if level == SkillLevel.ADVANCED:
            award("level_advanced")
        if level == SkillLevel.EXPERT:
            award("level_expert")
        if projects >= 1:
            award("first_project")
        if projects >= 3:
            award("projects_3")
        if context.get("novel_approach"):
            award("novel_approach")
        if context.get("math_sessions", 0) >= 5:
            award("math_5")

        return earned


# ══════════════════════════════════════════════════════════════════════════════
# QuickTestAgent — 5-minute QuickTests
# ══════════════════════════════════════════════════════════════════════════════

class QuickTestAgent:
    """
    5-minute micro-tasks. Key insight: consistent daily micro-learning
    beats weekly cramming. Perfect for busy professionals.
    """

    SYSTEM = """You are a micro-learning designer for Sarthak Spaces.
Create a focused 5-minute challenge. Types:
- formula_recall: write a formula from memory + explain one term
- code_snippet: write 5-10 lines implementing one idea
- explain_like_5: explain a concept to a beginner
- spot_the_bug: find and fix a bug in provided code
- connect_concepts: describe how two concepts relate

Output ONLY valid JSON:
{
  "type": "formula_recall|code_snippet|explain_like_5|spot_the_bug|connect_concepts",
  "title": "QuickTest title",
  "challenge": "The 5-minute challenge (include code if spot_the_bug)",
  "success_criteria": "How you know you've succeeded",
  "xp_reward": 5
}"""

    async def generate(
        self,
        concept: str,
        level: SkillLevel,
        background: str = "",
        is_technical: bool = True,
        user_prompt: str = "",
        notes_context: str = "",
    ) -> dict:
        challenge_type = "code_snippet" if is_technical else "explain_like_5"
        prompt = (
            f"Concept: {concept}\n"
            f"Level: {level.value}\n"
            f"Background: {background or 'technical'}\n"
            f"Preferred type: {challenge_type}\n"
            f"User request: {user_prompt or 'none'}\n"
            "Generate 5-minute micro-task. Return JSON."
        )
        if notes_context:
            prompt += f"Notes context:\n{notes_context}\n"
        return await _call_llm_json(self.SYSTEM, prompt, {
            "type": challenge_type,
            "title": f"Quick: {concept}",
            "challenge": f"In 5 minutes, implement the core idea of **{concept}** in Python.",
            "success_criteria": "Code runs without errors and demonstrates the concept.",
            "xp_reward": 5,
        }, tag="quicktest_agent")


# ══════════════════════════════════════════════════════════════════════════════
# WorkspaceAnalyserAgent — read workspace state; produce Optimal_Learn.md
# ══════════════════════════════════════════════════════════════════════════════

class WorkspaceAnalyserAgent:
    """
    Reads the actual workspace directory (intelligently — counts dirs first,
    then samples) and the roadmap to produce Optimal_Learn.md.

    Optimal_Learn.md is given to the orchestrator at the start of every session.
    It encodes:
    - What tools are actually present (discovered from filesystem)
    - What learning artefacts exist (notebooks, scripts, projects)
    - Recommended focus for this session
    - External tools the learner appears to use
    - Any AGENTS.md files found (agent-readable info)

    Rule: never read entire files. Use names/counts to infer content.
    """

    SYSTEM = """You are a workspace intelligence analyst for Sarthak Spaces.
Given a snapshot of a learner's workspace, produce a concise Optimal_Learn.md.

This file is read by the orchestrator once per session to personalize learning.

Output format — ONLY Markdown, no JSON, no preamble:

# Optimal_Learn

## Workspace State
(2-3 sentences: what exists, what's recent, what's missing)

## Detected Tools & Environment
(comma-separated list of detected tools/configs)

## Learning Artefacts
(bullet list: notebooks, scripts, experiments found)

## Recommended Session Focus
(1 concrete recommendation based on workspace state)

## External Tools Detected
(any VS Code settings, Google Drive markers, Jupyter configs, etc.)

## Notes for Orchestrator
(anything unusual or important for the orchestrator to know)"""

    def _sample_workspace(self, workspace_dir: Path) -> dict:
        """Intelligently sample workspace without reading file contents."""
        ws = workspace_dir
        if not ws.exists():
            return {"dirs": [], "files": [], "config_files": [], "agents_md": []}

        # Count top-level dirs first
        top_dirs = [p for p in ws.iterdir() if p.is_dir() and not p.name.startswith(".")]
        hidden_dirs = [p for p in ws.iterdir() if p.is_dir() and p.name.startswith(".")]

        # Sample files: if >20 items, just list names; otherwise get structure
        all_files = [p for p in ws.rglob("*") if p.is_file() and not any(
            part.startswith(".") for part in p.relative_to(ws).parts
        )]

        # Limit to first 40 file paths
        sampled_paths = [str(p.relative_to(ws)) for p in all_files[:40]]

        # Look for config files
        found_configs: list[str] = []
        for name in ["pyproject.toml", "requirements.txt", "environment.yml",
                     "Makefile", "docker-compose.yml", "Dockerfile"]:
            if (ws / name).exists():
                found_configs.append(name)
        if (ws / ".vscode").exists():
            found_configs.append(".vscode/")

        # Find AGENTS.md files
        agents_md_paths = list(ws.rglob("AGENTS.md"))
        agents_md_content: list[str] = []
        for p in agents_md_paths[:3]:
            try:
                text = p.read_text(encoding="utf-8")[:600]
                agents_md_content.append(f"[{p.relative_to(ws)}]\n{text}")
            except Exception:
                pass

        return {
            "top_dirs": [d.name for d in top_dirs],
            "hidden_dirs": [d.name for d in hidden_dirs],
            "sampled_files": sampled_paths,
            "config_files": found_configs,
            "agents_md": agents_md_content,
            "total_file_count_estimate": len(all_files),
        }

    async def analyse(self, ctx: SpaceContext) -> str:
        """Produce Optimal_Learn.md content as a string."""
        workspace_dir = Path(ctx.workspace_dir)
        snapshot = self._sample_workspace(workspace_dir)
        p = ctx.profile.learner

        prompt = (
            f"Domain: {ctx.profile.domain}\n"
            f"Learner level: {p.skill_level.value}\n"
            f"Goal: {p.goal or 'mastery'}\n"
            f"Background: {p.background or 'not specified'}\n"
            f"Mastered concepts (last 5): {json.dumps(p.mastered_concepts[-5:])}\n"
            f"Struggling: {json.dumps(p.struggling_concepts)}\n"
            f"Sessions done: {p.total_sessions}\n"
            f"Top-level dirs: {snapshot['top_dirs']}\n"
            f"Config files found: {snapshot['config_files']}\n"
            f"Sampled file paths (first 40): {snapshot['sampled_files']}\n"
            f"Total files estimate: {snapshot['total_file_count_estimate']}\n"
        )
        if snapshot["agents_md"]:
            prompt += f"AGENTS.md content found:\n{'---'.join(snapshot['agents_md'])}\n"

        try:
            return await run_llm(self.SYSTEM, prompt)
        except Exception as exc:
            log.warning("workspace_analyser_failed", error=str(exc))
            return (
                f"# Optimal_Learn\n\n"
                f"## Workspace State\n"
                f"Workspace at `{ctx.workspace_dir}`. "
                f"Dirs: {', '.join(snapshot['top_dirs'][:8])}.\n\n"
                f"## Recommended Session Focus\n"
                f"Continue with current curriculum — {p.mastered_concepts[-1] if p.mastered_concepts else 'basics'} mastered last.\n"
            )

    def write_optimal_learn(self, workspace_dir: Path, content: str) -> Path:
        """Write Optimal_Learn.md to .spaces/ directory."""
        out_dir = workspace_dir / ".spaces"
        out_dir.mkdir(parents=True, exist_ok=True)
        path = out_dir / "Optimal_Learn.md"
        path.write_text(content, encoding="utf-8")
        return path


# ══════════════════════════════════════════════════════════════════════════════
# ExternalToolsAgent — detect and suggest external tools
# ══════════════════════════════════════════════════════════════════════════════

class ExternalToolsAgent:
    """
    Detects which external tools the learner uses (VS Code, Google Colab,
    Jupyter, Obsidian, etc.) and surfaces recommendations to use them WITH
    the Sarthak workspace for maximum effectiveness.

    The learner should always come back to the workspace, but the best tools
    should be used for each task.
    """

    # External tools the learner might use alongside Sarthak
    EXTERNAL_TOOL_SIGNALS: dict[str, list[str]] = {
        "VS Code": [".vscode", ".vscodeignore", ".devcontainer"],
        "Google Colab": ["colab_", "_colab", "drive.mount", "colab.research"],
        "Jupyter": [".ipynb", "jupyter_notebook_config"],
        "Obsidian": [".obsidian"],
        "Anki": ["anki_", ".apkg"],
        "DBeaver": [".dbeaver"],
        "GitHub": [".github", ".git"],
        "Docker": ["Dockerfile", "docker-compose"],
        "MLflow": ["mlruns", "mlflow"],
        "Weights & Biases": ["wandb", ".wandb"],
    }

    # Recommended external tools per domain
    DOMAIN_EXTERNAL_RECOMMENDATIONS: dict[str, list[dict]] = {
        "Data Science & AI Engineering": [
            {"tool": "VS Code", "why": "Python debugging, Jupyter integration, Git UI",
             "url": "https://code.visualstudio.com/",
             "after_task": "After completing a task in VS Code, log results with `sarthak spaces evaluate`"},
            {"tool": "Google Colab", "why": "Free GPU for deep learning experiments",
             "url": "https://colab.research.google.com/",
             "after_task": "Save your .ipynb to the workspace experiments/ folder"},
        ],
        "default": [
            {"tool": "VS Code", "why": "Best general-purpose editor with extensions for any domain",
             "url": "https://code.visualstudio.com/",
             "after_task": "Return to Sarthak to evaluate your work and track progress"},
            {"tool": "Obsidian", "why": "Build a personal knowledge graph as you learn",
             "url": "https://obsidian.md/",
             "after_task": "Link your Obsidian vault to the workspace notes/ folder"},
        ],
    }

    def detect_from_workspace(self, workspace_dir: Path) -> list[str]:
        """Detect external tools from filesystem signals. No file reading."""
        detected: list[str] = []
        try:
            all_names = [
                p.name for p in workspace_dir.rglob("*")
                if len(p.relative_to(workspace_dir).parts) <= 3
            ]
            names_str = " ".join(all_names).lower()
            for tool, signals in self.EXTERNAL_TOOL_SIGNALS.items():
                if any(sig.lower() in names_str for sig in signals):
                    detected.append(tool)
        except Exception:
            pass
        return detected

    def get_recommendations(self, domain: str) -> list[dict]:
        """Return external tool recommendations for a domain."""
        recs = self.DOMAIN_EXTERNAL_RECOMMENDATIONS.get(domain)
        return recs or self.DOMAIN_EXTERNAL_RECOMMENDATIONS["default"]

    def format_guidance(self, detected: list[str], domain: str) -> str:
        """Return Markdown guidance on using external tools with Sarthak."""
        lines = ["## External Tools"]
        if detected:
            lines.append(f"Detected in your workspace: {', '.join(detected)}")
        lines.append("")
        lines.append("Use these tools for their strengths, then return to Sarthak to track progress:")
        recs = self.get_recommendations(domain)
        for r in recs:
            lines.append(f"- **{r['tool']}**: {r['why']}")
            lines.append(f"  After use: {r['after_task']}")
        return "\n".join(lines)
