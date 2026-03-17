"""
spaces/tools/env_scan.py — OS environment scanner

Pure logic. No LLM. Uses shutil.which + importlib.util.
Returns raw scan data; LLM recommendations are a separate concern (skill).

Public API:
    scan_environment(ctx) → dict   {installed, missing, platform}
"""
from __future__ import annotations

import importlib.util
import shutil

from sarthak.spaces.models import SpaceContext


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


def scan_environment(ctx: SpaceContext) -> dict:
    """
    Scan PATH and importlib for installed tools.
    Returns:
        installed: sorted list of found tool names
        missing:   tools in ctx.profile.recommended_tools not installed
        platform:  'linux' | 'darwin' | 'windows'
    """
    from sarthak.spaces.agents._common import detect_platform

    platform     = detect_platform()
    installed_cli = [t for t in CLI_TOOLS if shutil.which(t)]
    installed_pkg: list[str] = []
    for pkg in PYTHON_PACKAGES:
        try:
            if importlib.util.find_spec(pkg.replace("-", "_")):
                installed_pkg.append(pkg)
        except Exception:
            pass

    all_installed = sorted(set(installed_cli + installed_pkg))
    recommended   = [t.name for t in ctx.profile.recommended_tools]
    missing       = [n for n in recommended if n not in all_installed]

    return {
        "installed": all_installed,
        "missing":   missing,
        "platform":  platform,
    }
