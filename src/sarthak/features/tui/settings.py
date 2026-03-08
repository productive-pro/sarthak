"""
Sarthak AI — Settings Tab.
Theme picker · config overview · daemon status · keybinding reference.
"""
from __future__ import annotations

import asyncio

from textual.app import ComposeResult
from textual.containers import Horizontal, ScrollableContainer
from textual.widget import Widget
from textual.widgets import Button, DataTable, Label, Select, Static
from pathlib import Path
import tomlkit


# ── Theme preview swatches (block chars) ─────────────────────────────────────
_SWATCH = "██████"

_THEME_CHOICES = [
    ("onedark     — atom inspired",        "onedark"),
    ("midnight    — deep black + red",     "midnight"),
    ("catppuccin  — mocha pastels",        "catppuccin"),
    ("tokyo night — blue-purple neon",     "tokyo"),
    ("gruvbox     — warm amber retro",     "gruvbox"),
    ("nord        — arctic blues",         "nord"),
    ("rose pine   — dusty roses",          "rose_pine"),
]


class SettingsTab(Widget):
    """Settings: theme, config, daemon, keybindings."""

    DEFAULT_CSS = """
    SettingsTab { height: 1fr; }

    #settings-scroll { height: 1fr; padding: 1 2; }

    .section-heading {
        color: $accent;
        text-style: bold;
        margin-top: 1;
        margin-bottom: 0;
    }

    .kv-row {
        height: auto;
        margin-bottom: 0;
    }
    .kv-key  { width: 30; color: $text-muted; }
    .kv-val  { color: $text; }

    #theme-row {
        height: auto;
        margin-top: 1;
        align: left middle;
    }
    #theme-select { width: 45; }
    #theme-apply  { margin-left: 2; }

    #daemon-row   { height: auto; margin-top: 1; }
    #daemon-badge { margin-left: 1; }

    #keybinds-table { margin-top: 1; height: auto; }
    """

    def compose(self) -> ComposeResult:
        with ScrollableContainer(id="settings-scroll"):
            # ── Theme ──────────────────────────────────────────────────────
            yield Label("󰏘  Theme", classes="section-heading title")
            with Horizontal(id="theme-row"):
                yield Select(
                    [(label, val) for label, val in _THEME_CHOICES],
                    value=self._current_theme(),
                    id="theme-select",
                )
                yield Button("Apply", id="theme-apply", variant="primary")

            # ── Active Config ──────────────────────────────────────────────
            yield Label("󰒓  Active Configuration", classes="section-heading title")
            yield Static("", id="config-display")


            # ── Keybinding Reference ───────────────────────────────────────
            yield Label("󰌌  Keybindings", classes="section-heading title")
            tbl = DataTable(id="keybinds-table", zebra_stripes=True, cursor_type="none")
            tbl.add_columns("Key", "Action", "Scope")
            for row in _KEYBINDS:
                tbl.add_row(*row)
            yield tbl

    def on_mount(self) -> None:
        asyncio.create_task(self._load_config_display())

    def on_button_pressed(self, event: Button.Pressed) -> None:
        match event.button.id:
            case "theme-apply":
                sel = self.query_one("#theme-select", Select)
                if sel.value and sel.value != Select.BLANK:
                    theme = str(sel.value)
                    self._save_theme(theme)
                    self.app.apply_theme(theme)

    # ── Config display ────────────────────────────────────────────────────

    async def _load_config_display(self) -> None:
        st = self.query_one("#config-display", Static)
        try:
            from sarthak.core.config import load_config
            cfg = load_config()
            ai = cfg.get("ai", {})
            provider_list = sorted([k for k, v in ai.items() if isinstance(v, dict)])
            lines = [
                f"Provider   : {ai.get('default_provider', '?')}",
                f"Model      : {ai.get('default_model', '?')}",
                f"Providers  : {', '.join(provider_list) if provider_list else '?'}",
                f"Theme      : {cfg.get('tui', {}).get('theme', 'midnight')}",
                f"Log level  : {cfg.get('general', {}).get('log_level', 'info')}",
            ]
            st.update("\n".join(lines))
        except Exception as exc:
            st.update(f"[red]Could not load config: {exc}[/red]")


    # ── Helpers ───────────────────────────────────────────────────────────

    @staticmethod
    def _current_theme() -> str:
        try:
            from sarthak.core.config import load_config
            return load_config().get("tui", {}).get("theme", "midnight")
        except Exception:
            return "midnight"

    @staticmethod
    def _save_theme(theme_name: str) -> None:
        try:
            cfg_path = Path.home() / ".sarthak_ai" / "config.toml"
            if not cfg_path.exists():
                cfg_path = Path(__file__).resolve().parents[3] / "config.toml"
            if not cfg_path.exists():
                return
            doc = tomlkit.parse(cfg_path.read_text())
            tui = doc.setdefault("tui", tomlkit.table())
            tui["theme"] = theme_name
            cfg_path.write_text(tomlkit.dumps(doc))
        except Exception:
            pass


# ── Keybinding reference table ────────────────────────────────────────────────

_KEYBINDS = [
    ("1–5",       "Switch to tab",              "Global"),
    ("r",         "Refresh current tab",         "Global"),
    ("q",         "Quit",                        "Global"),
    ("Esc",       "Unselect / clear focus",      "Global"),
    ("ctrl+p",    "Command palette",             "Global"),
    ("j / k",     "Navigate list down / up",     "Summaries"),
    ("c",         "Copy content to clipboard",   "Chat / Summaries"),
    ("Enter",     "Submit / confirm",            "Chat"),
    ("↑ / ↓",     "Select list item",            "Summaries"),
]
