"""Web search tool — DuckDuckGo instant answers."""
from __future__ import annotations

import httpx

from sarthak.core.constants import WEB_SEARCH_TIMEOUT, WEB_SEARCH_RELATED_LIMIT, WEB_SEARCH_URL
from sarthak.core.logging import get_logger

log = get_logger(__name__)


async def tool_search_web(query: str) -> str:
    """Search the web via DuckDuckGo. Returns a short abstract + related topics."""
    try:
        async with httpx.AsyncClient(timeout=WEB_SEARCH_TIMEOUT) as c:
            resp = await c.get(
                WEB_SEARCH_URL,
                params={"q": query, "format": "json", "no_html": "1", "t": "sarthak"},
            )
            d = resp.json()
            abstract = d.get("AbstractText", "")
            related = [
                r.get("Text", "")
                for r in d.get("RelatedTopics", [])[:WEB_SEARCH_RELATED_LIMIT]
                if isinstance(r, dict) and r.get("Text")
            ]
            if abstract:
                return f"{abstract}\n\nRelated:\n" + "\n".join(f"• {r}" for r in related)
            return "\n".join(f"• {r}" for r in related) or "No results found."
    except Exception as exc:
        return f"Search failed: {exc}"
