"""Generate reference pages for mkdocstrings."""
from __future__ import annotations

from pathlib import Path

MODULES = [
    "sarthak.cli.main",
    "sarthak.core.config",
    "sarthak.features.mcp.server",
    "sarthak.features.tui.app",
    "sarthak.features.ai.agent",
    "sarthak.web.app",
]


def _write(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def main() -> None:
    docs_root = Path(__file__).resolve().parents[1] / "docs"
    ref_root = docs_root / "reference"

    _write(
        ref_root / "index.md",
        "# API Reference\n\nAuto-generated documentation for core modules.\n",
    )

    for module in MODULES:
        _write(
            ref_root / f"{module}.md",
            f"# `{module}`\n\n::: {module}\n",
        )


if __name__ == "__main__":
    main()
