"""
GitHub Copilot authentication — device-flow OAuth + token exchange + refresh.

Flow (mirrors OpenClaw's github-copilot provider strategy):
  1. Device-flow: POST https://github.com/login/device/code  → device_code + user_code + verification_uri
  2. Poll: POST https://github.com/login/oauth/access_token  → github_token (ghu_...)
  3. Exchange: GET https://api.github.com/copilot_internal/v2/token  → copilot_token (exp ~30 min)
  4. Refresh: re-exchange before expiry; token stored in ~/.sarthak_ai/copilot_token.json

The Copilot API endpoint speaks OpenAI /v1/chat/completions (openai-compat).
Required header: Copilot-Integration-Id: vscode-chat
"""
from __future__ import annotations

import asyncio
import json
import time
from pathlib import Path
from typing import Any

import httpx

from sarthak.core.logging import get_logger

log = get_logger(__name__)

# ── GitHub OAuth app ID used by VS Code / Copilot CLI ─────────────────────────
_CLIENT_ID = "Iv1.b507a08c87ecfe98"
_SCOPES    = "read:user"
_DEVICE_URL   = "https://github.com/login/device/code"
_POLL_URL     = "https://github.com/login/oauth/access_token"
_EXCHANGE_URL = "https://api.github.com/copilot_internal/v2/token"
_TOKEN_PATH   = Path.home() / ".sarthak_ai" / "copilot_token.json"
_REFRESH_BUFFER_SECONDS = 300   # refresh 5 min before expiry


# ── Persistent token store ────────────────────────────────────────────────────

def _save_token(data: dict[str, Any]) -> None:
    _TOKEN_PATH.parent.mkdir(parents=True, exist_ok=True)
    _TOKEN_PATH.write_text(json.dumps(data, indent=2), encoding="utf-8")


def _load_token() -> dict[str, Any] | None:
    try:
        return json.loads(_TOKEN_PATH.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError):
        return None


# ── Device-flow login (interactive, sync — called from CLI only) ──────────────

def login_device_flow() -> str:
    """
    Run GitHub device-flow OAuth interactively. Prints instructions to stdout.
    Returns the GitHub user token (ghu_...) and saves it to _TOKEN_PATH.
    """
    with httpx.Client(timeout=30) as c:
        r = c.post(
            _DEVICE_URL,
            data={"client_id": _CLIENT_ID, "scope": _SCOPES},
            headers={"Accept": "application/json"},
        )
        r.raise_for_status()
        data = r.json()

    device_code      = data["device_code"]
    user_code        = data["user_code"]
    verification_uri = data["verification_uri"]
    interval         = int(data.get("interval", 5))
    expires_in       = int(data.get("expires_in", 900))

    print(f"\nVisit: {verification_uri}")
    print(f"Code:  {user_code}\n")
    print("Waiting for authorization...", flush=True)

    deadline = time.monotonic() + expires_in
    with httpx.Client(timeout=30) as c:
        while time.monotonic() < deadline:
            time.sleep(interval)
            r = c.post(
                _POLL_URL,
                data={
                    "client_id": _CLIENT_ID,
                    "device_code": device_code,
                    "grant_type": "urn:ietf:params:oauth:grant-type:device_code",
                },
                headers={"Accept": "application/json"},
            )
            body = r.json()
            if "access_token" in body:
                github_token = body["access_token"]
                _save_token({"github_token": github_token, "copilot_token": "", "expires_at": 0})
                log.info("copilot_github_token_acquired")
                return github_token
            err = body.get("error", "")
            if err == "authorization_pending":
                continue
            if err == "slow_down":
                interval += 5
                continue
            raise RuntimeError(f"Device flow error: {err} — {body.get('error_description', '')}")

    raise RuntimeError("Device flow timed out — code expired.")


# ── Token exchange (async) ────────────────────────────────────────────────────

async def _exchange_github_token(github_token: str) -> dict[str, Any]:
    """Exchange a GitHub user token for a short-lived Copilot API token."""
    async with httpx.AsyncClient(timeout=15) as c:
        r = await c.get(
            _EXCHANGE_URL,
            headers={
                "Authorization": f"token {github_token}",
                "Accept": "application/json",
                "Editor-Version": "vscode/1.99.0",
                "Copilot-Integration-Id": "vscode-chat",
            },
        )
        if r.status_code != 200:
            raise RuntimeError(f"Copilot token exchange failed: HTTP {r.status_code}")
        return r.json()


# ── Token manager (singleton, async-safe) ─────────────────────────────────────

class _CopilotTokenManager:
    """Holds the active Copilot API token and refreshes it before expiry."""

    def __init__(self) -> None:
        self._lock = asyncio.Lock()
        self._copilot_token: str = ""
        self._expires_at: float = 0.0
        self._github_token: str = ""
        self._refresh_task: asyncio.Task | None = None

    def _load_from_disk(self) -> None:
        data = _load_token()
        if data:
            self._github_token  = data.get("github_token", "")
            self._copilot_token = data.get("copilot_token", "")
            self._expires_at    = float(data.get("expires_at", 0))

    async def get_token(self) -> str:
        """Return a valid Copilot API token, refreshing if needed."""
        async with self._lock:
            if not self._github_token:
                self._load_from_disk()
            if not self._github_token:
                raise RuntimeError(
                    "GitHub Copilot not authenticated. Run: sarthak copilot login"
                )
            if time.time() >= self._expires_at - _REFRESH_BUFFER_SECONDS:
                await self._refresh()
            return self._copilot_token

    async def _refresh(self) -> None:
        data = await _exchange_github_token(self._github_token)
        self._copilot_token = data.get("token", "")
        # expires_at is a Unix timestamp in the response
        self._expires_at = float(data.get("expires_at", time.time() + 1800))
        stored = _load_token() or {}
        stored.update({
            "copilot_token": self._copilot_token,
            "expires_at": self._expires_at,
        })
        _save_token(stored)
        log.debug("copilot_token_refreshed", expires_at=self._expires_at)


_manager = _CopilotTokenManager()


async def get_copilot_token() -> str:
    """Public async entry point — returns a live Copilot API token."""
    return await _manager.get_token()


def get_copilot_token_sync() -> str:
    """Sync wrapper for use in synchronous builder context."""
    try:
        loop = asyncio.get_running_loop()
        if loop.is_running():
            # Inside an async context — schedule and block via a future.
            # This shouldn't normally be called from a running loop; prefer get_copilot_token().
            import concurrent.futures
            with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
                return pool.submit(asyncio.run, get_copilot_token()).result()
    except RuntimeError:
        return asyncio.run(get_copilot_token())
    # No running loop but event loop available — run to completion.
    return asyncio.run(get_copilot_token())


def is_configured() -> bool:
    """Return True if a GitHub token has been saved on disk."""
    data = _load_token()
    return bool(data and data.get("github_token"))
