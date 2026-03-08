"""
Sarthak Spaces — Session Tracker & System-Space Bridge

Tracks one focused learning session:
  - Active time (only when space-relevant apps are focused, not idle)
  - Idle time (via xprintidle / ioreg / ctypes)
  - File edits (mtime scan on space directory)
  - Git stats (commits + lines written since session start)
  - Outcome self-report (3 questions at end)

System-level bridge:
  idle detection via xprintidle (Linux), ioreg (macOS), ctypes (Windows).

This replaces random screenshots and raw context-switch dumps as the
data source for daily summaries and space optimization.
"""
from __future__ import annotations

import asyncio
import subprocess
import sys
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path

import structlog

from sarthak.spaces.models import SelfReport, SessionSignals, SpaceSession

log = structlog.get_logger(__name__)

# ── Space-relevant app names (cross-platform) ─────────────────────────────────
# Only count active time when one of these apps is focused.
DEFAULT_SPACE_APPS: frozenset[str] = frozenset({
    # Editors
    "code", "cursor", "zed", "vim", "nvim", "emacs", "sublime_text",
    "gedit", "kate", "atom", "brackets",
    # Terminals
    "kitty", "alacritty", "wezterm", "gnome-terminal", "konsole",
    "Terminal", "iTerm2", "WindowsTerminal", "cmd", "powershell",
    # Browsers (docs / research)
    "firefox", "chromium", "google-chrome", "chrome", "brave", "safari",
    # Notebooks / REPL
    "jupyter", "marimo", "jupyter-lab",
    # IDE / domain tools
    "rstudio", "spyder", "pycharm", "intellij", "clion", "goland",
    # macOS bundle IDs
    "com.microsoft.VSCode", "com.apple.Terminal", "com.googlecode.iterm2",
    "org.mozilla.firefox",
})


# ── Idle detection ────────────────────────────────────────────────────────────

def _idle_seconds() -> float:
    """Return seconds since last user input. Best-effort, never raises."""
    try:
        if sys.platform.startswith("linux"):
            out = subprocess.check_output(["xprintidle"], timeout=1)
            return int(out.strip()) / 1000.0
    except Exception:
        pass
    try:
        if sys.platform == "darwin":
            out = subprocess.check_output(["ioreg", "-c", "IOHIDSystem"], timeout=2, text=True)
            for line in out.splitlines():
                if "HIDIdleTime" in line:
                    ns = int(line.split("=")[-1].strip())
                    return ns / 1_000_000_000.0
    except Exception:
        pass
    try:
        if sys.platform == "win32":
            import ctypes
            class _LASTINPUT(ctypes.Structure):
                _fields_ = [("cbSize", ctypes.c_uint), ("dwTime", ctypes.c_uint)]
            li = _LASTINPUT()
            li.cbSize = ctypes.sizeof(_LASTINPUT)
            ctypes.windll.user32.GetLastInputInfo(ctypes.byref(li))
            return (ctypes.windll.kernel32.GetTickCount() - li.dwTime) / 1000.0
    except Exception:
        pass
    return 0.0


# ── Git stats ─────────────────────────────────────────────────────────────────

def _git_stats_since(directory: Path, since_ts: float) -> dict[str, int]:
    since_iso = datetime.fromtimestamp(since_ts, tz=timezone.utc).strftime("%Y-%m-%dT%H:%M:%S")
    try:
        r1 = subprocess.run(
            ["git", "rev-list", "--count", f"--since={since_iso}", "HEAD"],
            cwd=str(directory), capture_output=True, text=True, timeout=5,
        )
        commits = int(r1.stdout.strip()) if r1.returncode == 0 else 0

        r2 = subprocess.run(
            ["git", "log", f"--since={since_iso}", "--numstat", "--format="],
            cwd=str(directory), capture_output=True, text=True, timeout=5,
        )
        lines_added = 0
        if r2.returncode == 0:
            for line in r2.stdout.splitlines():
                parts = line.split("\t")
                if len(parts) >= 2:
                    try:
                        lines_added += int(parts[0])
                    except ValueError:
                        pass
        return {"commits": commits, "lines_added": lines_added}
    except Exception:
        return {"commits": 0, "lines_added": 0}


def _file_edits_since(directory: Path, since_ts: float) -> tuple[list[str], int]:
    """Scan for files modified since since_ts. Returns (paths, total_lines_in_edited_files)."""
    text_exts = {".py", ".md", ".txt", ".rst", ".r", ".ts", ".js",
                 ".sql", ".yaml", ".yml", ".toml", ".json", ".ipynb"}
    edited: list[str] = []
    total_lines = 0
    for p in directory.rglob("*"):
        if not p.is_file() or p.suffix not in text_exts:
            continue
        if any(part.startswith(".") for part in p.relative_to(directory).parts):
            continue
        try:
            st = p.stat()
        except OSError:
            continue
        if st.st_mtime >= since_ts:
            edited.append(str(p.relative_to(directory)))
            try:
                total_lines += p.read_bytes().count(b"\n")
            except OSError:
                pass
    return edited[:30], total_lines


# ── Active window ─────────────────────────────────────────────────────────────

async def _current_app_name() -> str:
    """Best-effort active app name using system-level introspection."""
    try:
        if sys.platform.startswith("linux"):
            out = subprocess.check_output(
                ["xdotool", "getactivewindow", "getwindowname"], timeout=1, text=True
            )
            return out.strip().lower()
    except Exception:
        pass
    return ""


# ── Depth score ───────────────────────────────────────────────────────────────

def _depth_score(
    lines_written: int,
    commits: int,
    rating: int,        # 1–5
    focus_ratio: float,
) -> float:
    code  = min(1.0, lines_written * 0.005 + commits * 0.1)
    rate  = (rating - 1) / 4.0
    return round(0.40 * rate + 0.30 * focus_ratio + 0.30 * code, 3)


# ── SpaceSessionTracker ───────────────────────────────────────────────────────

class SpaceSessionTracker:
    """
    Tracks one learning session from start() → end(self_report).

    Background asyncio task polls every POLL_INTERVAL seconds:
      - If in space app and not idle → accrue active_sec
      - Else → accrue idle_sec

    Usage:
        tracker = SpaceSessionTracker(space_dir, concept="Linear Algebra")
        await tracker.start()
        # … learner works …
        session = await tracker.end(SelfReport(task_completed=True, understanding_rating=4))
    """

    POLL_INTERVAL  = 10.0   # seconds between polls
    IDLE_THRESHOLD = 300.0  # 5 min idle → don't count as active

    def __init__(
        self,
        space_dir: Path,
        concept: str,
        task_id: str = "",
        planned_minutes: int = 30,
        space_apps: frozenset[str] | None = None,
    ) -> None:
        self.space_dir       = space_dir
        self.concept         = concept
        self.task_id         = task_id
        self.planned_minutes = planned_minutes
        self.space_apps      = space_apps or DEFAULT_SPACE_APPS

        self._session_id  = str(uuid.uuid4())[:12]
        self._started_ts  = time.time()
        self._started_at  = datetime.now(timezone.utc)
        self._active_sec  = 0.0
        self._idle_sec    = 0.0
        self._stop        = asyncio.Event()
        self._task: asyncio.Task | None = None

    async def start(self) -> None:
        log.info("session_started", id=self._session_id, concept=self.concept)
        self._task = asyncio.create_task(self._poll())

    async def end(self, report: SelfReport | None = None) -> SpaceSession:
        self._stop.set()
        if self._task:
            await asyncio.gather(self._task, return_exceptions=True)

        elapsed = time.time() - self._started_ts
        git     = _git_stats_since(self.space_dir, self._started_ts)
        files, lines = _file_edits_since(self.space_dir, self._started_ts)

        focus   = self._active_sec / elapsed if elapsed > 0 else 0.0
        rating  = report.understanding_rating if report else 3
        depth   = _depth_score(git["lines_added"] or lines, git["commits"], rating, focus)

        signals = SessionSignals(
            active_seconds=int(self._active_sec),
            idle_seconds=int(self._idle_sec),
            files_edited=files,
            lines_written=git["lines_added"] or lines,
            git_commits=git["commits"],
            focus_ratio=round(focus, 3),
            depth_score=depth,
        )
        session = SpaceSession(
            session_id=self._session_id,
            space_dir=str(self.space_dir),
            concept=self.concept,
            task_id=self.task_id,
            started_at=self._started_at,
            ended_at=datetime.now(timezone.utc),
            planned_minutes=self.planned_minutes,
            signals=signals,
            self_report=report or SelfReport(),
        )
        log.info("session_ended",
                 id=self._session_id,
                 active_min=round(self._active_sec / 60, 1),
                 depth=depth)
        return session

    async def _poll(self) -> None:
        while not self._stop.is_set():
            try:
                idle  = _idle_seconds()
                app   = await _current_app_name()
                in_space = any(s in app for s in self.space_apps)

                if idle >= self.IDLE_THRESHOLD:
                    self._idle_sec += self.POLL_INTERVAL
                elif in_space or not app:
                    self._active_sec += self.POLL_INTERVAL
                else:
                    self._idle_sec += self.POLL_INTERVAL
            except Exception as exc:
                log.debug("session_poll_error", error=str(exc))
            try:
                await asyncio.wait_for(self._stop.wait(), timeout=self.POLL_INTERVAL)
            except asyncio.TimeoutError:
                pass


# ── Session persistence ───────────────────────────────────────────────────────

def save_session(space_dir: Path, session: SpaceSession) -> None:
    out = space_dir / ".spaces" / "sessions.jsonl"
    out.parent.mkdir(parents=True, exist_ok=True)
    with out.open("a", encoding="utf-8") as f:
        f.write(session.model_dump_json() + "\n")


def load_sessions(space_dir: Path, limit: int = 50) -> list[SpaceSession]:
    path = space_dir / ".spaces" / "sessions.jsonl"
    if not path.exists():
        return []
    lines = path.read_text(encoding="utf-8").splitlines()
    sessions: list[SpaceSession] = []
    for line in lines[-limit:]:
        try:
            sessions.append(SpaceSession.model_validate_json(line))
        except Exception:
            pass
    return sessions

