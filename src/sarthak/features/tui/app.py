"""
Sarthak AI — Textual TUI Root App.
Tabs: Dashboard · Chat · Summaries · Alerts · Settings
Theme-aware: reads theme from config.toml, live-switchable via Settings tab.
"""
from __future__ import annotations

from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.widgets import Footer, Header, TabbedContent, TabPane

from sarthak.features.tui.theme import build_css, load_active_theme
from sarthak.features.tui.dashboard import DashboardTab
from sarthak.features.tui.chat import ChatTab
from sarthak.features.tui.summaries import SummariesTab
from sarthak.features.tui.alerts import AlertsTab
from sarthak.features.tui.settings import SettingsTab

# Map tab id → widget class name, for targeted refresh
_TAB_WIDGET: dict[str, str] = {
    "dashboard": "DashboardTab",
    "summaries": "SummariesTab",
    "alerts":    "AlertsTab",
}


class SarthakApp(App):
    """Sarthak AI self-analytics TUI."""

    TITLE     = "󰋙 Sarthak"
    SUB_TITLE = "Privacy-first self-analytics"
    ENABLE_MOUSE = False

    BINDINGS = [
        Binding("1", "switch_tab('dashboard')", "Dashboard",  show=True),
        Binding("2", "switch_tab('chat')",      "Chat",       show=True),
        Binding("3", "switch_tab('summaries')", "Summaries",  show=True),
        Binding("4", "switch_tab('alerts')",    "Alerts",     show=True),
        Binding("5", "switch_tab('settings')",  "Settings",   show=True),
        Binding("r",      "refresh_active",  "Refresh", show=True),
        Binding("escape", "cancel_focus",    "Unselect", show=False),
        Binding("q",      "quit",            "Quit",    show=True),
        Binding("ctrl+p", "command_palette", "Palette", show=False),
    ]

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._theme_obj = load_active_theme()
        self.CSS = build_css(self._theme_obj)

    def compose(self) -> ComposeResult:
        yield Header(show_clock=True)
        with TabbedContent(initial="dashboard"):
            with TabPane("󰋙 Dashboard",  id="dashboard"):
                yield DashboardTab()
            with TabPane("󱚞 Chat",       id="chat"):
                yield ChatTab()
            with TabPane("󰃭 Summaries",  id="summaries"):
                yield SummariesTab()
            with TabPane(" Alerts",     id="alerts"):
                yield AlertsTab()
            with TabPane("󰒓 Settings",   id="settings"):
                yield SettingsTab()
        yield Footer()

    def action_switch_tab(self, tab_id: str) -> None:
        self.query_one(TabbedContent).active = tab_id

    def action_refresh_active(self) -> None:
        """Refresh only the currently visible tab widget."""
        active_id = self.query_one(TabbedContent).active

        # Try direct CSS child selector first (works for all tabs)
        for widget in self.query(f"#{active_id} > *"):
            if hasattr(widget, "refresh_data"):
                widget.refresh_data()
                return

        # Fallback: look up the known widget class for this tab id
        cls_name = _TAB_WIDGET.get(active_id)
        if cls_name:
            for widget in self.query(cls_name):
                if hasattr(widget, "refresh_data"):
                    widget.refresh_data()
                    return

        # Active tab has no refresh_data — silently do nothing
        log_no_refresh = getattr(self, "_log", None)
        if log_no_refresh:
            log_no_refresh.debug("no refresh_data on active tab", tab=active_id)

    def action_cancel_focus(self) -> None:
        """Clear focus/selection for the currently focused widget."""
        focused = self.focused
        if focused is None:
            return
        try:
            if hasattr(focused, "clear_selection"):
                focused.clear_selection()
            if hasattr(focused, "index"):
                focused.index = None
        except Exception:
            pass
        self.set_focus(None)

    def apply_theme(self, theme_name: str) -> None:
        """Hot-swap the CSS theme at runtime."""
        from sarthak.features.tui.theme import get_theme
        self._theme_obj = get_theme(theme_name)
        self.CSS = build_css(self._theme_obj)
        try:
            self.refresh_css()
        except Exception:
            self.refresh(layout=True)
        self.notify(f"Theme → {theme_name}", timeout=2)


def main() -> None:
    SarthakApp().run()
