from __future__ import annotations

from pathlib import Path


def write_atomic(path: Path, content: str, *, encoding: str = "utf-8") -> None:
    """Atomically write text to a file (write temp → replace)."""
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(content, encoding=encoding)
    tmp.replace(path)
