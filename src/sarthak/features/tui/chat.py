"""
Sarthak AI — Chat Tab.
Multi-turn conversation with your activity data.
"""
from __future__ import annotations

import asyncio
import uuid
from datetime import datetime
from pathlib import Path

import pyperclip
import shutil
import subprocess
from rich.markdown import Markdown
from textual.app import ComposeResult
from textual.containers import Horizontal, ScrollableContainer, Vertical
from textual import events
from textual.widget import Widget
from textual.widgets import Button, Input, Label, RichLog, Select, Static

from sarthak.core.logging import get_logger
import tomlkit
from sarthak.features.channels import (
    stream_dispatch as _stream_dispatch,
    save_chat_turn as _save_chat_turn,
)

_WELCOME = """## Sarthak Chat

Ask about your activity, habits, and productivity:

- *"What was I working on this afternoon?"*
- *"What are my most-used terminal commands this week?"*
- *"Summarize my last hour"*

---
"""
log = get_logger(__name__)


class ChatTab(Widget):
    """Conversational interface over activity data."""

    DEFAULT_CSS = """
    ChatTab { height: 1fr; layout: vertical; }

    #chat-header {
        height: 3;
        background: $surface;
        padding: 0 2;
        align: left middle;
    }
    #chat-header Label { color: $text; text-style: bold; }
    #chat-hint { color: $text-muted; margin-left: 2; }
    #session-select { width: 44; min-width: 32; margin-left: 2; }
    #new-session { margin-left: 1; }

    #chat-scroll {
        height: 1fr;
        padding: 1 2;
        scrollbar-color: $surface $surface;
    }
    #chat-history { height: auto; width: 1fr; }

    #chat-footer {
        height: 3;
        background: $surface;
        padding: 0 1;
        layout: horizontal;
        align: left middle;
        border: none;
    }
    #chat-footer Button { height: 3; margin: 0; }
    #chat-footer Input  { height: 3; }
    #chat-input {
        width: 1fr;
        min-width: 12;
        margin-right: 1;
        height: 3;
        padding: 0 1;
        background: $surface;
        border: none;
    }
    #ask-btn   { width: 8; min-width: 8; }
    #clear-btn { width: 8; min-width: 8; }
    #chat-status { height: 3; color: $text-muted; margin-left: 1; }
    """

    BINDINGS = [
        ("c", "copy_chat", "Copy"),
        ("ctrl+l", "clear_chat", "Clear"),
    ]

    def compose(self) -> ComposeResult:
        with Horizontal(id="chat-header"):
            yield Label("Chat", classes="title")
            yield Label("  [c] copy  [ctrl+l] clear", id="chat-hint")
            yield Select([("Current session", "")], id="session-select", value="")
            yield Button("New Session", id="new-session")

        with ScrollableContainer(id="chat-scroll"):
            yield RichLog(id="chat-history", highlight=False, wrap=True)

        with Horizontal(id="chat-footer"):
            yield Input(
                placeholder="Ask anything about your activity...",
                id="chat-input",
            )
            yield Button("Ask", id="ask-btn", variant="primary")
            yield Button("Clear", id="clear-btn")
            yield Label("", id="chat-status")

    def on_mount(self) -> None:
        self._history_md: str = _WELCOME
        self._chat_session_id: str | None = None
        self._session_loading: bool = False
        self._session_options: list[tuple[str, str]] = []
        self._input_history: list[str] = []
        self._history_index: int | None = None
        self.query_one("#chat-input", Input).focus()
        asyncio.create_task(self._init_chat_session())

    async def _init_chat_session(self) -> None:
        from sarthak.storage.helpers import get_latest_chat_session_id, get_chat_sessions
        try:
            await self._refresh_session_list()
            session_id = await get_latest_chat_session_id()
            if not session_id:
                session_id = str(uuid.uuid4())
            await self._load_session(session_id)
        except Exception:
            self._history_md = _WELCOME
        await self._render_history()

    async def _refresh_session_list(self) -> None:
        from sarthak.storage.helpers import get_chat_sessions
        sessions = await get_chat_sessions(limit=20)
        self._session_options = [
            (self._format_session_label(s["session_id"], s.get("last_ts"), s.get("msg_count", 0)), s["session_id"])
            for s in sessions
        ]
        sel = self.query_one("#session-select", Select)
        self._session_loading = True
        if self._session_options:
            sel.set_options(self._session_options)
        else:
            sel.set_options([("Current session", "")])
        self._session_loading = False

    def _format_session_label(self, session_id: str, last_ts, msg_count: int) -> str:
        short = session_id.split("-")[0]
        if last_ts:
            try:
                dt = datetime.fromisoformat(str(last_ts).replace("Z", "+00:00"))
                ts = dt.astimezone().strftime("%b %d %H:%M")
                return f"{short} · {ts} · {msg_count} msg"
            except Exception:
                pass
        return f"{short} · {msg_count} msg" if msg_count else f"{short} · new"

    async def _start_new_session(self) -> None:
        self._chat_session_id = str(uuid.uuid4())
        self._history_md = _WELCOME
        await self._render_history()
        sel = self.query_one("#session-select", Select)
        label = self._format_session_label(self._chat_session_id, None, 0)
        self._session_options = [(label, self._chat_session_id)] + [
            opt for opt in self._session_options if opt[1] != self._chat_session_id
        ]
        self._session_loading = True
        sel.set_options(self._session_options)
        sel.value = self._chat_session_id
        self._session_loading = False

    async def _load_session(self, session_id: str) -> None:
        from sarthak.storage.helpers import get_chat_history
        self._chat_session_id = session_id
        try:
            history = await get_chat_history(session_id, limit=40)
            self._history_md = _WELCOME
            for item in history:
                ts_raw = item.get("ts", "")
                try:
                    ts = datetime.fromisoformat(str(ts_raw).replace("Z", "+00:00")).astimezone().strftime("%H:%M")
                except Exception:
                    ts = "??"
                role = item.get("role")
                content = item.get("content", "")
                if role == "user":
                    self._history_md += f"\n\n### You · {ts}\n{content}\n"
                elif role == "assistant":
                    self._history_md += f"\n### Sarthak · {ts}\n{content}\n\n---"
            sel = self.query_one("#session-select", Select)
            if session_id:
                self._session_loading = True
                sel.value = session_id
                self._session_loading = False
        except Exception:
            pass

    async def _render_history(self) -> None:
        rl = self.query_one("#chat-history", RichLog)
        rl.clear()
        rl.write(Markdown(self._history_md))

    def on_key(self, event: events.Key) -> None:
        inp = self.query_one("#chat-input", Input)
        if self.app.focused is not inp:
            return
        if event.key not in ("up", "down"):
            return
        if not self._input_history:
            return
        if self._history_index is None:
            self._history_index = len(self._input_history)
        if event.key == "up":
            self._history_index = max(0, self._history_index - 1)
        else:
            self._history_index = min(len(self._input_history), self._history_index + 1)
        if self._history_index >= len(self._input_history):
            inp.value = ""
        else:
            inp.value = self._input_history[self._history_index]
            try:
                inp.cursor_position = len(inp.value)
            except Exception:
                pass
        event.stop()

    def _copy_text(self, text: str) -> bool:
        try:
            pyperclip.copy(text)
            return True
        except Exception:
            pass
        if shutil.which("wl-copy"):
            try:
                subprocess.run(["wl-copy"], input=text.encode(), check=True)
                return True
            except Exception:
                pass
        if shutil.which("xclip"):
            try:
                subprocess.run(["xclip", "-selection", "clipboard"], input=text.encode(), check=True)
                return True
            except Exception:
                pass
        return False

    def _scroll_chat_end(self) -> None:
        scroll = self.query_one("#chat-scroll", ScrollableContainer)
        scroll.scroll_end(animate=False)

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "ask-btn":
            self._submit()
        elif event.button.id == "clear-btn":
            self.action_clear_chat()
        elif event.button.id == "new-session":
            asyncio.create_task(self._start_new_session())

    def on_select_changed(self, event: Select.Changed) -> None:
        if event.select.id == "session-select":
            if self._session_loading:
                return
            if event.value:
                asyncio.create_task(self._load_session(str(event.value)))

    def _submit(self) -> None:
        inp = self.query_one("#chat-input", Input)
        question = inp.value.strip()
        if not question:
            return
        if not self._input_history or self._input_history[-1] != question:
            self._input_history.append(question)
        self._history_index = None
        inp.value = ""
        asyncio.create_task(self._answer(question))

    def on_input_submitted(self, event: Input.Submitted) -> None:
        if event.input.id == "chat-input":
            self._submit()

    async def _answer(self, question: str) -> None:
        from sarthak.storage.helpers import write_alert
        status = self.query_one("#chat-status", Label)
        ts = datetime.now().strftime("%H:%M")
        status.update("Thinking...")

        self._history_md += f"\n\n### You · {ts}\n{question}\n"
        await self._render_history()
        self._scroll_chat_end()

        try:
            log.info("agent_prompt", agent="orchestrator", prompt=question, prompt_len=len(question))
            self._history_md += f"\n### Sarthak · {ts}\n"
            base = self._history_md
            answer = ""
            async for partial_reply in _stream_dispatch(
                question,
                cwd=str(Path.home()),
                session_id=self._chat_session_id,
            ):
                answer = partial_reply
                self._history_md = base + answer
                await self._render_history()
                self._scroll_chat_end()

            self._history_md = base + answer + "\n\n---"
            await self._render_history()
            self._scroll_chat_end()
            status.update(f"Last reply at {datetime.now().strftime('%H:%M:%S')}")

            if self._chat_session_id:
                await _save_chat_turn(self._chat_session_id, question, answer)

        except Exception as exc:
            self._history_md += f"\n**[Error]** {exc}\n\n---"
            await self._render_history()
            status.update(f"Error: {exc}")
            try:
                await write_alert(level="error", source="chat", message=str(exc))
            except Exception:
                pass

    def action_copy_chat(self) -> None:
        if self._copy_text(self._history_md):
            self.notify("Chat copied to clipboard!", timeout=2)
        else:
            self.notify("Copy failed: no clipboard backend.", timeout=3, severity="error")

    def action_clear_chat(self) -> None:
        self._history_md = _WELCOME
        asyncio.create_task(self._render_history())
        self.query_one("#chat-status", Label).update("")
        self.notify("Chat cleared.", timeout=2)
