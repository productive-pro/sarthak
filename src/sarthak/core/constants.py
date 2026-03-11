"""
Sarthak AI — Central constants.
All hardcoded values live here. Override via config.toml where possible.
"""
from __future__ import annotations

import sys

# ── AI / LLM ──────────────────────────────────────────────────────────────────
DEFAULT_PROVIDER: str = "ollama"
DEFAULT_MODEL: str    = "gemma3:4b"

DAILY_SUMMARY_CONTEXT_LIMIT: int = 3000
DAILY_SUMMARY_PREV_LIMIT: int    = 800
CLASSIFY_MAX_EVENTS: int         = 10

AGENT_RETRIES: int        = 3
AGENT_OUTPUT_RETRIES: int = 3

# ── Orchestration ─────────────────────────────────────────────────────────────
RULE_BASED_TIPS_LIMIT: int    = 3
RULE_BASED_ACTIVITY_DAYS: int = 1
RULE_BASED_TREND_DAYS: int    = 14

# ── Shell tool ────────────────────────────────────────────────────────────────
SHELL_TIMEOUT_SECONDS: int  = 15
SHELL_OUTPUT_MAX_CHARS: int = 1500

SAFE_SHELL_PREFIXES: frozenset[str] = frozenset({
    "git", "ls", "cat", "which", "echo", "pwd", "uname",
    "python", "uv", "node", "npm", "cargo", "go",
    "systemctl", "journalctl", "ps", "df", "du", "free",
    "top", "htop", "ping", "curl", "wget", "env", "printenv",
    # Windows equivalents
    "dir", "type", "where", "Get-", "Set-",
})

SHELL_BLOCK_PATTERNS: tuple[str, ...] = (
    "rm ", "sudo ", "dd ", ">", ">>", "| rm", "mkfs", "chmod", "chown",
    # Windows destructive equivalents
    "Remove-Item", "del ", "format ", "rd /s",
)

# ── Web search ────────────────────────────────────────────────────────────────
WEB_SEARCH_TIMEOUT: int       = 10
WEB_SEARCH_RELATED_LIMIT: int = 4
WEB_SEARCH_URL: str           = "https://api.duckduckgo.com/"

# ── Activity query ────────────────────────────────────────────────────────────
ACTIVITY_EVENT_TYPES: list[str] = [
    "window.focus", "terminal.command",
]
ACTIVITY_MAX_DAYS: int  = 30
ACTIVITY_HEAD_TAIL: int = 5

# ── Channels ──────────────────────────────────────────────────────────────────
TELEGRAM_MESSAGE_LIMIT: int = 4096
WHATSAPP_MESSAGE_LIMIT: int = 4096   # Meta Cloud API plain-text body limit

# ── Chat / TUI ────────────────────────────────────────────────────────────────
CHAT_MAX_HISTORY_PAIRS: int   = 20
CHAT_HISTORY_LIMIT: int       = 40
CHAT_SESSION_LIST_LIMIT: int  = 20
CHAT_DEFAULT_SPLIT_RATIO: float = 0.7
CHAT_DATA_PREVIEW_ROWS: int   = 10

# ── Sensitive key fragments (log redaction) ───────────────────────────────────
SENSITIVE_KEY_FRAGMENTS: tuple[str, ...] = (
    "token", "secret", "password", "api_key", "bot_token", "key",
)

# ── Services — platform-aware ─────────────────────────────────────────────────
# Names used to identify background services on each platform.
if sys.platform.startswith("linux"):
    SYSTEMD_SERVICES: tuple[str, ...] = ("sarthak-orchestrator",)
    ALLOWED_RESTART_SERVICES: frozenset[str] = frozenset(SYSTEMD_SERVICES)
elif sys.platform == "darwin":
    SYSTEMD_SERVICES = ()                        # macOS uses launchd, not systemd
    ALLOWED_RESTART_SERVICES = frozenset()
elif sys.platform == "win32":
    SYSTEMD_SERVICES = ()
    ALLOWED_RESTART_SERVICES = frozenset()
else:
    SYSTEMD_SERVICES = ()
    ALLOWED_RESTART_SERVICES = frozenset()

SERVICE_CHECK_TIMEOUT: int   = 5
SERVICE_RESTART_TIMEOUT: int = 10
