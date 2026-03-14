"""
data/expert_spaces — curated space templates served via the API.

Each JSON file defines one expert space template. The load_expert_spaces()
function returns them in canonical display order. In future iterations,
community-contributed templates will live alongside these built-in ones,
enabling a marketplace where practitioners sell their curated spaces.
"""
from __future__ import annotations

import json
from importlib.resources import files
from functools import lru_cache

# Canonical display order matches the intended UX progression:
# technical tracks first, exam/research/business in the middle, custom last.
_ORDER = [
    "data_science",
    "ai_engineering",
    "software_engineering",
    "medicine",
    "education",
    "exam_prep",
    "research",
    "business",
    "custom",
]


@lru_cache(maxsize=1)
def load_expert_spaces() -> list[dict]:
    """Return expert space templates in canonical order.

    Reads from the bundled JSON files in this package directory.
    The result is cached after the first call — restart the server to
    pick up changes to the JSON files in development.
    """
    pkg = files(__name__)
    templates: list[dict] = []

    for space_id in _ORDER:
        resource = pkg.joinpath(f"{space_id}.json")
        try:
            templates.append(json.loads(resource.read_text(encoding="utf-8")))
        except Exception:
            pass  # skip missing or malformed files silently

    return templates
