"""
Sarthak AI — Dashboard Tab.
Primary: Sarthak Spaces status and progress.
Auto-refreshes every 5 s.
"""
from __future__ import annotations

import asyncio
from datetime import datetime
from pathlib import Path

from textual.app import ComposeResult
from textual.containers import Horizontal, ScrollableContainer, Vertical
from textual.widget import Widget
from textual.widgets import DataTable, Label, Static

from sarthak.core.config import load_config

_REFRESH = 5.0


def _bar(value: float, max_value: float, width: int = 14) -> str:
    """Unicode block progress bar."""
    filled = int(value / max(max_value, 1) * width)
    return "█" * filled + "░" * (width - filled)


class StatCard(Static):
    """Labeled stat block."""

    DEFAULT_CSS = """
    StatCard {
        height: 5;
        border: solid $border;
        background: $surface;
        padding: 0 2;
        min-width: 18;
        margin-right: 1;
        content-align: left middle;
    }
    StatCard .card-label { color: $text-muted; text-style: none; }
    StatCard .card-value  { color: $accent; text-style: bold; }
    """

    def __init__(self, label: str, card_id: str = "", **kw):
        super().__init__(**kw, id=card_id or None)
        self._label = label

    def compose(self) -> ComposeResult:
        yield Label(self._label, classes="card-label")
        yield Label("—", id=f"{self.id}-val", classes="card-value")

    def set_value(self, v: str) -> None:
        try:
            self.query_one(f"#{self.id}-val", Label).update(v)
        except Exception:
            pass


class DashboardTab(Widget):
    """Dashboard: Spaces overview."""

    DEFAULT_CSS = """
    DashboardTab { height: 1fr; layout: vertical; }

    #dash-header {
        height: 3;
        background: $surface;
        border-bottom: solid $border;
        padding: 0 2;
        align: left middle;
    }

    #stat-strip {
        height: 7;
        padding: 1 1;
        background: $background;
    }

    #dash-body { height: 1fr; layout: horizontal; }

    /* left: spaces feed */
    #spaces-pane {
        width: 60%;
        height: 1fr;
        border-right: solid $border;
        layout: vertical;
    }
    #spaces-label {
        height: 2;
        padding: 0 2;
        background: $surface;
        border-bottom: solid $border;
        color: $accent;
        text-style: bold;
        content-align: left middle;
    }
    #spaces-table { height: 1fr; }

    /* right: session details */
    #aw-pane { width: 40%; height: 1fr; layout: vertical; }
    #aw-label {
        height: 2;
        padding: 0 2;
        background: $surface;
        border-bottom: solid $border;
        color: $accent;
        text-style: bold;
        content-align: left middle;
    }
    #aw-scroll  { height: 1fr; padding: 1 2; }

    #dash-status {
        height: 1;
        background: $surface;
        color: $text-muted;
        padding: 0 2;
        border-top: solid $border;
    }
    """

    def compose(self) -> ComposeResult:
        with Horizontal(id="dash-header"):
            yield Label("Sarthak Spaces Dashboard", classes="title")
            yield Label("  auto-refreshes every 5 s", classes="dim")

        with Horizontal(id="stat-strip"):
            yield StatCard("Active Spaces",  card_id="card-spaces")
            yield StatCard("Sessions Today", card_id="card-sessions")
            yield StatCard("Active Minutes", card_id="card-active")
            yield StatCard("Current App",    card_id="card-app")

        with Horizontal(id="dash-body"):
            with Vertical(id="spaces-pane"):
                yield Label("Spaces — recent sessions", id="spaces-label")
                yield DataTable(
                    id="spaces-table", zebra_stripes=True, cursor_type="row"
                )

            with Vertical(id="aw-pane"):
                yield Label("Recent session details", id="aw-label")
                with ScrollableContainer(id="aw-scroll"):
                    yield Static("", id="aw-content")

        yield Label("", id="dash-status")

    def on_mount(self) -> None:
        tbl = self.query_one("#spaces-table", DataTable)
        tbl.add_columns("Space", "Concept", "Active min", "Depth", "When")
        try:
            cfg = load_config()
            refresh = float(cfg.get("tui", {}).get("refresh_interval", _REFRESH))
        except Exception:
            refresh = _REFRESH
        self._timer = self.set_interval(refresh, self.refresh_data)
        asyncio.create_task(self._load())

    def refresh_data(self) -> None:
        asyncio.create_task(self._load())

    def _set_empty_state(self, message: str) -> None:
        tbl = self.query_one("#spaces-table", DataTable)
        tbl.clear()
        tbl.add_row("—", "—", "—", "—", message)
        self.query_one("#aw-content", Static).update(message)
        for cid in ("card-spaces", "card-sessions", "card-active", "card-app"):
            self.query_one(f"#{cid}", StatCard).set_value("—")

    async def _load(self) -> None:
        status = self.query_one("#dash-status", Label)
        status.update("Refreshing...")
        try:
            await self._load_spaces()
            status.update(f"Updated {datetime.now().strftime('%H:%M:%S')}")
        except Exception as exc:
            self._set_empty_state("Load failed.")
            status.update(f"[red]Error: {exc}[/red]")

    # ── Spaces pane ──────────────────────────────────────────────────────────

    async def _load_spaces(self) -> None:
        from sarthak.spaces.store import list_spaces
        from sarthak.spaces.session_tracker import load_sessions

        try:
            spaces = list_spaces()
        except Exception:
            spaces = []

        tbl = self.query_one("#spaces-table", DataTable)
        tbl.clear()

        total_active_today = 0
        total_sessions_today = 0
        today = datetime.now().date()
        rows_added = 0

        for space in spaces:
            space_dir = Path(space.get("directory", ""))
            name = space.get("name") or space_dir.name
            if not space_dir.exists():
                continue
            sessions = load_sessions(space_dir, limit=30)
            today_sessions = [
                s for s in sessions
                if s.started_at and s.started_at.date() == today
            ]
            total_sessions_today += len(today_sessions)
            active_today = sum(
                s.signals.active_seconds for s in today_sessions
            ) // 60

            # Show the most recent session for each space
            recent = sessions[-1] if sessions else None
            if recent:
                when = recent.started_at.strftime("%H:%M") if recent.started_at else "—"
                active_min = recent.signals.active_seconds // 60
                depth = f"{recent.signals.depth_score:.2f}" if recent.signals.depth_score else "—"
                tbl.add_row(
                    name[:20],
                    (recent.concept or "—")[:30],
                    str(active_min),
                    depth,
                    when,
                )
                total_active_today += active_today
                rows_added += 1

        if rows_added == 0:
            tbl.add_row("—", "No sessions yet", "—", "—", "run `sarthak spaces session`")

        self.query_one("#card-spaces",   StatCard).set_value(str(len(spaces)))
        self.query_one("#card-sessions", StatCard).set_value(str(total_sessions_today))
        self.query_one("#card-active",   StatCard).set_value(f"{total_active_today} min")

        # Populate right pane with recent session details
        await self._load_session_details(spaces)

    # ── Session details pane ─────────────────────────────────────────────────

    async def _load_session_details(self, spaces: list) -> None:
        from sarthak.spaces.session_tracker import load_sessions

        aw_content = self.query_one("#aw-content", Static)
        self.query_one("#card-app", StatCard).set_value("—")

        lines: list[str] = []
        for space in spaces[:5]:
            d = Path(space.get("directory", ""))
            if not d.exists():
                continue
            sessions = load_sessions(d, limit=5)
            for s in sessions:
                name = space.get("name", d.name)[:14].ljust(14)
                concept = (s.concept or "—")[:20]
                active_min = s.signals.active_seconds // 60
                depth = f"{s.signals.depth_score:.2f}" if s.signals.depth_score else "—"
                lines.append(f"{name}  {concept:<20}  {active_min}m  d={depth}")

        aw_content.update("\n".join(lines) if lines else "No recent sessions.")
