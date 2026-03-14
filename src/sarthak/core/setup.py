"""
Sarthak AI — First-run bootstrap.

Runs automatically on the first invocation of any `sarthak` command after
a pip install. Creates ~/.sarthak_ai/ with all required files and shows
a small "Setting up Sarthak" animation in the terminal.

Public API
----------
  ensure_bootstrapped()   — call once at CLI entry point; no-op if already done
  bootstrap_first_run()   — force a full bootstrap (idempotent)
"""
from __future__ import annotations

import base64
import itertools
import os
import shutil
import sys
import threading
import time
from pathlib import Path

import tomlkit

# ── Paths ─────────────────────────────────────────────────────────────────────
BASE_DIR        = Path.home() / ".sarthak_ai"
CONFIG_FILE     = BASE_DIR / "config.toml"
MASTER_KEY_FILE = BASE_DIR / "master.key"
BOOTSTRAP_FLAG  = BASE_DIR / ".bootstrapped"   # sentinel: exists ⟹ already done

# ── Palette ───────────────────────────────────────────────────────────────────
OR = "\033[38;5;214m"
CY = "\033[38;5;87m"
GR = "\033[38;5;82m"
DM = "\033[38;5;240m"
BD = "\033[1m"
RS = "\033[0m"


# ── Spinner ───────────────────────────────────────────────────────────────────

class _Spinner:
    """Braille-dot spinner that animates while a task runs."""

    _FRAMES = ["⠋", "⠙", "⠹", "⠸", "⠼", "⠴", "⠦", "⠧", "⠇", "⠏"]

    def __init__(self, label: str) -> None:
        self._label   = label
        self._stop    = threading.Event()
        self._thread  = threading.Thread(target=self._spin, daemon=True)
        self._tty     = sys.stdout.isatty()

    def __enter__(self) -> "_Spinner":
        if self._tty:
            # Hide cursor
            sys.stdout.write("\033[?25l")
            sys.stdout.flush()
        self._thread.start()
        return self

    def __exit__(self, *_) -> None:
        self._stop.set()
        self._thread.join()
        if self._tty:
            # Clear the spinner line and restore cursor
            sys.stdout.write(f"\r\033[K\033[?25h")
            sys.stdout.flush()

    def _spin(self) -> None:
        for frame in itertools.cycle(self._FRAMES):
            if self._stop.is_set():
                break
            if self._tty:
                sys.stdout.write(
                    f"\r  {OR}{BD}{frame}{RS}  {CY}{self._label}{RS}  "
                    f"{DM}(first-time setup){RS}"
                )
                sys.stdout.flush()
            time.sleep(0.08)


def _step(msg: str) -> None:
    print(f"  {GR}+{RS} {msg}")


def _info(msg: str) -> None:
    print(f"  {CY}>{RS} {msg}")


# ── Template loader ───────────────────────────────────────────────────────────

def _template_config_text() -> str:
    """Return the bundled config.toml template text."""
    import importlib.resources
    # 1. Bundled in installed package (sarthak.data)
    try:
        ref = importlib.resources.files("sarthak.data").joinpath("config.toml")
        return ref.read_text(encoding="utf-8")
    except Exception:
        pass
    # 2. Dev-tree fallback: walk up from this file to find config.toml at repo root
    here = Path(__file__).resolve()
    for parent in here.parents:
        candidate = parent / "config.toml"
        if candidate.exists():
            return candidate.read_text(encoding="utf-8")
    raise FileNotFoundError("config.toml template not found in package data or repo root")


# ── Individual bootstrap steps ────────────────────────────────────────────────

def _create_dirs() -> None:
    """Create ~/.sarthak_ai/ and standard subdirectories."""
    for sub in ("", "logs", "cache", "whisper_models", "agents"):
        (BASE_DIR / sub).mkdir(parents=True, exist_ok=True)


def _write_config() -> None:
    """Write the default config.toml if it does not exist yet."""
    if CONFIG_FILE.exists():
        return
    CONFIG_FILE.write_text(_template_config_text(), encoding="utf-8")
    _step(f"config.toml  →  {CONFIG_FILE}")


def _write_master_key() -> None:
    """Generate and store the master encryption key."""
    if MASTER_KEY_FILE.exists():
        return
    key = base64.b64encode(os.urandom(32)).decode()
    MASTER_KEY_FILE.write_text(key + "\n", encoding="utf-8")
    try:
        os.chmod(MASTER_KEY_FILE, 0o600)
    except Exception:
        pass
    _step(f"master.key   →  {MASTER_KEY_FILE}")


def _mark_done() -> None:
    BOOTSTRAP_FLAG.write_text("1")


# ── Public API ────────────────────────────────────────────────────────────────

def bootstrap_first_run(*, silent: bool = False) -> None:
    """
    Create ~/.sarthak_ai/ with all required files.

    Shows a spinner + per-step messages unless *silent* is True.
    Safe to call multiple times — each step is idempotent.
    """
    label = "Setting up Sarthak AI"

    if not silent:
        print(f"\n{OR}{BD}  Sarthak AI — First Run Setup{RS}")
        print(f"  {DM}Creating {BASE_DIR}{RS}\n")

    steps = [
        ("Creating directories …",   _create_dirs),
        ("Writing config.toml …",    _write_config),
        ("Generating master key …",  _write_master_key),
        ("Finalising …",             _mark_done),
    ]

    for step_label, fn in steps:
        if not silent:
            with _Spinner(step_label):
                fn()
        else:
            fn()

    if not silent:
        print(f"\n  {GR}✓{RS}  Setup complete.")
        print(f"  {CY}>{RS}  Run {OR}{BD}sarthak configure{RS} to choose your AI provider.\n")


def ensure_bootstrapped() -> None:
    """
    Run bootstrap_first_run() exactly once — on the first `sarthak` invocation.

    Subsequent calls are instant (sentinel file exists).
    Also triggers if config.toml is missing even after the flag exists,
    which handles the case where the user deleted their config manually.
    """
    if BOOTSTRAP_FLAG.exists() and CONFIG_FILE.exists():
        return
    bootstrap_first_run()
