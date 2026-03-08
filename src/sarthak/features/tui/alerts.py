"""
Sarthak AI — Alerts Tab.
Shows recent alerts, notifications, and LLM errors.
"""
from __future__ import annotations

import asyncio

from textual.app import ComposeResult
from textual.containers import Horizontal
from textual.widget import Widget
from textual.widgets import Button, DataTable, Label

from sarthak.storage.helpers import get_alerts


class AlertsTab(Widget):
    """Recent alerts and notifications."""

    DEFAULT_CSS = """
    AlertsTab { height: 1fr; layout: vertical; }

    #alerts-header {
        height: 3;
        background: $surface;
        border-bottom: solid $border;
        padding: 0 2;
        align: left middle;
    }
    #alerts-header Label { color: $accent; text-style: bold; }
    #alerts-hint { color: $text-muted; margin-left: 2; }

    #alerts-table { height: 1fr; }

    #alerts-status {
        height: 1;
        background: $surface;
        color: $text-muted;
        padding: 0 2;
        border-top: solid $border;
    }
    """

    BINDINGS = [("r", "refresh_data", "Refresh")]

    def compose(self) -> ComposeResult:
        with Horizontal(id="alerts-header"):
            yield Label("\uf0a2 Alerts", classes="title")
            yield Label("  [r] refresh", id="alerts-hint")
            yield Button("Refresh", id="alerts-refresh")

        yield DataTable(id="alerts-table", zebra_stripes=True, cursor_type="row")
        yield Label("", id="alerts-status")

    def on_mount(self) -> None:
        tbl = self.query_one("#alerts-table", DataTable)
        tbl.add_columns("Time", "Level", "Source", "Message")
        asyncio.create_task(self._load())

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "alerts-refresh":
            self.refresh_data()

    def refresh_data(self) -> None:
        asyncio.create_task(self._load())

    async def _load(self) -> None:
        status = self.query_one("#alerts-status", Label)
        status.update("Loading…")
        try:
            rows = await get_alerts(limit=200)

            tbl = self.query_one("#alerts-table", DataTable)
            tbl.clear()

            for r in rows:
                ts_raw = str(r.get("ts") or "")
                ts_str = ts_raw.replace("T", " ")[:16] if ts_raw else "?"
                tbl.add_row(
                    ts_str,
                    str(r.get("level", "")),
                    str(r.get("source", "")),
                    str(r.get("message", ""))[:200],
                )

            status.update(f"{len(rows)} alert(s)")
        except Exception as exc:
            status.update(f"[red]{exc}[/red]")
