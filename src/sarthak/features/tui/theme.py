"""
Sarthak AI — TUI Theme System.
Single source of truth for all colors and CSS variables.
Switch themes by changing ACTIVE_THEME.
"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Theme:
    name: str
    bg: str           # main background
    bg2: str          # panel / header background
    bg3: str          # subtle surface (borders, inactive)
    accent: str       # primary accent (red/teal/blue)
    accent2: str      # secondary accent
    text: str         # primary text
    text_dim: str     # muted / labels
    text_bright: str  # headings / titles
    success: str
    warning: str
    error: str
    border: str       # panel borders
    cursor_bg: str    # table cursor bg
    cursor_fg: str    # table cursor fg


# ── Built-in themes ───────────────────────────────────────────────────────────

THEMES: dict[str, Theme] = {
    "onedark": Theme(
        name="onedark",
        bg="#282c34",
        bg2="#2c313c",
        bg3="#353a42",
        accent="#61AFEF",
        accent2="#C678DD",
        text="#abb2bf",
        text_dim="#5c5f69",
        text_bright="#e6eef6",
        success="#98c379",
        warning="#e5c07b",
        error="#e06c75",
        border="#3b4048",
        cursor_bg="#61AFEF",
        cursor_fg="#282c34",
    ),
    "midnight": Theme(
        name="midnight",
        bg="#0d1117",
        bg2="#161b22",
        bg3="#21262d",
        accent="#e94560",
        accent2="#58a6ff",
        text="#c9d1d9",
        text_dim="#6e7681",
        text_bright="#f0f6fc",
        success="#3fb950",
        warning="#d29922",
        error="#f85149",
        border="#30363d",
        cursor_bg="#e94560",
        cursor_fg="#0d1117",
    ),
    "catppuccin": Theme(
        name="catppuccin",
        bg="#1e1e2e",
        bg2="#181825",
        bg3="#313244",
        accent="#cba6f7",
        accent2="#89b4fa",
        text="#cdd6f4",
        text_dim="#6c7086",
        text_bright="#f5c2e7",
        success="#a6e3a1",
        warning="#fab387",
        error="#f38ba8",
        border="#45475a",
        cursor_bg="#cba6f7",
        cursor_fg="#1e1e2e",
    ),
    "tokyo": Theme(
        name="tokyo",
        bg="#1a1b26",
        bg2="#16161e",
        bg3="#292e42",
        accent="#7aa2f7",
        accent2="#bb9af7",
        text="#a9b1d6",
        text_dim="#565f89",
        text_bright="#c0caf5",
        success="#9ece6a",
        warning="#e0af68",
        error="#f7768e",
        border="#414868",
        cursor_bg="#7aa2f7",
        cursor_fg="#1a1b26",
    ),
    "gruvbox": Theme(
        name="gruvbox",
        bg="#282828",
        bg2="#1d2021",
        bg3="#3c3836",
        accent="#fe8019",
        accent2="#b8bb26",
        text="#ebdbb2",
        text_dim="#928374",
        text_bright="#fbf1c7",
        success="#b8bb26",
        warning="#fabd2f",
        error="#fb4934",
        border="#504945",
        cursor_bg="#fe8019",
        cursor_fg="#282828",
    ),
    "nord": Theme(
        name="nord",
        bg="#2e3440",
        bg2="#242933",
        bg3="#3b4252",
        accent="#88c0d0",
        accent2="#81a1c1",
        text="#d8dee9",
        text_dim="#4c566a",
        text_bright="#eceff4",
        success="#a3be8c",
        warning="#ebcb8b",
        error="#bf616a",
        border="#434c5e",
        cursor_bg="#88c0d0",
        cursor_fg="#2e3440",
    ),
    "rose_pine": Theme(
        name="rose_pine",
        bg="#191724",
        bg2="#1f1d2e",
        bg3="#26233a",
        accent="#eb6f92",
        accent2="#c4a7e7",
        text="#e0def4",
        text_dim="#6e6a86",
        text_bright="#f7f7f8",
        success="#31748f",
        warning="#f6c177",
        error="#eb6f92",
        border="#393552",
        cursor_bg="#eb6f92",
        cursor_fg="#191724",
    ),
}

DEFAULT_THEME = "tokyo"


def get_theme(name: str | None = None) -> Theme:
    """Return theme by name, falling back to DEFAULT_THEME."""
    return THEMES.get(name or DEFAULT_THEME, THEMES[DEFAULT_THEME])


def load_active_theme() -> Theme:
    """Load theme from config, falling back to default."""
    try:
        from sarthak.core.config import load_config
        cfg = load_config()
        name = cfg.get("tui", {}).get("theme", DEFAULT_THEME)
        return get_theme(name)
    except Exception:
        return get_theme(DEFAULT_THEME)


def build_css(t: Theme) -> str:
    """Generate Textual CSS from a Theme object."""
    return f"""
/* ── Global ── */
Screen {{
    background: {t.bg};
    color: {t.text};
}}

/* ── Header / Footer ── */
Header {{
    background: {t.bg2};
    color: {t.text_bright};
    text-style: bold;
    border: none;
}}
Footer {{
    background: {t.bg2};
    color: {t.text_dim};
    border: none;
}}

/* ── Tabs ── */
Tabs {{
    background: {t.bg2};
    border: none;
}}
Tab {{
    color: {t.text_dim};
    padding: 0 2;
    border: none;
}}
Tab.-active {{
    background: {t.bg2};
    color: {t.text_bright};
    text-style: bold;
    border: none;
}}
Tab:hover {{
    color: {t.text};
    background: {t.bg3};
}}
TabbedContent > TabPane {{
    padding: 0 1;
    height: 1fr;
    background: {t.bg};
    border: none;
}}

/* ── DataTable ── */
DataTable {{
    background: {t.bg};
    color: {t.text};
    border: none;
}}
DataTable > .datatable--header {{
    background: {t.bg2};
    color: {t.text_bright};
    text-style: bold;
    border: none;
}}
DataTable > .datatable--cursor {{
    background: {t.bg3};
    color: {t.text_bright};
    border: none;
}}
DataTable > .datatable--hover {{
    background: {t.bg3};
    border: none;
}}

/* ── Inputs ── */
Input {{
    background: {t.bg2};
    color: {t.text};
    border: none;
}}
Input:focus {{
    background: {t.bg2};
    border: none;
}}
TextArea {{
    background: {t.bg2};
    color: {t.text};
    border: none;
}}
TextArea:focus {{
    background: {t.bg2};
    border: none;
}}

/* ── Buttons ── */
Button {{
    background: {t.bg3};
    color: {t.text};
    margin: 0 1;
    border: none;
}}
Button:hover {{
    background: {t.bg3};
    color: {t.text_bright};
    border: none;
}}
Button.-primary {{
    background: {t.bg3};
    color: {t.text_bright};
    text-style: bold;
    border: none;
}}
Button.-primary:hover {{
    background: {t.bg3};
    border: none;
}}

/* ── ListView ── */
ListView {{
    background: {t.bg};
    scrollbar-color: {t.bg3} {t.bg2};
    scrollbar-size: 1 1;
    border: none;
}}
ListItem {{
    background: {t.bg};
    color: {t.text};
    border: none;
}}
ListItem:hover {{
    background: {t.bg3};
    border: none;
}}
ListItem.-highlighted {{
    background: {t.bg2};
    border: none;
}}

/* ── ScrollableContainer ── */
ScrollableContainer {{
    scrollbar-color: {t.bg3} {t.bg2};
    scrollbar-size: 1 1;
    border: none;
}}

/* ── Select ── */
Select {{
    background: {t.bg2};
    color: {t.text};
    border: none;
}}
SelectOverlay {{
    background: {t.bg2};
    border: none;
}}
Select:focus {{
    background: {t.bg3};
    border: none;
}}

/* ── Markdown ── */
Markdown {{
    background: {t.bg};
    color: {t.text};
    border: none;
}}

/* ── Utility classes ── */
.title {{
    color: {t.text_bright};
    text-style: bold;
}}
.dim {{
    color: {t.text_dim};
}}
.success {{
    color: {t.success};
}}
.warning {{
    color: {t.warning};
}}
.error {{
    color: {t.error};
}}
.accent2 {{
    color: {t.accent2};
}}
.panel {{
    background: {t.bg2};
    padding: 1 2;
    border: none;
}}
.statusbar {{
    height: 1;
    background: {t.bg2};
    color: {t.text_dim};
    padding: 0 2;
    border: none;
}}
.header-bar {{
    height: 3;
    background: {t.bg2};
    padding: 0 2;
    align: left middle;
    border: none;
}}
"""
