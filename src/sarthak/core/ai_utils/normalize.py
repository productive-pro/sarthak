"""
Shared helpers for normalizing activity events into compact CSV context.
"""
from __future__ import annotations

from collections.abc import Iterable
from typing import Any


def _event_to_dict(event: Any) -> dict:
    if isinstance(event, dict):
        return event
    if hasattr(event, "model_dump"):
        try:
            return event.model_dump()
        except Exception:
            return {}
    if hasattr(event, "dict"):
        try:
            return event.dict()
        except Exception:
            return {}
    return {}


def _clean_field(value: Any) -> str:
    text = str(value or "")
    text = text.replace("●", "").replace("*", "").strip()
    if len(text) > 150:
        text = text[:147] + "..."
    return text.replace(",", ";").replace("\n", " ").strip()


def event_to_row(event: Any) -> str:
    data = _event_to_dict(event)
    etype = data.get("event_type") or getattr(event, "event_type", "")

    if etype == "window.focus":
        app = data.get("app_class", "") or getattr(event, "app_class", "")
        resource = data.get("app_title", "") or getattr(event, "app_title", "")
    elif etype == "terminal.command":
        app = data.get("app_class", "terminal") or "terminal"
        resource = data.get("command", "") or getattr(event, "command", "")
    elif etype == "snapshot.captured":
        app = "snapshot"
        resource = data.get("summary", "") or getattr(event, "summary", "")
    else:
        app = data.get("app_class", "") or getattr(event, "app_class", "") or str(etype)
        resource = data.get("app_title", "") or getattr(event, "app_title", "")

    prev = data.get("prev_app_class", "") or getattr(event, "prev_app_class", "")

    app = _clean_field(app)
    resource = _clean_field(resource)
    prev = _clean_field(prev)

    return f"{app},{resource},{prev}"


def build_activity_csv(events: Iterable[Any], max_events: int | None = None) -> str:
    rows = ["app,resource,from"]
    count = 0
    for event in events:
        if max_events is not None and count >= max_events:
            break
        row_str = event_to_row(event)
        if len(rows) == 1 or rows[-1] != row_str:
            rows.append(row_str)
        count += 1
    return "\n".join(rows)
