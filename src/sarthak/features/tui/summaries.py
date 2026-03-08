"""
Sarthak AI — Summaries Tab.
Left sidebar (30%): daily summaries per date, word-wrapped.
Right pane (70%): full summary for the selected day.
"""
from __future__ import annotations

import asyncio
import textwrap
from datetime import date

import pyperclip
from textual.app import ComposeResult
from textual.containers import Horizontal, ScrollableContainer, Vertical
from textual.reactive import reactive
from textual.widget import Widget
from textual.widgets import Label, ListItem, ListView, Markdown


# ── Sidebar entry ─────────────────────────────────────────────────────────────

class DateItem(ListItem):
    """Date + full summary in the sidebar."""

    DEFAULT_CSS = """
    DateItem {
        padding: 1 2;
        height: auto;
        border-bottom: solid $border;
    }
    DateItem:hover        { background: $surface; }
    DateItem.-highlighted { background: $surface; border-left: thick $accent; }
    DateItem .di-date     { color: $accent; text-style: bold; margin-bottom: 0; }
    DateItem .di-body     { color: $text-muted; }
    """

    def __init__(self, target_date: date, summary_text: str, **kw):
        super().__init__(**kw)
        self.target_date = target_date
        self._summary = summary_text.strip()

    def compose(self):
        yield Label(
            self.target_date.strftime("󰃭  %a, %b %d %Y"),
            classes="di-date",
        )
        body = textwrap.fill(self._summary, width=52) if self._summary else "_No summary._"
        yield Label(body, classes="di-body", markup=False)


# ── Main tab ──────────────────────────────────────────────────────────────────

class SummariesTab(Widget):
    """Daily summaries viewer — split sidebar / detail."""

    DEFAULT_CSS = """
    SummariesTab { height: 1fr; layout: vertical; }

    #sum-header {
        height: 3;
        background: $surface;
        border-bottom: solid $border;
        padding: 0 2;
        align: left middle;
    }
    #sum-header Label { color: $accent; text-style: bold; }
    #sum-hint { color: $text-muted; margin-left: 2; }

    #sum-body { height: 1fr; layout: horizontal; }

    /* sidebar */
    #date-sidebar {
        width: 30%;
        border-right: solid $border;
        height: 1fr;
        layout: vertical;
    }
    #date-list {
        height: 1fr;
        background: $background;
        scrollbar-color: $accent $surface;
    }

    /* detail pane */
    #detail-pane {
        width: 70%;
        height: 1fr;
        padding: 1 2;
        scrollbar-color: $accent $surface;
    }
    #detail-static { width: 1fr; height: auto; color: $text; }

    /* status */
    #sum-status {
        height: 1;
        background: $surface;
        color: $text-muted;
        padding: 0 2;
        border-top: solid $border;
    }
    """

    BINDINGS = [
        ("c", "copy_detail", "Copy"),
        ("r", "refresh_data", "Refresh"),
        ("j", "next_item",   "↓"),
        ("k", "prev_item",   "↑"),
    ]

    _current_md: reactive[str] = reactive("")

    def compose(self) -> ComposeResult:
        with Horizontal(id="sum-header"):
            yield Label("󰃭 Summaries", classes="title")
            yield Label("  [c] copy · [j/k] navigate · [r] refresh", id="sum-hint")

        with Horizontal(id="sum-body"):
            with Vertical(id="date-sidebar"):
                yield ListView(id="date-list")

            with ScrollableContainer(id="detail-pane"):
                yield Markdown(
                    "Select a day on the left to view the full summary.",
                    id="detail-static",
                )

        yield Label("", id="sum-status")

    def on_mount(self) -> None:
        asyncio.create_task(self._populate_sidebar())

    # ── Sidebar ───────────────────────────────────────────────────────────

    async def _populate_sidebar(self) -> None:
        self._set_status("Loading summaries…")
        lst = self.query_one("#date-list", ListView)
        lst.clear()
        try:
            from sarthak.storage.helpers import list_daily_summaries
            rows = await list_daily_summaries(limit=90)
        except Exception as exc:
            self._set_status(f"Error: {exc}")
            return

        if not rows:
            self.query_one("#detail-static", Markdown).update(
                "No summaries yet.\nRun  sarthak summarize  to generate one."
            )
            self._set_status("No summaries.")
            return

        for r in rows:
            d = r.get("date")
            if isinstance(d, str):
                d = date.fromisoformat(d)
            lst.append(DateItem(d, r.get("summary") or ""))

        self._set_status(f"{len(rows)} summaries.")
        # Auto-select first
        if rows:
            lst.index = 0
            self._load_detail(rows[0]["date"])

    # ── Detail pane ───────────────────────────────────────────────────────

    def on_list_view_highlighted(self, event: ListView.Highlighted) -> None:
        if event.item and isinstance(event.item, DateItem):
            self._load_detail(event.item.target_date)

    def _load_detail(self, target_date: date) -> None:
        asyncio.create_task(self._fetch_and_render(target_date))

    async def _fetch_and_render(self, target_date: date) -> None:
        st = self.query_one("#detail-static", Markdown)
        self._set_status(f"Loading {target_date}…")
        st.update("Loading…")
        self._current_md = ""

        try:
            from sarthak.storage.helpers import get_daily_summary
            row = await get_daily_summary(target_date)
        except Exception as exc:
            st.update(f"Error: {exc}")
            self._set_status(f"Failed: {exc}")
            return

        date_label = target_date.strftime("%A, %B %d %Y")

        if not row:
            placeholder = (
                f"## {date_label}\n\n"
                "_No summary found for this day._\n\n"
                "Run `sarthak summarize` to generate one."
            )
            self._current_md = placeholder
            st.update(placeholder)
            self._set_status(f"{date_label} · no summary")
            return

        summary = row.get("summary", "").strip()
        md = "\n".join(
            [
                f"# Daily Summary - {date_label}",
                "",
                summary or "_Summary text missing._",
            ]
        )
        self._current_md = md
        st.update(md)
        self._set_status(f"{date_label} · summary")

    # ── Actions ───────────────────────────────────────────────────────────

    def action_copy_detail(self) -> None:
        if self._current_md:
            pyperclip.copy(self._current_md)
            self.notify("Copied to clipboard!", timeout=2)
        else:
            self.notify("Nothing to copy.", severity="warning", timeout=2)

    def refresh_data(self) -> None:
        asyncio.create_task(self._populate_sidebar())

    def action_next_item(self) -> None:
        lst = self.query_one("#date-list", ListView)
        if lst.index is not None:
            lst.index = min(lst.index + 1, len(list(lst.children)) - 1)

    def action_prev_item(self) -> None:
        lst = self.query_one("#date-list", ListView)
        if lst.index is not None:
            lst.index = max(lst.index - 1, 0)

    def _set_status(self, msg: str) -> None:
        try:
            self.query_one("#sum-status", Label).update(msg)
        except Exception:
            pass
