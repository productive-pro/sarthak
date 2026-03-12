"""
Sarthak AI — Tips Tab.
View, search, copy, and delete user-approved recommendations.
"""
from __future__ import annotations

import asyncio
from datetime import timezone

import pyperclip
from textual.app import ComposeResult
from textual.containers import Horizontal, ScrollableContainer, Vertical
from textual.widget import Widget
from textual.widgets import Button, Input, Label, Static

from sarthak.storage.helpers import get_saved_tips, delete_tip


class TipCard(Static):
    """Clickable tip card — press Enter or c to copy, d to delete."""

    DEFAULT_CSS = """
    TipCard {
        height: auto;
        border: solid $border;
        background: $surface;
        padding: 1 2;
        margin-bottom: 1;
    }
    TipCard:hover  { border: solid $accent; }
    TipCard:focus  { border: solid $accent; background: $background; }
    TipCard .tip-ts   { color: $text-muted; margin-bottom: 1; }
    TipCard .tip-body { color: $text; }
    TipCard .tip-hint { color: $text-muted; }
    """

    def __init__(self, tip_id: int, ts: str, body: str, **kw):
        super().__init__(**kw, id=f"tip-{tip_id}")
        self._tip_id = tip_id
        self._ts = ts
        self._body = str(body)

    def compose(self) -> ComposeResult:
        yield Label(f"󰃭 {self._ts}", classes="tip-ts")
        yield Label(self._body, classes="tip-body", markup=False)
        yield Label("[c] copy  [d] delete", classes="tip-hint dim")

    def on_mount(self) -> None:
        self.can_focus = True

    def on_key(self, event) -> None:
        if event.key == "c":
            pyperclip.copy(self._body)
            self.app.notify("Tip copied!", timeout=2)
        elif event.key == "d":
            asyncio.create_task(self._delete())

    async def _delete(self) -> None:
        try:
            await delete_tip(self._tip_id)
            self.remove()
            self.app.notify("Tip deleted.", timeout=2)
        except Exception as exc:
            self.app.notify(f"Delete failed: {exc}", severity="error", timeout=3)


class TipsTab(Widget):
    """Saved agent recommendations — searchable, copyable, deletable."""

    DEFAULT_CSS = """
    TipsTab { height: 1fr; layout: vertical; }

    #tips-header {
        height: 3;
        background: $surface;
        border-bottom: solid $border;
        padding: 0 2;
        align: left middle;
    }
    #tips-header Label { color: $accent; text-style: bold; }
    #tips-hint { color: $text-muted; margin-left: 2; }

    #tips-search-row {
        height: 4;
        padding: 0 2;
        background: $background;
        border-bottom: solid $border;
        align: left middle;
    }
    #tips-search { width: 1fr; margin-right: 2; }
    #tips-refresh { width: 12; }

    #tips-scroll {
        height: 1fr;
        padding: 1 2;
        scrollbar-color: $accent $surface;
    }

    #tips-status {
        height: 1;
        background: $surface;
        color: $text-muted;
        padding: 0 2;
        border-top: solid $border;
    }
    """

    BINDINGS = [("r", "refresh_data", "Refresh")]

    def compose(self) -> ComposeResult:
        with Horizontal(id="tips-header"):
            yield Label("🌟 Saved Tips", classes="title")
            yield Label("  [c] copy  [d] delete  [r] refresh", id="tips-hint")

        with Horizontal(id="tips-search-row"):
            yield Input(placeholder="Search tips…", id="tips-search")
            yield Button("󰑮 Refresh", id="tips-refresh")

        with ScrollableContainer(id="tips-scroll"):
            yield Label("Loading…", id="tips-placeholder", classes="dim")

        yield Label("", id="tips-status")

    def on_mount(self) -> None:
        self._all_tips: list[dict] = []
        asyncio.create_task(self._fetch())

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "tips-refresh":
            self.refresh_data()

    def on_input_changed(self, event: Input.Changed) -> None:
        if event.input.id == "tips-search":
            self._render(filter_text=event.value.strip().lower())

    def refresh_data(self) -> None:
        asyncio.create_task(self._fetch())

    # ── Data loading ──────────────────────────────────────────────────────

    async def _fetch(self) -> None:
        status = self.query_one("#tips-status", Label)
        status.update("Loading…")
        try:
            self._all_tips = await get_saved_tips(limit=100)
            self._render()
            status.update(f"{len(self._all_tips)} tips saved.")
        except Exception as exc:
            status.update(f"[red]{exc}[/red]")

    def _render(self, filter_text: str = "") -> None:
        scroll = self.query_one("#tips-scroll", ScrollableContainer)
        # Remove old cards
        for child in list(scroll.children):
            child.remove()

        # Filter
        tips = self._all_tips
        if filter_text:
            tips = [t for t in tips if filter_text in t.get("tip", "").lower()]

        if not tips:
            msg = "No tips match your search." if filter_text else (
                "No tips yet."
            )
            scroll.mount(Label(msg, classes="dim"))
            return

        for tip in tips:
            tip_id = tip.get("id", 0)
            ts_raw = tip.get("ts")
            if ts_raw:
                if isinstance(ts_raw, str):
                    ts_str = ts_raw.replace("T", " ")[:16]
                else:
                    if ts_raw.tzinfo is None:
                        ts_raw = ts_raw.replace(tzinfo=timezone.utc)
                    ts_str = ts_raw.astimezone().strftime("%b %d %Y, %I:%M %p")
            else:
                ts_str = "?"
            body = str(tip.get("tip") or "").strip()
            scroll.mount(TipCard(tip_id, ts_str, body))
