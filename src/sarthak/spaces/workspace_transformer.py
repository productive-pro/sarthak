"""
Sarthak Spaces — WorkspaceTransformer.

Applies expert workspace templates to an existing directory.
Non-destructive: never deletes, only adds.
Cross-platform: generates both .sh (Linux/macOS) and .ps1 (Windows) scripts.
Idempotent: safe to run multiple times.
"""
from __future__ import annotations

from pathlib import Path

from sarthak.core.logging import get_logger
from sarthak.spaces.models import SpaceType

log = get_logger(__name__)


# ── Template definitions ───────────────────────────────────────────────────────

def _ds_ai_template() -> dict:
    return {
        "directories": [
            "notebooks/exploration",
            "notebooks/tutorials",
            "experiments",
            "projects",
            "src",
            "data/raw",
            "data/processed",
            "data/external",
            "models",
            "reports/figures",
            "scripts",
            ".spaces/tasks",
        ],
        "readme_files": {
            "notebooks/README.md": (
                "# Notebooks\n\n"
                "## `exploration/` — Messy, disposable analysis. Move insights to `src/` when they solidify.\n"
                "## `tutorials/` — One notebook per concept. Your personal textbook.\n\n"
                "> **Expert tip**: Use `marimo` for production notebooks — pure Python, git-diffs that make sense.\n"
                "> Keep Jupyter for exploration only.\n\n"
                "```bash\n# Start marimo\nmarimo edit notebooks/tutorials/your_notebook.py\n```"
            ),
            "experiments/README.md": (
                "# Experiments\n\n"
                "Every ML experiment gets a folder: `YYYY-MM-DD_concept_variant/`\n\n"
                "Track everything with **MLflow**:\n\n"
                "```python\nimport mlflow\n"
                "mlflow.set_experiment('gradient_descent')\n"
                "with mlflow.start_run():\n"
                "    mlflow.log_param('lr', 0.01)\n"
                "    mlflow.log_metric('val_loss', 0.23)\n"
                "    mlflow.log_artifact('reports/figures/loss_curve.png')\n```\n\n"
                "> Never run an experiment without logging it. Future-you will thank you."
            ),
            "src/README.md": (
                "# Source Code\n\n"
                "Production-quality Python only. Extracted from notebooks when concepts solidify.\n\n"
                "```\nsrc/\n"
                "  data/       # data loading & preprocessing\n"
                "  features/   # feature engineering\n"
                "  models/     # model definitions & training\n"
                "  evaluate/   # metrics, visualizations, reports\n```\n\n"
                "> Expert rule: If you use it twice, it goes in `src/`."
            ),
            "data/README.md": (
                "# Data\n\n"
                "- `raw/`        → **Never modify.** Original source data, immutable.\n"
                "- `processed/`  → Cleaned, transformed, ready for modeling.\n"
                "- `external/`   → Third-party reference datasets.\n\n"
                "> **Expert tip**: Use DuckDB to query without loading into memory:\n"
                "> ```python\n> import duckdb\n"
                "> duckdb.sql(\"SELECT * FROM 'data/raw/file.csv' LIMIT 5\").df()\n> ```"
            ),
            "models/README.md": (
                "# Models\n\nSaved artifacts, weights, and metadata.\n\n"
                "Naming: `model_name_v1_YYYY-MM-DD.pkl`\n\n"
                "Always save metadata alongside the model:\n"
                "```python\nimport joblib, json\n"
                "joblib.dump(model, 'models/lr_v1.pkl')\n"
                "json.dump({'features': list(X.columns), 'val_score': 0.89},\n"
                "          open('models/lr_v1_meta.json', 'w'))\n```"
            ),
            "reports/README.md": (
                "# Reports\n\nFinal analyses, presentations, and publication-ready figures.\n\n"
                "> Always save figures programmatically — never screenshot:\n"
                "> ```python\n> plt.savefig('reports/figures/loss_curve.png', dpi=150, bbox_inches='tight')\n> ```"
            ),
            "projects/README.md": (
                "# Projects\n\n"
                "Real end-to-end projects. Each subfolder is a complete, shareable project.\n\n"
                "This is your portfolio. Every project you complete goes here.\n\n"
                "> Expert insight: Projects teach 10x more than isolated exercises.\n"
                "> They force you to integrate concepts, debug real issues, and make decisions."
            ),
            ".spaces/README.md": (
                "# Sarthak Spaces\n\n"
                "Learning state managed by Sarthak AI.\n\n"
                "- `tasks/` — current and past learning tasks\n"
                "- `progress.md` — your mastery roadmap\n\n"
                "Do not delete. This is your learning history."
            ),
        },
        "starter_files": {
            "pyproject.toml": (
                "[project]\n"
                "name = \"ai-ds-workspace\"\n"
                "version = \"0.1.0\"\n"
                "requires-python = \">=3.11\"\n"
                "dependencies = [\n"
                "    \"numpy\", \"pandas\", \"polars\",\n"
                "    \"scikit-learn\", \"matplotlib\", \"seaborn\",\n"
                "    \"jupyter\", \"duckdb\", \"mlflow\", \"rich\",\n"
                "]\n\n"
                "[tool.ruff]\n"
                "line-length = 100\n\n"
                "[tool.ruff.lint]\n"
                "select = [\"E\", \"F\", \"I\"]\n"
            ),
            ".editorconfig": (
                "root = true\n\n"
                "[*.py]\n"
                "indent_style = space\n"
                "indent_size = 4\n"
                "end_of_line = lf\n"
                "charset = utf-8\n"
                "trim_trailing_whitespace = true\n"
                "insert_final_newline = true\n"
            ),
            "scripts/setup_env.sh": (
                "#!/usr/bin/env bash\n"
                "# Setup your expert DS/AI environment\n"
                "set -e\n\n"
                "echo '🚀 Setting up Sarthak AI/DS workspace...'\n\n"
                "# Install uv if not present\n"
                "command -v uv >/dev/null 2>&1 || \\\n"
                "    curl -LsSf https://astral.sh/uv/install.sh | sh\n\n"
                "# Install core + expert tools\n"
                "uv sync\n"
                "uv add polars duckdb marimo mlflow rich\n"
                "uv add --dev ruff pytest hypothesis\n\n"
                "echo '✅ Expert environment ready!'\n"
                "echo 'Run: marimo edit notebooks/tutorials/start_here.py'\n"
            ),
            "scripts/setup_env.ps1": (
                "# Setup your expert DS/AI environment on Windows\n"
                "Write-Host '🚀 Setting up Sarthak AI/DS workspace...'\n\n"
                "# Install uv if not present\n"
                "if (-not (Get-Command uv -ErrorAction SilentlyContinue)) {\n"
                "    irm https://astral.sh/uv/install.ps1 | iex\n"
                "}\n\n"
                "uv sync\n"
                "uv add polars duckdb marimo mlflow rich\n"
                "uv add --dev ruff pytest hypothesis\n\n"
                "Write-Host '✅ Expert environment ready!'\n"
            ),
            ".gitignore": (
                "# Python\n__pycache__/\n*.pyc\n*.pyo\n.venv/\ndist/\nbuild/\n*.egg-info/\n\n"
                "# Data (track with DVC instead)\ndata/raw/\ndata/processed/\nmodels/*.pkl\nmodels/*.pt\n\n"
                "# Jupyter\n.ipynb_checkpoints/\n\n"
                "# MLflow\nmlruns/\n\n"
                "# Environment\n.env\n*.env\n"
            ),
        },
    }


def _exam_template() -> dict:
    return {
        "directories": [
            "subjects",
            "flashcards",
            "mock_tests",
            "weak_areas",
            "notes",
            "previous_years",
            ".spaces/tasks",
        ],
        "readme_files": {
            "subjects/README.md": "# Subjects\nOne folder per subject. Organize by chapter.\n",
            "flashcards/README.md": (
                "# Flashcards\n\n"
                "Use **Anki** for spaced repetition — the most evidence-backed memorization tool.\n\n"
                "Export your deck after each study session.\n"
                "> Research shows: spaced repetition beats re-reading by 200-400%."
            ),
            "mock_tests/README.md": (
                "# Mock Tests\n\n"
                "Rules for effective mock testing:\n"
                "1. Full length, timed, no interruptions.\n"
                "2. Immediately analyse every wrong answer.\n"
                "3. Log error type: conceptual / careless / time-pressure.\n"
                "4. Only errors in `weak_areas/` get re-studied."
            ),
            "weak_areas/README.md": (
                "# Weak Areas\n\n"
                "Track your error patterns here. Fix the root cause, not the symptom.\n\n"
                "Template: `topic | error_type | fix | date_resolved`"
            ),
        },
        "starter_files": {
            "notes/template.md": (
                "# Topic: [Name]\n\n"
                "## Core Concept\n\n"
                "## Key Formulas\n\n"
                "## Common Mistakes\n\n"
                "## Practice Questions\n\n"
                "## Connections to Other Topics\n"
            ),
        },
    }


def _medicine_template() -> dict:
    return {
        "directories": [
            "clinical_data",
            "notebooks/eda",
            "notebooks/modeling",
            "src",
            "reports",
            "literature",
            ".spaces/tasks",
        ],
        "readme_files": {
            "clinical_data/README.md": (
                "# Clinical Data\n\n"
                "⚠️ **Data governance first**: Verify IRB approval and de-identification before any analysis.\n\n"
                "Use MIMIC-III demo dataset for learning: https://physionet.org/content/mimic-demo/\n"
            ),
        },
        "starter_files": {},
    }


def _generic_template() -> dict:
    return {
        "directories": [
            "notes",
            "projects",
            "resources",
            ".spaces/tasks",
        ],
        "readme_files": {},
        "starter_files": {},
    }


# ── Template registry ──────────────────────────────────────────────────────────

TEMPLATES: dict[SpaceType, dict] = {
    SpaceType.DATA_SCIENCE:   _ds_ai_template(),
    SpaceType.AI_ENGINEERING: _ds_ai_template(),
    SpaceType.EXAM_PREP:      _exam_template(),
    SpaceType.MEDICINE:       _medicine_template(),
}


# ── WorkspaceTransformer ───────────────────────────────────────────────────────

class WorkspaceTransformer:
    """
    Applies the expert workspace template.
    Safe to run multiple times — idempotent.
    """

    def __init__(self, workspace_dir: str | Path):
        self.workspace_dir = Path(workspace_dir).resolve()

    def transform(
        self,
        space_type: SpaceType = SpaceType.DATA_SCIENCE,
    ) -> list[str]:
        """Apply expert workspace template. Returns list of created paths."""
        template = TEMPLATES.get(space_type, _generic_template())
        created: list[str] = []

        for d in template.get("directories", []):
            target = self.workspace_dir / d
            target.mkdir(parents=True, exist_ok=True)
            created.append(str(target))

        for rel, content in template.get("readme_files", {}).items():
            target = self.workspace_dir / rel
            target.parent.mkdir(parents=True, exist_ok=True)
            if not target.exists():
                target.write_text(content, encoding="utf-8")
                created.append(str(target))

        for rel, content in template.get("starter_files", {}).items():
            target = self.workspace_dir / rel
            target.parent.mkdir(parents=True, exist_ok=True)
            if not target.exists():
                target.write_text(content, encoding="utf-8")
                created.append(str(target))

        self._write_progress_tracker(space_type)
        return created

    def _write_progress_tracker(self, space_type: SpaceType) -> None:
        progress = self.workspace_dir / ".spaces" / "progress.md"
        progress.parent.mkdir(parents=True, exist_ok=True)
        if progress.exists():
            return  # Don't overwrite progress

        if space_type in (SpaceType.DATA_SCIENCE, SpaceType.AI_ENGINEERING):
            content = (
                "# Mastery Roadmap\n\n"
                "Auto-updated by Sarthak after each session.\n\n"
                "## 🔵 Foundation\n"
                "- [ ] Python basics\n- [ ] NumPy\n- [ ] Pandas\n- [ ] Statistics\n\n"
                "## 🟡 Core ML\n"
                "- [ ] Linear regression (derive)\n- [ ] Gradient descent (implement)\n- [ ] scikit-learn pipelines\n\n"
                "## 🟠 Deep Learning\n"
                "- [ ] Neural networks from scratch\n- [ ] Backpropagation\n- [ ] PyTorch\n\n"
                "## 🔴 Advanced\n"
                "- [ ] Transformers\n- [ ] MLOps\n- [ ] Production deployment\n\n"
                "## 🏆 Expert\n"
                "- [ ] Research replication\n- [ ] Custom architectures\n"
            )
        elif space_type == SpaceType.EXAM_PREP:
            content = (
                "# Exam Prep Roadmap\n\n"
                "## Phase 1: Foundation\n- [ ] Understand exam pattern\n- [ ] Build study schedule\n\n"
                "## Phase 2: Core Subjects\n- [ ] Subject-by-subject coverage\n\n"
                "## Phase 3: Practice\n- [ ] Previous year questions\n- [ ] Mock tests\n\n"
                "## Phase 4: Weak Area Elimination\n- [ ] Targeted drilling\n\n"
                "## Phase 5: Peak Performance\n- [ ] Full-length tests under exam conditions\n"
            )
        else:
            content = "# Mastery Roadmap\n\nAuto-updated by Sarthak after each session.\n"

        progress.write_text(content, encoding="utf-8")
