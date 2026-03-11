from __future__ import annotations

import asyncio
import json
import shutil
from pathlib import Path

from sarthak.core.logging import get_logger
from sarthak.features.ai.agents._base import run_llm
from sarthak.spaces.agents._common import _call_llm_json, detect_platform
from sarthak.spaces.models import SpaceContext

log = get_logger(__name__)


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


# WorkspaceAnalyserAgent lives in _workspace_analyser.py — import directly.
from sarthak.spaces.agents._workspace_analyser import WorkspaceAnalyserAgent  # noqa: F401


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
