"""
spaces/tools/external_tools.py — External tool detection (filesystem signals)

Pure logic. No LLM. No I/O beyond filesystem stat.
Detects VS Code, Colab, Jupyter, Obsidian, etc. from directory signals.

Public API:
    detect_external_tools(workspace_dir) → list[str]
    get_domain_recommendations(domain)   → list[dict]
    format_guidance(detected, domain)    → str (Markdown)
"""
from __future__ import annotations

from pathlib import Path


TOOL_SIGNALS: dict[str, list[str]] = {
    "VS Code":          [".vscode", ".vscodeignore", ".devcontainer"],
    "Google Colab":     ["colab_", "_colab", "drive.mount"],
    "Jupyter":          [".ipynb", "jupyter_notebook_config"],
    "Obsidian":         [".obsidian"],
    "Anki":             ["anki_", ".apkg"],
    "GitHub":           [".github", ".git"],
    "Docker":           ["Dockerfile", "docker-compose"],
    "MLflow":           ["mlruns", "mlflow"],
    "Weights & Biases": ["wandb", ".wandb"],
}

DOMAIN_RECOMMENDATIONS: dict[str, list[dict]] = {
    "Data Science & AI Engineering": [
        {"tool": "VS Code",
         "why": "Python debugging, Jupyter integration, Git UI",
         "url": "https://code.visualstudio.com/",
         "after_task": "Log results: `sarthak spaces evaluate`"},
        {"tool": "Google Colab",
         "why": "Free GPU for deep learning experiments",
         "url": "https://colab.research.google.com/",
         "after_task": "Save .ipynb to workspace experiments/"},
    ],
    "default": [
        {"tool": "VS Code",
         "why": "Best general-purpose editor",
         "url": "https://code.visualstudio.com/",
         "after_task": "Return to Sarthak to evaluate and track progress"},
        {"tool": "Obsidian",
         "why": "Build a personal knowledge graph as you learn",
         "url": "https://obsidian.md/",
         "after_task": "Link vault to workspace notes/"},
    ],
}


def detect_external_tools(workspace_dir: Path) -> list[str]:
    """Detect external tools from filesystem signals. No file reading."""
    detected: list[str] = []
    try:
        all_names = [
            p.name for p in workspace_dir.rglob("*")
            if len(p.relative_to(workspace_dir).parts) <= 3
        ]
        names_str = " ".join(all_names).lower()
        for tool, signals in TOOL_SIGNALS.items():
            if any(sig.lower() in names_str for sig in signals):
                detected.append(tool)
    except Exception:
        pass
    return detected


def get_domain_recommendations(domain: str) -> list[dict]:
    """Return tool recommendations for a domain."""
    return DOMAIN_RECOMMENDATIONS.get(domain) or DOMAIN_RECOMMENDATIONS["default"]


def format_guidance(detected: list[str], domain: str) -> str:
    """Return Markdown guidance on using external tools with Sarthak."""
    lines = ["## External Tools"]
    if detected:
        lines.append(f"Detected: {', '.join(detected)}")
    lines.append("\nUse these for their strengths, then return to Sarthak:")
    for r in get_domain_recommendations(domain):
        lines.append(f"- **{r['tool']}**: {r['why']}")
        lines.append(f"  After use: {r['after_task']}")
    return "\n".join(lines)
