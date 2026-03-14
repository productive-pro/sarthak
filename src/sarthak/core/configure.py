
"""
Sarthak AI — Interactive configuration wizard.
Minimal glyph-only UI with orange/cyan palette. Dot/circle selectors.
Preserves existing model settings on update. Includes health checks.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

import click
import questionary
import tomlkit
import httpx
from questionary import Style

BASE_DIR = Path.home() / ".sarthak_ai"
MASTER_KEY_FILE = BASE_DIR / "master.key"

# ── Palette (ANSI for click.echo) ─────────────────────────────────────────────
OR = "\033[38;5;214m"   # orange
CY = "\033[38;5;87m"    # cyan
GR = "\033[38;5;82m"    # green
YL = "\033[38;5;227m"   # yellow
RD = "\033[38;5;196m"   # red
DM = "\033[38;5;240m"   # dim grey
BD = "\033[1m"
RS = "\033[0m"


def hdr(text: str) -> None:
    click.echo(f"\n{OR}{BD}:: {text}{RS}")

def ok(text: str) -> None:
    click.echo(f"  {GR}+{RS} {text}")

def info(text: str) -> None:
    click.echo(f"  {CY}>{RS} {text}")

def warn(text: str) -> None:
    click.echo(f"  {YL}!{RS} {text}")

def err(text: str) -> None:
    click.echo(f"  {RD}x{RS} {text}")

def dim(text: str) -> None:
    click.echo(f"  {DM}{text}{RS}")


# ── Questionary style: dot/circle selectors, orange/cyan ─────────────────────
_STYLE = Style([
    ("qmark",       "fg:#ff8c00 bold"),
    ("question",    "bold"),
    ("answer",      "fg:#00d7ff bold"),
    ("pointer",     "fg:#ff8c00 bold"),
    ("highlighted", "fg:#00d7ff bold"),
    ("selected",    "fg:#5fdf5f"),
    ("separator",   "fg:#606060"),
    ("instruction", "fg:#606060 italic"),
    ("text",        ""),
    ("disabled",    "fg:#606060 italic"),
    ("completion-menu", "bg:#1b1f2a fg:#cdd6f4"),
    ("completion-menu.completion", "bg:#1b1f2a fg:#cdd6f4"),
    ("completion-menu.completion.current", "bg:#2b3245 fg:#a6e22e bold"),
    ("scrollbar.background", "bg:#1b1f2a"),
    ("scrollbar.button", "bg:#2b3245"),
])

_POINTER = "│"
_QMARK = ""

def q_select(message: str, **kwargs):
    kwargs.setdefault("qmark", _QMARK)
    kwargs.setdefault("pointer", _POINTER)
    kwargs.setdefault("instruction", " ")
    return questionary.select(message, **kwargs)

def q_text(message: str, **kwargs):
    kwargs.setdefault("qmark", _QMARK)
    return questionary.text(message, **kwargs)

def q_autocomplete(message: str, **kwargs):
    kwargs.setdefault("qmark", _QMARK)
    if kwargs.get("default") is None:
        kwargs["default"] = ""
    return questionary.autocomplete(message, **kwargs)

def q_confirm(message: str, **kwargs):
    kwargs.setdefault("qmark", _QMARK)
    return questionary.confirm(message, **kwargs)

def q_press(message: str, **kwargs):
    # press_any_key_to_continue does not accept qmark in some questionary versions
    kwargs.pop("qmark", None)
    return questionary.press_any_key_to_continue(message, **kwargs)

def q_secret(message: str, **kwargs):
    """Password-masked input — characters are hidden as they are typed."""
    kwargs.setdefault("qmark", _QMARK)
    return questionary.password(message, **kwargs)



# ── Provider catalog ──────────────────────────────────────────────────────────
from sarthak.core.ai_utils.catalog import ModelEntry, list_models, load_catalog
from sarthak.core.ai_utils.provider_registry import canonical_provider, list_models_sync, provider_entry


# Tracks whether the "Other providers" section is expanded in the current selection session.
_other_providers_expanded: bool = False


def _provider_choices(show_others: bool = False) -> list[questionary.Choice]:
    choices: list[questionary.Choice] = []
    catalog = load_catalog()
    top = [
        "openai",
        "anthropic",
        "gemini",
        "groq",
        "openrouter",
        "ollama",
        "github-copilot",
        "custom",
    ]
    # Keys to suppress from the "Other" list (aliases / redundant duplicates)
    suppress = set(top)

    seen: set[str] = set()
    for key in top:
        if key == "custom":
            choices.append(questionary.Choice(f"  {'custom':<16} — Custom (OpenAI / Anthropic compat)", value="custom"))
            seen.add(key)
            continue
        entry = catalog.get(key)
        if not entry:
            continue
        meta = entry["meta"]
        label = str(meta.get("label", key))
        choices.append(questionary.Choice(f"  {key:<16} — {label}", value=key))
        seen.add(key)

    others = []
    for key in sorted(catalog.keys()):
        if key in seen or key in suppress:
            continue
        meta = catalog[key]["meta"]
        label = str(meta.get("label", key))
        others.append(questionary.Choice(f"  {key:<16} — {label}", value=key))

    if others:
        if show_others:
            choices.append(questionary.Separator("── Other providers ──"))
            choices.extend(others)
            choices.append(questionary.Choice("  ▲ Hide other providers", value="__hide_others__"))
        else:
            choices.append(questionary.Choice("  ▼ Show other providers…", value="__show_others__"))

    return choices


def _provider_defaults(provider: str) -> tuple[str, str]:
    entries = list_models(canonical_provider(provider))
    text = [m for m in entries if "text" in m.capabilities]
    default = text[0].id if text else (entries[0].id if entries else "")
    vision = next((m.id for m in entries if "vision" in m.capabilities), "")
    return default, vision or default


def _model_meta_map(provider: str) -> dict[str, ModelEntry]:
    entries = list_models(canonical_provider(provider))
    return {m.id: m for m in entries if m.id}


def _filter_model_ids(model_ids: list[str], meta_map: dict[str, ModelEntry], capability: str) -> list[str]:
    filtered: list[str] = []
    for mid in model_ids:
        if not mid:
            continue
        meta = meta_map.get(mid)
        if not meta:
            filtered.append(mid)
            continue
        if capability in meta.capabilities:
            filtered.append(mid)
    return filtered


def _model_label(model_id: str, meta: ModelEntry) -> str:
    caps = ",".join(meta.capabilities) if meta.capabilities else "unknown"
    details: list[str] = []
    if meta.context_window:
        details.append(f"ctx={meta.context_window}")
    if meta.tier and meta.tier != "unknown":
        details.append(meta.tier)
    if meta.speed and meta.speed != "unknown":
        details.append(meta.speed)
    suffix = f"  {' '.join(details)}" if details else ""
    return f"{model_id}  [{caps}]{suffix}"




def _filter_openrouter_available(models: list) -> list:
    return models


def _decrypt_if_needed(value: str) -> str:
    if value.startswith("ENC:"):
        from sarthak.storage.encrypt import decrypt_string
        return decrypt_string(value)
    return value


def _resolve_api_key_from_data(toml_data: dict, secrets_data: dict, provider: str) -> str:
    canon = canonical_provider(provider)
    key_path = ["ai", canon, "api_key"]
    key = _get_secret(toml_data, key_path)
    if key:
        return key
    entry = provider_entry(canon)
    if entry.env_key:
        env_val = os.getenv(entry.env_key, "").strip()
        if env_val:
            return env_val
    return ""


def _fetch_models(provider_key: str, toml_data: dict, secrets_data: dict, vision_only: bool = False) -> list[str]:
    if provider_key == "custom":
        # For custom providers: try to fetch live model list from the configured endpoint.
        # Fall back to [current model] so the user can at least confirm what they typed.
        from sarthak.core.ai_utils.provider_registry import _fetch_openai_compat_models
        base_url = _gv(toml_data, ["ai", "custom", "base_url"], "")
        api_key  = _resolve_api_key_from_data(toml_data, secrets_data, "custom")
        cur_model = _gv(toml_data, ["ai", "custom", "model"], "")
        if base_url:
            try:
                fetched = _fetch_openai_compat_models(base_url, api_key)
                if fetched:
                    return fetched
            except Exception:
                pass
        return [m for m in [cur_model] if m]
    api_key = _resolve_api_key_from_data(toml_data, secrets_data, provider_key)
    base_url = _gv(toml_data, ["ai", provider_key, "base_url"], "")
    models = list_models_sync(provider_key, api_key=api_key, base_url=base_url)
    if provider_key == "openrouter":
        models = _filter_openrouter_available(models)
    meta_map = _model_meta_map(provider_key)
    if vision_only:
        return _filter_model_ids(models, meta_map, "vision")
    return _filter_model_ids(models, meta_map, "text")


# ── Health check helpers ──────────────────────────────────────────────────────

def _setup_github_copilot() -> bool:
    """Run device-flow OAuth for GitHub Copilot inline in the configure wizard.
    Returns True if authentication succeeded.
    """
    from sarthak.core.ai_utils.github_copilot_auth import (
        is_configured, login_device_flow, _manager,
    )
    import asyncio

    if is_configured():
        import time
        from sarthak.core.ai_utils.github_copilot_auth import _load_token
        data = _load_token() or {}
        expires_at = float(data.get("expires_at", 0))
        remaining = int(expires_at - time.time()) if expires_at else 0
        status = f"expires in {remaining // 60}m" if remaining > 0 else "token will refresh on use"
        ok(f"Already authenticated ({status})")
        reauthenticate = q_confirm("Re-authenticate?", default=False, style=_STYLE).ask()
        if not reauthenticate:
            return True

    hdr("GitHub Copilot — Device Login")
    info("A browser page will open. Enter the code shown below to authorize.")
    info("Requires a GitHub account with an active Copilot subscription.")
    click.echo("")

    try:
        github_token = login_device_flow()
    except Exception as e:
        err(f"Device flow failed: {e}")
        return False

    info("Exchanging GitHub token for Copilot API token...")
    try:
        async def _exchange():
            _manager._github_token = github_token
            await _manager._refresh()

        asyncio.run(_exchange())
        ok("GitHub Copilot authenticated.")
        return True
    except Exception as e:
        err(f"Token exchange failed: {e}")
        return False


def _configure_custom_provider(toml_data: dict, secrets_data: dict) -> tuple[bool, bool]:
    """Configure a custom OpenAI/Anthropic-compatible provider.
    Returns (toml_changed, secrets_changed).
    """
    toml_changed = False
    secrets_changed = False

    hdr("Custom provider")
    dim("Use any OpenAI-compatible or Anthropic-compatible endpoint.")

    # ── Compat type ──────────────────────────────────────────────────────────
    cur_compat = _gv(toml_data, ["ai", "custom", "compat"], "openai")
    compat = q_select(
        "API compatibility",
        choices=[
            questionary.Choice("  openai    — OpenAI-compatible  (/v1/chat/completions)", value="openai"),
            questionary.Choice("  anthropic — Anthropic-compatible (/v1/messages)",       value="anthropic"),
        ],
        default=cur_compat if cur_compat in ("openai", "anthropic") else "openai",
        style=_STYLE,
        pointer=_POINTER,
    ).ask()
    if compat is None:
        return toml_changed, secrets_changed
    if compat != cur_compat:
        _sv(toml_data, ["ai", "custom", "compat"], compat)
        toml_changed = True

    # ── Base URL ─────────────────────────────────────────────────────────────
    cur_base = _gv(toml_data, ["ai", "custom", "base_url"], "")
    placeholder = "https://my-llm.example.com/v1" if compat == "openai" else "https://my-llm.example.com"
    dim(f"e.g. {placeholder}")
    base_url = q_text("Base URL", default=cur_base, style=_STYLE).ask()
    if base_url and base_url != cur_base:
        _sv(toml_data, ["ai", "custom", "base_url"], base_url.rstrip("/"))
        toml_changed = True

    # ── Model name ───────────────────────────────────────────────────────────
    cur_model = _gv(toml_data, ["ai", "custom", "model"], "")
    dim("Exact model ID served by the endpoint  e.g. mistral-7b-instruct")
    model = q_text("Model name", default=cur_model, style=_STYLE).ask()
    if model and model != cur_model:
        _sv(toml_data, ["ai", "custom", "model"], model)
        toml_changed = True

    # ── API key ──────────────────────────────────────────────────────────────
    cur_raw = _gv(toml_data, ["ai", "custom", "api_key"], "")
    has_key = bool(cur_raw)
    key_display = "(set)" if has_key else "(unset)"
    dim(f"API key {key_display}  — leave blank to keep existing or skip if not required")
    new_key = q_secret("API key", style=_STYLE).ask()
    if new_key:
        _set_secret(toml_data, ["ai", "custom", "api_key"], new_key)
        toml_changed = True
        ok("API key saved (encrypted in config.toml)")

    if toml_changed or secrets_changed:
        ok(f"Custom provider configured  [{compat} / {model or cur_model or '?'} / {(base_url or cur_base or '?')[:40]}]")
    return toml_changed, secrets_changed

def _test_llm_api(provider: str, model: str, cfg: dict) -> tuple[bool, str]:
    """Send a minimal prompt to verify the API key + model. Returns (success, reply)."""
    try:
        import asyncio

        async def _check() -> str:
            from sarthak.core.ai_utils.multi_provider import call_llm
            return (await call_llm("Reply with: ok", model=model, provider=provider, max_tokens=5, cfg=cfg)).strip()[:30]

        return True, asyncio.run(_check())
    except Exception as e:
        return False, str(e)[:80]


def _check_system_tools() -> dict[str, bool]:
    """Check presence of optional system tools used by Sarthak (cross-platform)."""
    if sys.platform == "win32":
        # On Windows use 'where' instead of 'which'; tools are mostly N/A
        tools = ["ollama"]
        return {
            t: subprocess.run(["where", t], capture_output=True).returncode == 0
            for t in tools
        }
    # Linux / macOS
    tools = ["glow", "ollama"]
    return {t: subprocess.run(["which", t], capture_output=True).returncode == 0 for t in tools}


# ── TOML helpers ──────────────────────────────────────────────────────────────

def _gv(toml_data: dict, path: list[str], default: str = "") -> str:
    """Get a nested TOML value by dotted path list."""
    cur = toml_data
    for p in path:
        if not isinstance(cur, dict) or p not in cur:
            return default
        cur = cur[p]
    return str(cur)


def _sv(toml_data: dict, path: list[str], value) -> None:
    """Set a nested TOML value, coercing to int/float/bool where appropriate."""
    cur = toml_data
    for p in path[:-1]:
        if p not in cur:
            cur[p] = tomlkit.table()
        cur = cur[p]
    key = path[-1]
    # Accept native booleans/ints/floats directly
    if isinstance(value, bool):
        cur[key] = value
        return
    if isinstance(value, (int, float)):
        cur[key] = value
        return
    s = str(value)
    if s.lower() == "true":
        cur[key] = True
    elif s.lower() == "false":
        cur[key] = False
    elif s.isdigit():
        cur[key] = int(s)
    elif s.replace(".", "", 1).isdigit() and s.count(".") == 1:
        cur[key] = float(s)
    else:
        cur[key] = s


def _get_secret(toml_data: dict, path: list[str]) -> str:
    return _decrypt_if_needed(_gv(toml_data, path, ""))


def _set_secret(toml_data: dict, path: list[str], value: str) -> None:
    from sarthak.storage.encrypt import encrypt_string

    _ensure_master_key()
    _sv(toml_data, path, encrypt_string(value) if value else "")


# ── Model selector ────────────────────────────────────────────────────────────

def _normalize_catalog(provider: str, catalog: list[str]) -> list[str]:
    return catalog

def _sync_provider_text_model(toml_data: dict, provider: str, model: str) -> None:
    """Keep provider-specific text model in sync with ai.default_model."""
    section = toml_data.get("ai", {}).get(provider, {})
    has_text = isinstance(section, dict) and "text_model" in section
    has_model = isinstance(section, dict) and "model" in section

    if has_text:
        _sv(toml_data, ["ai", provider, "text_model"], model)
    if has_model:
        _sv(toml_data, ["ai", provider, "model"], model)

    if not (has_text or has_model):
        key = "text_model" if provider == "ollama" else "model"
        _sv(toml_data, ["ai", provider, key], model)


def _ensure_provider_auth(toml_data: dict, secrets_data: dict, provider: str) -> bool:
    """Prompt for API key if not already set. Saves to config.toml (encrypted).
    Returns True if toml_data was modified."""
    if provider == "custom":
        return False  # handled entirely inside _configure_custom_provider
    canon = canonical_provider(provider)
    entry = provider_entry(canon)
    if not entry.env_key:
        return False  # provider needs no key (e.g. Ollama)
    cur = _resolve_api_key_from_data(toml_data, secrets_data, canon)
    if cur:
        return False
    label = entry.label or provider
    prompt = f"{label} API key"
    new_val = q_secret(prompt, style=_STYLE).ask()
    if not new_val:
        return False
    key_path = ["ai", canon, "api_key"]
    _set_secret(toml_data, key_path, new_val)
    ok(f"{label} API key set (saved to config.toml, encrypted)")
    return True  # toml_dirty

def _model_selector(
    label: str,
    toml_data: dict,
    secrets_data: dict,
    prov_path: list[str],
    model_path: list[str],
    vision_only: bool = False,
    sync_provider_model: bool = False,
) -> tuple[bool, bool]:
    """Pick provider + model interactively. Returns (toml_changed, secrets_changed).
    
    Existing models are shown as the default — never silently overwritten.
    """
    cur_prov  = _gv(toml_data, prov_path,  "ollama")
    cur_model = _gv(toml_data, model_path, "")
    toml_changed = False
    secrets_changed = False

    # Migrate stale provider names that no longer appear in the choices list
    _STALE_PROVIDER_MAP: dict[str, str] = {}
    if cur_prov in _STALE_PROVIDER_MAP:
        cur_prov = _STALE_PROVIDER_MAP[cur_prov]
        _sv(toml_data, prov_path, cur_prov)
        toml_changed = True

    hdr(label)
    dim(f"Current: {cur_prov} / {cur_model or '(none)'}")

    show_others = False
    while True:
        all_choices = _provider_choices(show_others=show_others) + [questionary.Choice("  <- Back", value="__back__")]
        valid_values = {c.value for c in all_choices if isinstance(c, questionary.Choice)}
        prov_default = cur_prov if cur_prov in valid_values else None
        prov = q_select(
            "Provider",
            choices=all_choices,
            default=prov_default,
            style=_STYLE,
            pointer=_POINTER,
        ).ask()
        if prov in (None, "__back__"):
            return toml_changed, secrets_changed
        if prov == "__show_others__":
            show_others = True
            continue
        if prov == "__hide_others__":
            show_others = False
            continue

        if prov == "custom":
            c_toml, c_secrets = _configure_custom_provider(toml_data, secrets_data)
            toml_changed |= c_toml
            secrets_changed |= c_secrets
            # After setup, set provider + model from what was just configured
            # and return immediately — no separate model picker for custom.
            if c_toml or c_secrets:
                _sv(toml_data, prov_path, "custom")
                configured_model = _gv(toml_data, ["ai", "custom", "model"], "")
                if configured_model:
                    _sv(toml_data, model_path, configured_model)
                    ok(f"Provider -> custom / {configured_model}")
                else:
                    ok("Provider -> custom")
                toml_changed = True
                if sync_provider_model:
                    _sync_provider_text_model(toml_data, "custom", configured_model)
            return toml_changed, secrets_changed

        if prov == "github-copilot":
            authed = _setup_github_copilot()
            if not authed:
                warn("GitHub Copilot not authenticated. Skipping provider selection.")
                continue

        toml_changed |= _ensure_provider_auth(toml_data, secrets_data, prov)

        if prov != cur_prov:
            _sv(toml_data, prov_path, prov)
            ok(f"Provider -> {prov}")
            toml_changed = True
            cur_prov = prov

        if prov not in ("custom", "github-copilot"):
            entry = provider_entry(prov)
            if entry.base_url:
                base_path = ["ai", prov, "base_url"]
                current_base = _gv(toml_data, base_path, "")
                if not current_base:
                    _sv(toml_data, base_path, entry.base_url)
                    ok(f"{entry.label} base_url -> {entry.base_url}")
                    toml_changed = True

        if prov == "ollama":
            base_path = ["ai", "ollama", "base_url"]
            current_base = _gv(toml_data, base_path, "http://localhost:11434/v1")
            dim("Ollama base URL (OpenAI-compatible, should end with /v1)")
            new_base = q_text("Base URL", default=current_base, style=_STYLE).ask()
            if new_base and new_base != current_base:
                _sv(toml_data, base_path, new_base)
                ok(f"Ollama base_url -> {new_base}")
                toml_changed = True

        # Build model list
        if prov == "ollama":
            dim(f"Scanning local Ollama models{' (vision)' if vision_only else ''}...")
        catalog = _fetch_models(prov, toml_data, secrets_data, vision_only=vision_only)
        catalog = _normalize_catalog(prov, catalog)
        meta_map = _model_meta_map(prov)

        if catalog:
            # Bubble recommended default to top without hiding current
            rec = _provider_defaults(prov)[1 if vision_only else 0]
            if rec and rec in catalog and rec != cur_model:
                catalog = [rec] + [m for m in catalog if m != rec]
            default_sel = cur_model if cur_model in catalog else catalog[0]

            while True:
                choices = catalog[:] + ["<- Back"]

                new_model = q_autocomplete(
                    f"Model{' (vision-capable)' if vision_only else ''}",
                    choices=choices,
                    default=default_sel if default_sel in catalog else None,
                    style=_STYLE,
                    match_middle=True,
                ).ask()

                if new_model in (None, "<- Back"):
                    break

                # Picked a model
                from sarthak.core.ai_utils.multi_provider import normalize_model_name
                new_model = normalize_model_name(prov, new_model)
                if new_model != cur_model:
                    _sv(toml_data, model_path, new_model)
                    ok(f"Model -> {new_model}")
                    toml_changed = True
                    if sync_provider_model:
                        _sync_provider_text_model(toml_data, prov, new_model)
                return toml_changed, secrets_changed

            # back from model selection to provider selection
            continue

        # No catalog: offer manual entry or back
        choice = q_select(
            "Model catalog not found",
            choices=[
                questionary.Choice("  Enter manually", value="__manual__"),
                questionary.Choice("  <- Back", value="__back__"),
            ],
            style=_STYLE,
            pointer=_POINTER,
        ).ask()
        if choice in (None, "__back__"):
            continue

        dim("Enter model name manually:")
        new_model = q_text("Model ID", default=cur_model, style=_STYLE).ask()
        if not new_model:
            continue

        from sarthak.core.ai_utils.multi_provider import normalize_model_name
        new_model = normalize_model_name(prov, new_model)
        if new_model != cur_model:
            _sv(toml_data, model_path, new_model)
            ok(f"Model -> {new_model}")
            toml_changed = True
            if sync_provider_model:
                _sync_provider_text_model(toml_data, prov, new_model)
        return toml_changed, secrets_changed


# ── Submenu: API Keys ─────────────────────────────────────────────────────────

_SECRET_FIELDS: list[tuple[str, list[str], str, bool]] = [
    ("Telegram bot token", ["telegram", "bot_token"], "123456:ABCDEF...", True),
]


def _ensure_master_key() -> None:
    """Ensure master key exists at ~/.sarthak_ai/master.key."""
    if MASTER_KEY_FILE.exists():
        return
    import base64
    MASTER_KEY_FILE.parent.mkdir(parents=True, exist_ok=True)
    key = base64.b64encode(os.urandom(32)).decode()
    MASTER_KEY_FILE.write_text(key + "\n")
    os.chmod(MASTER_KEY_FILE, 0o600)
    ok("Master key generated (stored in master.key)")


def _section_api_keys(toml_data: dict, secrets_data: dict) -> tuple[bool, bool]:
    """Edit miscellaneous API keys interactively. Returns (toml_dirty, secrets_dirty).

    Provider API keys (Gemini, OpenAI, etc.) are set during model selection.
    This section handles other secrets (e.g. Telegram token).
    """
    toml_dirty = False
    secrets_dirty = False
    _ensure_master_key()

    while True:
        hdr("API Keys")
        dim("Provider AI keys are set during model selection — use 'Models & Providers'.")
        choices = []
        for name, path, hint, _encrypt in _SECRET_FIELDS:
            val = _get_secret(toml_data, path)
            status = "(set)" if val else "(unset)"
            choices.append(questionary.Choice(f"  {name:<22} {status}", value=".".join(path)))
        choices.append(questionary.Separator())
        choices.append(questionary.Choice("  <- Back", value="__back__"))

        sel = q_select("Select key", choices=choices, style=_STYLE, pointer=_POINTER).ask()
        if sel in (None, "__back__"):
            break

        entry = next((e for e in _SECRET_FIELDS if ".".join(e[1]) == sel), None)
        if not entry:
            continue
        name, path, hint, encrypt_val = entry
        cur = _get_secret(toml_data, path)
        dim(f"Format hint: {hint}")

        new_val = q_secret(name, style=_STYLE).ask()

        if new_val is None or (new_val == cur):
            continue

        if encrypt_val and new_val:
            _set_secret(toml_data, path, new_val)
            toml_dirty = True
        else:
            _sv(toml_data, path, new_val)
            toml_dirty = True
        ok(f"{name} updated")

    return toml_dirty, secrets_dirty


# ── Submenu: General / UI ─────────────────────────────────────────────────────

_GENERAL_SETTINGS: list[tuple[str, list[str], str]] = [
    ("Log level", ["general", "log_level"], "debug / info / warning / error"),
    ("TUI theme", ["tui",     "theme"],     "midnight / onedark / catppuccin / tokyo / gruvbox / nord / rose_pine"),
    ("TUI font",  ["tui",     "font"],      "Any Nerd Font name"),
]


def _section_general(toml_data: dict) -> bool:
    """Edit general/UI settings. Returns toml_dirty."""
    toml_dirty = False

    while True:
        hdr("General / UI")
        choices = [
            questionary.Choice(f"  {name:<18} [{_gv(toml_data, path)}]", value=name)
            for name, path, _ in _GENERAL_SETTINGS
        ]
        choices.append(questionary.Separator())
        choices.append(questionary.Choice("  <- Back", value="__back__"))

        sel = q_select("Select setting", choices=choices, style=_STYLE, pointer=_POINTER).ask()
        if sel in (None, "__back__"):
            break

        entry = next((e for e in _GENERAL_SETTINGS if e[0] == sel), None)
        if not entry:
            continue
        name, path, desc = entry
        cur = _gv(toml_data, path)
        dim(desc)

        new_val = q_text(name, default=cur, style=_STYLE).ask()
        if new_val and new_val != cur:
            _sv(toml_data, path, new_val)
            ok(f"{name} -> {new_val}")
            toml_dirty = True

    return toml_dirty


# ── Submenu: Channels ─────────────────────────────────────────────────────────

def _section_telegram(toml_data: dict, secrets_data: dict) -> tuple[bool, bool]:
    """Configure Telegram bot. Returns (toml_dirty, secrets_dirty)."""
    toml_dirty = False
    secrets_dirty = False

    hdr("Telegram Bot")
    dim("Create a bot via @BotFather and paste the token here.")
    dim("Allowed user ID: message @userinfobot and copy the numeric ID.")

    tg_enabled = _gv(toml_data, ["telegram", "enabled"], "false").lower()
    tg_allowed = _gv(toml_data, ["telegram", "allowed_user_id"], "")

    enabled = q_confirm(
        "Enable Telegram bot?",
        default=(tg_enabled == "true"),
        style=_STYLE,
    ).ask()
    if enabled is None:
        return toml_dirty, secrets_dirty
    if str(enabled).lower() != tg_enabled:
        _sv(toml_data, ["telegram", "enabled"], str(enabled).lower())
        toml_dirty = True

    new_allowed = q_text(
        "Allowed user ID",
        default=tg_allowed,
        style=_STYLE,
    ).ask()
    if new_allowed and new_allowed != tg_allowed:
        _sv(toml_data, ["telegram", "allowed_user_id"], new_allowed)
        toml_dirty = True

    new_token = q_secret("Bot token (blank = keep existing)", style=_STYLE).ask()
    if new_token:
        _set_secret(toml_data, ["telegram", "bot_token"], new_token)
        toml_dirty = True
        ok("Telegram token updated")

    cur_timeout = _gv(toml_data, ["telegram", "timeout_seconds"], "60")
    dim("Increase timeout if your network is slow or API calls are timing out.")
    new_timeout = q_text(
        "HTTP timeout (seconds)",
        default=cur_timeout,
        style=_STYLE,
    ).ask()
    if new_timeout and new_timeout != cur_timeout:
        _sv(toml_data, ["telegram", "timeout_seconds"], new_timeout)
        toml_dirty = True

    return toml_dirty, secrets_dirty


def _configure_whatsapp_qr(toml_data: dict) -> bool:
    """Run neonize QR login in the terminal (ASCII QR, no browser).

    Blocks until the user scans or 120 s elapse.
    Writes whatsapp.jid, mode=qr, enabled=true to toml_data.
    Returns toml_dirty.
    """
    hdr("WhatsApp — QR Login (neonize)")

    try:
        import qrcode  # type: ignore
        from neonize.client import ClientFactory  # type: ignore
        from neonize.events import ConnectedEv, OfflineSyncCompletedEv  # type: ignore
    except ImportError as e:
        err(f"Missing dependency: {e}")
        info("Install with: pip install neonize qrcode")
        return False

    import threading
    from sarthak.features.channels.whatsapp import SESSION_DB as _SESSION_DB

    result: dict = {}
    done = threading.Event()
    sync_done = threading.Event()
    factory = ClientFactory(database_name=_SESSION_DB)
    client = factory.new_client(uuid="sarthak-bot")

    def on_qr(_, data: bytes) -> None:
        qr = qrcode.QRCode(border=1)
        qr.add_data(data.decode("utf-8", errors="replace"))
        qr.make(fit=True)
        click.clear()
        click.echo(f"\n{OR}{BD}:: Scan this QR with WhatsApp{RS}\n")
        qr.print_ascii(out=None, tty=True)
        click.echo(f"\n  {DM}WhatsApp → Linked Devices → Link a Device{RS}\n")

    client.event.qr(on_qr)

    @client.event(ConnectedEv)
    def on_connected(cl, ev) -> None:
        try:
            result["jid"] = cl.me.JID.User if getattr(cl, "me", None) else ""
        except Exception:
            result["jid"] = ""
        done.set()

    @client.event(OfflineSyncCompletedEv)
    def on_sync_done(_cl, _ev) -> None:
        sync_done.set()

    info("Starting neonize — QR code will appear momentarily…")
    connect_thread = threading.Thread(target=client.connect, daemon=True)
    connect_thread.start()

    from sarthak.core.config import load_config as _load_cfg
    _timeout = int(_load_cfg().get("whatsapp", {}).get("session_timeout", 120))
    connected = done.wait(timeout=_timeout)

    if not connected:
        try:
            client.disconnect()
        except Exception:
            pass
        err(f"QR login timed out ({_timeout} s). Try again or increase whatsapp.session_timeout in config.")
        return False

    jid = result.get("jid", "")
    ok(f"WhatsApp paired  [{jid}]")
    info("Waiting for app state sync (up to 45 s) — do not close this window…")
    sync_done.wait(timeout=45)
    ok("Sync complete." if sync_done.is_set() else "Sync timeout — proceeding anyway.")

    try:
        client.disconnect()
    except Exception:
        pass

    _sv(toml_data, ["whatsapp", "jid"],     jid)
    _sv(toml_data, ["whatsapp", "mode"],    "qr")
    _sv(toml_data, ["whatsapp", "enabled"], True)
    return True


def _section_whatsapp_settings(toml_data: dict) -> bool:
    """Edit all neonize-relevant WhatsApp settings. Returns toml_dirty.

    Settings map to config.toml [whatsapp] keys consumed by neonize_bot.py:

      push_name        — display name shown to contacts (default: "Sarthak")
      allow_groups     — accept messages from group chats (default: false)
      send_read_receipt — mark messages read after replying (default: true)
      send_presence    — set online/available during active sessions (default: false)
      reconnect_backoff_max  — max reconnect wait in seconds (default: 300)
      reconnect_backoff_init — initial reconnect wait in seconds (default: 5)
      session_timeout  — neonize QR session validity in seconds (default: 120)
      proxy            — HTTP/SOCKS5 proxy URL, blank = none
    """
    hdr("WhatsApp — neonize Settings")

    # (label, path, hint, default_value)
    settings: list[tuple[str, list[str], str, str]] = [
        ("Push name",            ["whatsapp", "push_name"],           "Display name shown to contacts", "Sarthak"),
        ("Reconnect backoff max",["whatsapp", "reconnect_backoff_max"],"Max wait between reconnects (s)", "300"),
        ("Reconnect backoff init",["whatsapp","reconnect_backoff_init"],"Initial reconnect wait (s)", "5"),
        ("QR session timeout",   ["whatsapp", "session_timeout"],     "Seconds to wait for QR scan", "120"),
        ("Proxy URL",            ["whatsapp", "proxy"],               "HTTP/SOCKS5 proxy e.g. socks5://127.0.0.1:9050 (blank = none)", ""),
    ]
    bool_settings: list[tuple[str, list[str], str, bool]] = [
        ("Allow group messages",  ["whatsapp", "allow_groups"],       "Accept messages from group chats", False),
        ("Send read receipts",    ["whatsapp", "send_read_receipt"],  "Mark messages read after replying", True),
        ("Send presence (online)",["whatsapp", "send_presence"],      "Appear online during active sessions", False),
    ]

    toml_dirty = False
    while True:
        str_choices = [
            questionary.Choice(
                f"  {label:<28} [{_gv(toml_data, path, default)}]",
                value=label,
            )
            for label, path, _, default in settings
        ]
        bool_choices = [
            questionary.Choice(
                f"  {label:<28} [{'on' if _gv(toml_data, path, str(default).lower()) not in ('false','0','') else 'off'}]",
                value=label,
            )
            for label, path, _, default in bool_settings
        ]
        all_choices = (
            str_choices
            + [questionary.Separator("── toggles ──")]
            + bool_choices
            + [questionary.Separator(), questionary.Choice("  <- Back", value="__back__")]
        )

        sel = q_select("Setting", choices=all_choices, style=_STYLE, pointer=_POINTER).ask()
        if sel in (None, "__back__"):
            break

        # String settings
        str_entry = next((e for e in settings if e[0] == sel), None)
        if str_entry:
            label, path, hint, default = str_entry
            cur = _gv(toml_data, path, default)
            dim(hint)
            new = q_text(label, default=cur, style=_STYLE).ask()
            if new is not None and new != cur:
                _sv(toml_data, path, new)
                ok(f"{label} → {new or '(cleared)'}")
                toml_dirty = True
            continue

        # Bool settings
        bool_entry = next((e for e in bool_settings if e[0] == sel), None)
        if bool_entry:
            label, path, hint, default = bool_entry
            cur_str = _gv(toml_data, path, str(default).lower())
            cur_bool = cur_str not in ("false", "0", "")
            dim(hint)
            new_bool = q_confirm(label, default=cur_bool, style=_STYLE).ask()
            if new_bool is not None and new_bool != cur_bool:
                _sv(toml_data, path, new_bool)
                ok(f"{label} → {'on' if new_bool else 'off'}")
                toml_dirty = True

    return toml_dirty


def _section_whatsapp(toml_data: dict, secrets_data: dict) -> tuple[bool, bool]:
    """Configure WhatsApp via neonize. Returns (toml_dirty, secrets_dirty)."""
    toml_dirty    = False
    secrets_dirty = False  # kept for call-site compat

    while True:
        wa_enabled = _gv(toml_data, ["whatsapp", "enabled"], "false").lower()
        wa_jid     = _gv(toml_data, ["whatsapp", "jid"], "")
        push_name  = _gv(toml_data, ["whatsapp", "push_name"], "Sarthak")
        proxy      = _gv(toml_data, ["whatsapp", "proxy"], "")
        groups     = _gv(toml_data, ["whatsapp", "allow_groups"], "false")
        presence   = _gv(toml_data, ["whatsapp", "send_presence"], "false")

        status_line = (
            f"{'on' if wa_enabled == 'true' else 'off'}"
            f", jid: {wa_jid or '(not paired)'}"
            f", name: {push_name}"
            + (f", proxy: {proxy[:20]}" if proxy else "")
            + (f", groups: on" if groups not in ("false", "0", "") else "")
            + (f", presence: on" if presence not in ("false", "0", "") else "")
        )

        hdr("WhatsApp — neonize")
        dim(status_line)
        click.echo("")

        choices = [
            questionary.Choice(
                f"  {'Re-scan QR' if wa_jid else 'Scan QR to pair'}  "
                f"{'— already paired, re-pair?' if wa_jid else '— connect your WhatsApp account'}",
                value="scan",
            ),
            questionary.Choice(
                f"  {'Disable' if wa_enabled == 'true' else 'Enable'} bot",
                value="toggle",
            ),
            questionary.Choice("  Settings  — push name, proxy, presence, groups…", value="settings"),
            questionary.Choice("  Logout    — disconnect and delete session",        value="logout"),
            questionary.Separator(),
            questionary.Choice("  <- Back", value="__back__"),
        ]

        action = q_select("Action", choices=choices, style=_STYLE, pointer=_POINTER).ask()
        if action in (None, "__back__"):
            break

        if action == "scan":
            toml_dirty |= _configure_whatsapp_qr(toml_data)

        elif action == "toggle":
            new_state = not (wa_enabled == "true")
            _sv(toml_data, ["whatsapp", "enabled"], new_state)
            ok(f"WhatsApp {'enabled' if new_state else 'disabled'}")
            toml_dirty = True

        elif action == "settings":
            toml_dirty |= _section_whatsapp_settings(toml_data)

        elif action == "logout":
            confirmed = q_confirm(
                "Stop bot and delete session? You will need to re-scan QR to reconnect.",
                default=False,
                style=_STYLE,
            ).ask()
            if confirmed:
                # Clear config fields
                _sv(toml_data, ["whatsapp", "jid"],     "")
                _sv(toml_data, ["whatsapp", "enabled"], False)
                toml_dirty = True
                # Delete session DB on disk
                try:
                    from sarthak.features.channels.whatsapp import SESSION_DB
                    if SESSION_DB.exists():
                        SESSION_DB.unlink()
                        ok("Session DB deleted")
                except Exception as exc:
                    warn(f"Could not delete session DB: {exc}")
                ok("Logged out — restart orchestrator to stop the bot process")

    return toml_dirty, secrets_dirty


def _section_channels(toml_data: dict, secrets_data: dict) -> tuple[bool, bool]:
    """Edit channel settings. Returns (toml_dirty, secrets_dirty)."""
    toml_dirty = False
    secrets_dirty = False

    while True:
        hdr("Channels")

        # Telegram status
        tg_enabled = _gv(toml_data, ["telegram", "enabled"], "false").lower()
        tg_allowed = _gv(toml_data, ["telegram", "allowed_user_id"], "")
        tg_token   = _get_secret(toml_data, ["telegram", "bot_token"])
        tg_status  = f"{'on' if tg_enabled == 'true' else 'off'}, user: {tg_allowed or '-'}, token: {'set' if tg_token else 'unset'}"

        # WhatsApp status
        wa_enabled = _gv(toml_data, ["whatsapp", "enabled"], "false").lower()
        wa_jid     = _gv(toml_data, ["whatsapp", "jid"], "")
        wa_status  = f"{'on' if wa_enabled == 'true' else 'off'}, jid: {wa_jid or 'unset (scan QR to pair)'}"

        choices = [
            questionary.Choice(f"  Telegram     [{tg_status}]",  value="telegram"),
            questionary.Choice(f"  WhatsApp     [{wa_status}]",  value="whatsapp"),
            questionary.Separator(),
            questionary.Choice("  <- Back", value="__back__"),
        ]

        sel = q_select("Select channel", choices=choices, style=_STYLE, pointer=_POINTER).ask()
        if sel in (None, "__back__"):
            break

        if sel == "telegram":
            tg_toml, tg_secrets = _section_telegram(toml_data, secrets_data)
            toml_dirty |= tg_toml
            secrets_dirty |= tg_secrets
        elif sel == "whatsapp":
            wa_toml, wa_secrets = _section_whatsapp(toml_data, secrets_data)
            toml_dirty |= wa_toml
            secrets_dirty |= wa_secrets

    return toml_dirty, secrets_dirty


# ── Submenu: Embedding Model ─────────────────────────────────────────────────

_EMBED_FALLBACK = [
    "openai:text-embedding-3-small",
    "openai:text-embedding-3-large",
    "openai:text-embedding-ada-002",
    "ollama:nomic-embed-text",
    "ollama:mxbai-embed-large",
    "ollama:all-minilm",
    "gemini:models/text-embedding-004",
]


def _embed_choices() -> list[str]:
    """Load embedding model list from providers catalog; fall back to hardcoded list."""
    try:
        from sarthak.core.ai_utils.catalog import list_embedding_models
        models = list_embedding_models()
        if models:
            return models + ["<- Back"]
    except Exception:
        pass
    return _EMBED_FALLBACK + ["<- Back"]


def _section_embedding(toml_data: dict, secrets_data: dict) -> bool:
    """Configure the RAG embedding model. Returns toml_dirty."""
    hdr("Embedding Model (RAG / Vector Search)")
    dim("Used for indexing workspace files and semantic search.")
    dim("Format: provider:model-id  e.g. openai:text-embedding-3-small")

    cur = _gv(toml_data, ["ai", "embeddings", "model"], "openai:text-embedding-3-small")
    dim(f"Current: {cur}")
    choices = _embed_choices()

    val = q_autocomplete(
        "Embedding model",
        choices=choices,
        default=cur if cur in choices else "",
        style=_STYLE,
        match_middle=True,
    ).ask()

    if val in (None, "<- Back") or val == cur:
        return False

    # Auto-detect provider from format  provider:model
    if ":" in val:
        prov, _ = val.split(":", 1)
        _sv(toml_data, ["ai", "embeddings", "provider"], prov)
        # Ensure provider auth is set if needed
        _ensure_provider_auth(toml_data, secrets_data, prov)

    _sv(toml_data, ["ai", "embeddings", "model"], val)
    ok(f"Embedding model → {val}")
    warn("Re-index your spaces after changing the embedding model (RAG index will be stale).")
    return True


# ── Submenu: Vision Model ──────────────────────────────────────────────────────

def _section_vision(toml_data: dict, secrets_data: dict) -> tuple[bool, bool]:
    """Configure the vision model used for OCR and image understanding."""
    hdr("Vision Model (OCR / Images)")
    dim("Used for handwritten notes OCR and image understanding.")
    dim("Pick a model with vision capability.")

    prov_path = ["ai", "vision", "provider"]
    model_path = ["ai", "vision", "model"]

    model_toml, model_secrets = _model_selector(
        "Vision Model (OCR)",
        toml_data,
        secrets_data,
        prov_path=prov_path,
        model_path=model_path,
        vision_only=True,
    )
    return model_toml, model_secrets


# ── Submenu: Fallback Models ─────────────────────────────────────────────────

def _section_fallback(toml_data: dict, secrets_data: dict) -> bool:
    """Configure fallback model chain. Returns toml_dirty."""
    toml_dirty = False

    hdr("Fallback Model Chain")
    dim("If the primary model fails (4xx/5xx or empty response), Sarthak tries fallback1 then fallback2.")
    dim("Use a fast local model (ollama) or a paid API as fallback.")

    for slot in (1, 2):
        prov_path  = ["ai", "fallback", f"fallback{slot}_provider"]
        model_path = ["ai", "fallback", f"fallback{slot}_model"]
        cur_prov   = _gv(toml_data, prov_path, "")
        cur_model  = _gv(toml_data, model_path, "")

        info(f"\nFallback {slot}: {cur_prov or '(none)'} / {cur_model or '(none)'}")
        changed = q_confirm(
            f"Configure fallback {slot}?",
            default=bool(cur_prov),
            style=_STYLE,
        ).ask()
        if not changed:
            continue

        model_toml, model_secrets = _model_selector(
            f"Fallback {slot} Model",
            toml_data,
            secrets_data,
            prov_path=prov_path,
            model_path=model_path,
        )
        toml_dirty |= model_toml

    # Option to disable fallbacks entirely
    disable = q_confirm(
        "Disable all fallbacks? (clears both slots)",
        default=False,
        style=_STYLE,
    ).ask()
    if disable:
        for slot in (1, 2):
            _sv(toml_data, ["ai", "fallback", f"fallback{slot}_provider"], "")
            _sv(toml_data, ["ai", "fallback", f"fallback{slot}_model"], "")
        ok("Fallbacks disabled.")
        toml_dirty = True

    return toml_dirty


# ── Submenu: Tools ──────────────────────────────────────────────────────────────

# (label, toml path, hint, default)
_STT_PROVIDER_PARAMS: dict[str, list[tuple[str, list[str], str, str]]] = {
    "whisper": [
        ("Model",      ["stt", "whisper", "model"],      "base.en | base | small | medium | large-v3", "base.en"),
        ("Model path", ["stt", "whisper", "model_path"], "Absolute path to .bin file (blank = auto)",  ""),
        ("Device",     ["stt", "whisper", "device"],     "CPU | GPU | NPU",                            "CPU"),
        ("Beam size",  ["stt", "whisper", "beam_size"],  "1 = fastest, 5 = best quality",              "5"),
        ("Threads",    ["stt", "whisper", "threads"],    "CPU threads (0 = whisper-cli default)",       "0"),
        ("Language",   ["stt", "language"],              "en | fr | de | ... or auto",                 "auto"),
    ],
    "openai": [
        ("API key",  ["stt", "openai", "api_key"],  "or set env OPENAI_API_KEY",                             ""),
        ("Model",    ["stt", "openai", "model"],    "whisper-1",                                             "whisper-1"),
        ("Base URL", ["stt", "openai", "base_url"], "blank = default; override for Azure / compatible APIs", ""),
    ],
    "groq": [
        ("API key", ["stt", "groq", "api_key"], "or set env GROQ_API_KEY",              ""),
        ("Model",   ["stt", "groq", "model"],   "whisper-large-v3-turbo | whisper-large-v3", "whisper-large-v3-turbo"),
    ],
    "deepgram": [
        ("API key", ["stt", "deepgram", "api_key"], "or set env DEEPGRAM_API_KEY", ""),
        ("Model",   ["stt", "deepgram", "model"],   "nova-2 | nova | enhanced",    "nova-2"),
        ("Tier",    ["stt", "deepgram", "tier"],    "blank = default",             ""),
    ],
    "assemblyai": [
        ("API key", ["stt", "assemblyai", "api_key"], "or set env ASSEMBLYAI_API_KEY", ""),
    ],
}

_STT_PROVIDERS = [
    ("whisper",    "local, fully offline"),
    ("openai",     "OpenAI Whisper API"),
    ("groq",       "Groq Whisper API"),
    ("deepgram",   "Deepgram Nova-2"),
    ("assemblyai", "AssemblyAI Universal"),
]


# Per-platform whisper.cpp install guidance shown during interactive install
_WHISPER_INSTALL_GUIDE: dict[str, list[str]] = {
    "linux": [
        "Option A — pip wheel (CPU-only, easiest):",
        "  pip install openai-whisper",
        "Option B — whisper.cpp (faster, GPU support):",
        "  sudo apt install build-essential cmake",
        "  git clone https://github.com/ggml-org/whisper.cpp && cd whisper.cpp",
        "  cmake -B build && cmake --build build -j$(nproc)",
        "  sudo cp build/bin/whisper-cli /usr/local/bin/",
    ],
    "darwin": [
        "Option A — Homebrew (recommended):",
        "  brew install whisper-cpp",
        "Option B — build from source (Apple Silicon GPU):",
        "  git clone https://github.com/ggml-org/whisper.cpp && cd whisper.cpp",
        "  cmake -B build -DGGML_METAL=ON && cmake --build build -j$(sysctl -n hw.ncpu)",
        "  sudo cp build/bin/whisper-cli /usr/local/bin/",
    ],
    "win32": [
        "Option A — pip wheel (CPU-only, easiest):",
        "  pip install openai-whisper",
        "Option B — pre-built binary:",
        "  Download from: https://github.com/ggml-org/whisper.cpp/releases",
        "  Extract whisper-cli.exe and add its folder to PATH.",
    ],
}


def _whisper_cli_found() -> bool:
    import shutil
    return bool(shutil.which("whisper-cli") or shutil.which("whisper"))


def _install_whisper_interactive(toml_data: dict) -> bool:
    """Guide the user through installing whisper-cli and optionally downloading a model.
    Returns toml_dirty."""
    import urllib.request
    toml_dirty = False
    platform_key = sys.platform if sys.platform in _WHISPER_INSTALL_GUIDE else "linux"

    hdr("Whisper STT — Install")
    if _whisper_cli_found():
        ok("whisper-cli already found in PATH — nothing to install.")
    else:
        warn("whisper-cli not found in PATH.")
        click.echo("")
        for line in _WHISPER_INSTALL_GUIDE[platform_key]:
            info(line)
        click.echo("")
        input("  Press Enter once whisper-cli is installed and in PATH…")
        if _whisper_cli_found():
            ok("whisper-cli found — install confirmed!")
        else:
            warn("Still not found in PATH. You can re-run this step after adding it to PATH.")
            return toml_dirty

    # Offer to download the default model
    model_name = _gv(toml_data, ["stt", "whisper", "model"], _gv(toml_data, ["whisper", "model"], "base.en"))
    models_dir = BASE_DIR / "whisper_models"
    model_file = models_dir / f"ggml-{model_name}.bin"

    if model_file.exists():
        ok(f"Model already downloaded: {model_file}")
        _sv(toml_data, ["stt", "whisper", "model_path"], str(model_file))
        return toml_dirty

    ans = questionary.confirm(
        f"  Download default model ({model_name}) to {models_dir}?",
        default=True, style=_STYLE,
    ).ask()
    if not ans:
        return toml_dirty

    url = f"https://huggingface.co/ggerganov/whisper.cpp/resolve/main/ggml-{model_name}.bin"
    models_dir.mkdir(parents=True, exist_ok=True)
    info(f"Downloading {url} …")
    try:
        urllib.request.urlretrieve(url, model_file)
        ok(f"Saved to {model_file}")
        _sv(toml_data, ["stt", "whisper", "model_path"], str(model_file))
        toml_dirty = True
    except Exception as exc:
        warn(f"Download failed: {exc}")
        info("You can place the .bin file manually in ~/.sarthak_ai/whisper_models/ and set model_path in settings.")

    return toml_dirty


def _invalidate_stt() -> None:
    try:
        from sarthak.spaces.roadmap.stt import invalidate_stt_cache
        invalidate_stt_cache()
    except Exception:
        pass


def _edit_stt_provider_params(toml_data: dict, provider_key: str) -> bool:
    """Edit all params for an STT provider inline. Returns toml_dirty."""
    params = _STT_PROVIDER_PARAMS.get(provider_key, [])
    hdr(f"STT — {provider_key.title()} Settings")
    toml_dirty = False
    while True:
        param_choices = [
            questionary.Choice(
                f"  {label:<12} [{'*****' if 'key' in label.lower() and _gv(toml_data, path, default) else _gv(toml_data, path, default)}]",
                value=label,
            )
            for label, path, hint, default in params
        ]
        param_choices += [questionary.Separator(), questionary.Choice("  <- Back", value="__back__")]
        sel = q_select(f"{provider_key.title()} parameter", choices=param_choices, style=_STYLE, pointer=_POINTER).ask()
        if sel in (None, "__back__"):
            break
        entry = next((e for e in params if e[0] == sel), None)
        if not entry:
            continue
        label, path, hint, default = entry
        cur = _gv(toml_data, path, default)
        dim(hint)
        new_val = q_text(label, default=cur, style=_STYLE).ask()
        if new_val is not None and new_val != cur:
            _sv(toml_data, path, new_val)
            ok(f"{label} -> {new_val}")
            toml_dirty = True
            _invalidate_stt()
    return toml_dirty


def _section_tools(toml_data: dict) -> bool:
    """Configure external tools. Returns toml_dirty."""
    toml_dirty = False

    while True:
        hdr("Tools")
        whisper_ok = _whisper_cli_found()
        w_status = "installed" if whisper_ok else "not installed"
        cur_provider = _gv(toml_data, ["stt", "provider"], "whisper")
        choices = [
            questionary.Choice(f"  STT provider   [active: {cur_provider}]", value="stt_provider"),
            questionary.Separator(),
            questionary.Choice(f"  Whisper — install  [{w_status}]", value="whisper_install"),
        ] + [
            questionary.Choice(f"  {p:<12} settings", value=f"{p}_settings")
            for p, _ in _STT_PROVIDERS
        ] + [
            questionary.Separator(),
            questionary.Choice("  <- Back", value="__back__"),
        ]
        sel = q_select("Select tool", choices=choices, style=_STYLE, pointer=_POINTER).ask()
        if sel in (None, "__back__"):
            break

        if sel == "stt_provider":
            hdr("STT — Choose Provider")
            cur = _gv(toml_data, ["stt", "provider"], "whisper")
            new_provider = q_select(
                f"Provider (current: {cur})",
                choices=[questionary.Choice(f"  {p:<12} — {desc}", value=p) for p, desc in _STT_PROVIDERS],
                style=_STYLE, pointer=_POINTER,
            ).ask()
            if new_provider and new_provider != cur:
                _sv(toml_data, ["stt", "provider"], new_provider)
                ok(f"STT provider → {new_provider}")
                toml_dirty = True
                _invalidate_stt()

        elif sel == "whisper_install":
            toml_dirty |= _install_whisper_interactive(toml_data)

        elif sel and sel.endswith("_settings"):
            provider_key = sel[:-len("_settings")]
            if provider_key == "whisper" and not whisper_ok:
                warn("whisper-cli not found in PATH. Configure paths/params anyway?")
            toml_dirty |= _edit_stt_provider_params(toml_data, provider_key)

    return toml_dirty


# ── Non-interactive Whisper default install ───────────────────────────────────

def install_whisper_defaults() -> None:
    """Download the default Whisper model and write [whisper] defaults to config.toml.
    Called non-interactively from install.sh."""
    import shutil
    import urllib.request

    config_file = BASE_DIR / "config.toml"
    if not config_file.exists():
        warn("config.toml not found — run install.sh first to create it.")
        return

    toml_data = tomlkit.parse(config_file.read_text())
    models_dir = BASE_DIR / "whisper_models"
    models_dir.mkdir(parents=True, exist_ok=True)

    # Prefer [stt.whisper]; fall back to legacy [whisper] for existing installs
    stt_cfg = toml_data.setdefault("stt", tomlkit.table())
    if not isinstance(stt_cfg, dict):
        toml_data["stt"] = tomlkit.table()
        stt_cfg = toml_data["stt"]
    w = stt_cfg.get("whisper")
    if not isinstance(w, dict):
        stt_cfg["whisper"] = tomlkit.table()
        w = stt_cfg["whisper"]

    # Fall back to legacy [whisper] model name if not set in [stt.whisper]
    legacy_w = toml_data.get("whisper", {})
    model = str(w.get("model") or legacy_w.get("model") or "base.en").strip() or "base.en"
    model_file = models_dir / f"ggml-{model}.bin"

    _MIN = 10 * 1024 * 1024
    if model_file.exists() and model_file.stat().st_size >= _MIN:
        ok(f"Whisper model already present: {model_file.name}")
    else:
        url = (
            f"https://huggingface.co/ggerganov/whisper.cpp/resolve/main/"
            f"ggml-{model}.bin"
        )
        info(f"Downloading Whisper model: {model} ...")
        try:
            urllib.request.urlretrieve(url, model_file)
            if model_file.stat().st_size < _MIN:
                model_file.unlink(missing_ok=True)
                raise RuntimeError("Download incomplete — file too small")
            ok(f"Model saved: {model_file}")
        except Exception as exc:
            warn(f"Model download failed: {exc}")
            warn(f'  curl -fL "{url}" -o "{model_file}"')
            return

    defaults: dict[str, object] = {
        "model": model,
        "model_path": str(model_file),
        "device": "CPU",
        "beam_size": 5,
        "threads": 0,
    }
    for k, v in defaults.items():
        if k not in w:
            w[k] = v
    # Always sync model_path to the downloaded file
    w["model_path"] = str(model_file)
    # Ensure provider is set to whisper if not yet configured
    if not stt_cfg.get("provider"):
        stt_cfg["provider"] = "whisper"
    if not stt_cfg.get("language"):
        stt_cfg["language"] = "auto"
    config_file.write_text(tomlkit.dumps(toml_data))
    ok("Whisper defaults written to config.toml")

    if shutil.which("whisper-cli") or shutil.which("whisper"):
        ok("whisper-cli found in PATH")
    else:
        warn("whisper-cli not found in PATH — voice dictation will be unavailable.")
        info("Install: https://github.com/ggml-org/whisper.cpp")


# ── Submenu: Agent Sandbox ───────────────────────────────────────────────────

# (label, config.toml path, hint, default value as str)
_SANDBOX_SYSTEM_PARAMS: list[tuple[str, list[str], str, str]] = [
    # See docs/guides/configuration.md — [agents.sandbox.system]
    ("enabled",       ["agents", "sandbox", "system", "enabled"],       "true / false (false = dev only, unsafe)", "true"),
    ("wall_timeout",  ["agents", "sandbox", "system", "wall_timeout"],  "seconds before agent is killed",         "120"),
    ("memory_cap",    ["agents", "sandbox", "system", "memory_cap"],    "bytes (default 268435456 = 256 MB)",     "268435456"),
    ("cpu_seconds",   ["agents", "sandbox", "system", "cpu_seconds"],   "subprocess CPU cap (POSIX only)",        "30"),
    ("output_cap",    ["agents", "sandbox", "system", "output_cap"],    "max characters saved to run output",     "65536"),
    ("max_web_calls", ["agents", "sandbox", "system", "max_web_calls"], "web search calls allowed per run",      "10"),
]

_SANDBOX_SPACE_PARAMS: list[tuple[str, list[str], str, str]] = [
    # See docs/guides/configuration.md — [agents.sandbox.space]
    ("enabled",       ["agents", "sandbox", "space", "enabled"],       "true / false (false = dev only, unsafe)", "true"),
    ("wall_timeout",  ["agents", "sandbox", "space", "wall_timeout"],  "seconds before agent is killed",         "300"),
    ("memory_cap",    ["agents", "sandbox", "space", "memory_cap"],    "bytes (default 268435456 = 256 MB)",     "268435456"),
    ("cpu_seconds",   ["agents", "sandbox", "space", "cpu_seconds"],   "subprocess CPU cap (POSIX only)",        "30"),
    ("output_cap",    ["agents", "sandbox", "space", "output_cap"],    "max characters saved to run output",     "65536"),
    ("max_web_calls", ["agents", "sandbox", "space", "max_web_calls"], "web search calls allowed per run",      "10"),
]


def _section_agent_sandbox(toml_data: dict) -> bool:
    """
    Configure sandbox resource limits for system agents and space agents separately.

    System agents (global scope): scheduled digests, web monitors, personal automations.
    Space agents  (space scope):  learning assistants, workspace analysers, project agents.

    Resolution order applied at runtime:
      per-agent SandboxPolicy > [agents.sandbox.<type>] (this section) > hardcoded defaults

    See sandbox/config.py: _load_sandbox_cfg_overrides, build_sandbox_config.
    """
    toml_dirty = False

    while True:
        hdr("Agent Sandbox")
        dim("System agents = global scope (digests, monitors).")
        dim("Space agents  = space scope (learning assistants, workspace tools).")
        dim("Per-agent SandboxPolicy overrides these. Hardcoded defaults apply when unset.")

        sys_enabled   = _gv(toml_data, ["agents", "sandbox", "system", "enabled"], "true")
        space_enabled = _gv(toml_data, ["agents", "sandbox", "space",  "enabled"], "true")
        sys_timeout   = _gv(toml_data, ["agents", "sandbox", "system", "wall_timeout"], "120")
        space_timeout = _gv(toml_data, ["agents", "sandbox", "space",  "wall_timeout"], "300")

        choices = [
            questionary.Choice(
                f"  System agents  [sandbox: {'on' if sys_enabled != 'false' else 'OFF'}, timeout: {sys_timeout}s]",
                value="system",
            ),
            questionary.Choice(
                f"  Space agents   [sandbox: {'on' if space_enabled != 'false' else 'OFF'}, timeout: {space_timeout}s]",
                value="space",
            ),
            questionary.Separator(),
            questionary.Choice("  <- Back", value="__back__"),
        ]

        sel = q_select("Agent class", choices=choices, style=_STYLE, pointer=_POINTER).ask()
        if sel in (None, "__back__"):
            break

        params = _SANDBOX_SYSTEM_PARAMS if sel == "system" else _SANDBOX_SPACE_PARAMS
        label  = "System agent sandbox" if sel == "system" else "Space agent sandbox"
        hdr(label)

        if sel == "system":
            dim("Tighter limits are safe — system agents only need ~/.sarthak_ai access.")
        else:
            dim("Space agents may need longer timeouts for workspace analysis and LLM calls.")
        dim("Set 'enabled = false' only for local development — disables all enforcement.")

        while True:
            param_choices = []
            for plabel, path, _hint, default in params:
                cur = _gv(toml_data, path, default)
                param_choices.append(questionary.Choice(f"  {plabel:<16} [{cur}]", value=plabel))
            param_choices.append(questionary.Separator())
            param_choices.append(questionary.Choice("  <- Back", value="__back__"))

            sel2 = q_select(f"{label} — parameter", choices=param_choices, style=_STYLE, pointer=_POINTER).ask()
            if sel2 in (None, "__back__"):
                break

            entry = next((e for e in params if e[0] == sel2), None)
            if not entry:
                continue
            plabel, path, hint, default = entry
            cur = _gv(toml_data, path, default)
            dim(hint)

            if plabel == "enabled":
                new_val = q_confirm(
                    f"Enable sandbox for {sel} agents?",
                    default=(cur.lower() != "false"),
                    style=_STYLE,
                ).ask()
                if new_val is None:
                    continue
                str_val = str(new_val).lower()
                if str_val != cur.lower():
                    _sv(toml_data, path, str_val)
                    if not new_val:
                        warn("Sandbox disabled — only use in local dev environments.")
                    ok(f"{sel} sandbox enabled -> {new_val}")
                    toml_dirty = True
            else:
                new_val = q_text(plabel, default=cur, style=_STYLE).ask()
                if new_val and new_val != cur:
                    _sv(toml_data, path, new_val)
                    ok(f"{plabel} -> {new_val}")
                    toml_dirty = True

    return toml_dirty


# ── Submenu: Database Backends ───────────────────────────────────────────────

_RELATIONAL_BACKENDS = [
    ("sqlite",   "sqlite_vec default, zero deps — built-in"),
    ("postgres", "PostgreSQL  requires: pip install sarthak[postgres]"),
    ("duckdb",   "DuckDB      requires: pip install sarthak[duckdb]"),
    ("libsql",   "LibSQL/Turso requires: pip install sarthak[libsql]"),
]

_VECTOR_BACKENDS = [
    ("sqlite_vec", "sqlite-vec  default, zero deps — built-in"),
    ("qdrant",     "Qdrant      requires: pip install sarthak[qdrant]"),
    ("chroma",     "Chroma      requires: pip install sarthak[chroma]"),
    ("pgvector",   "pgvector    requires: pip install sarthak[pgvector]"),
    ("lancedb",    "LanceDB     requires: pip install sarthak[lancedb]"),
    ("weaviate",   "Weaviate    requires: pip install sarthak[weaviate]"),
]

# Connection string fields per backend: (label, toml path, hint, is_secret)
_BACKEND_FIELDS: dict[str, list[tuple[str, list[str], str, bool]]] = {
    "postgres": [
        ("URL",       ["storage", "postgres", "url"],       "postgresql+asyncpg://user:pass@host/db", False),
        ("Pool size", ["storage", "postgres", "pool_size"], "2–20",                                   False),
    ],
    "duckdb": [
        ("Path", ["storage", "duckdb", "path"], "~/.sarthak_ai/sarthak.duckdb", False),
    ],
    "libsql": [
        ("URL",        ["storage", "libsql", "url"],        "file://~/.sarthak_ai/sarthak.db or libsql://<db>.turso.io", False),
        ("Auth token", ["storage", "libsql", "auth_token"], "Turso auth token (leave blank for local file)",              True),
    ],
    "qdrant": [
        ("URL",               ["storage", "qdrant", "url"],               "http://localhost:6333",  False),
        ("API key",           ["storage", "qdrant", "api_key"],           "leave blank if no auth", True),
        ("Collection prefix", ["storage", "qdrant", "collection_prefix"], "sarthak",                False),
    ],
    "chroma": [
        ("Persist dir", ["storage", "chroma", "persist_directory"], "~/.sarthak_ai/chroma", False),
        ("Host",        ["storage", "chroma", "host"],               "blank = local client",  False),
        ("Port",        ["storage", "chroma", "port"],               "8000",                  False),
    ],
    "pgvector": [
        ("URL",          ["storage", "postgres", "url"],          "postgresql+asyncpg://user:pass@host/db", False),
        ("Table prefix", ["storage", "pgvector", "table_prefix"], "sarthak",                              False),
    ],
    "lancedb": [
        ("URI", ["storage", "lancedb", "uri"], "~/.sarthak_ai/lancedb  or  s3://bucket/path", False),
    ],
    "weaviate": [
        ("URL",       ["storage", "weaviate", "url"],       "http://localhost:8080", False),
        ("API key",   ["storage", "weaviate", "api_key"],   "leave blank if no auth", True),
        ("gRPC port", ["storage", "weaviate", "grpc_port"], "50051",                  False),
    ],
}

_REDIS_FIELDS: list[tuple[str, list[str], str, bool]] = [
    ("URL",         ["storage", "redis", "url"],         "redis://localhost:6379/0  — blank = in-process LRU", False),
    ("Default TTL", ["storage", "redis", "default_ttl"], "seconds (default 300)",                              False),
]


def _section_database(toml_data: dict, secrets_data: dict) -> tuple[bool, bool]:
    """Configure relational backend, vector backend, and cache. Returns (toml_dirty, secrets_dirty)."""
    toml_dirty = False
    secrets_dirty = False

    while True:
        cur_db  = _gv(toml_data, ["storage", "backend"],        "sqlite")
        cur_vec = _gv(toml_data, ["storage", "vector_backend"], "sqlite_vec")
        cur_redis = _gv(toml_data, ["storage", "redis", "url"], "")
        cache_label = "redis" if cur_redis else "lru (in-process)"

        hdr("Database Backends")
        dim("Defaults (sqlite + sqlite_vec) need no extra packages.")
        dim("Other backends require: pip install sarthak[<extra>]")

        choices = [
            questionary.Choice(f"  Relational DB   [{cur_db}]",   value="relational"),
            questionary.Choice(f"  Vector / RAG    [{cur_vec}]",  value="vector"),
            questionary.Choice(f"  Cache           [{cache_label}]", value="cache"),
            questionary.Separator(),
            questionary.Choice("  <- Back", value="__back__"),
        ]
        sel = q_select("Select backend type", choices=choices, style=_STYLE, pointer=_POINTER).ask()
        if sel in (None, "__back__"):
            break

        # ── Relational ──────────────────────────────────────────────────────
        if sel == "relational":
            hdr("Relational Backend")
            backend_choices = [
                questionary.Choice(f"  {name:<12} — {desc}", value=name)
                for name, desc in _RELATIONAL_BACKENDS
            ] + [questionary.Choice("  <- Back", value="__back__")]

            new_db = q_select(
                "Backend", choices=backend_choices,
                default=cur_db, style=_STYLE, pointer=_POINTER,
            ).ask()
            if new_db in (None, "__back__"):
                continue

            if new_db != cur_db:
                _sv(toml_data, ["storage", "backend"], new_db)
                toml_dirty = True
                ok(f"Relational backend → {new_db}")

            # Configure connection fields for non-sqlite backends
            fields = _BACKEND_FIELDS.get(new_db, [])
            for label, path, hint, is_secret in fields:
                cur_val = _get_secret(toml_data, path) if is_secret else _gv(toml_data, path, "")
                dim(hint)
                val = (q_secret if is_secret else q_text)(label, default=cur_val, style=_STYLE).ask()
                if val and val != cur_val:
                    if is_secret:
                        _set_secret(toml_data, path, val)
                    else:
                        _sv(toml_data, path, val)
                    toml_dirty = True
                    ok(f"{label} set")

        # ── Vector ──────────────────────────────────────────────────────────
        elif sel == "vector":
            hdr("Vector / RAG Backend")
            vec_choices = [
                questionary.Choice(f"  {name:<12} — {desc}", value=name)
                for name, desc in _VECTOR_BACKENDS
            ] + [questionary.Choice("  <- Back", value="__back__")]

            new_vec = q_select(
                "Backend", choices=vec_choices,
                default=cur_vec, style=_STYLE, pointer=_POINTER,
            ).ask()
            if new_vec in (None, "__back__"):
                continue

            if new_vec != cur_vec:
                _sv(toml_data, ["storage", "vector_backend"], new_vec)
                toml_dirty = True
                ok(f"Vector backend → {new_vec}")
                if new_vec != "sqlite_vec":
                    warn("Re-index your spaces after switching vector backends.")

            fields = _BACKEND_FIELDS.get(new_vec, [])
            for label, path, hint, is_secret in fields:
                cur_val = _get_secret(toml_data, path) if is_secret else _gv(toml_data, path, "")
                dim(hint)
                val = (q_secret if is_secret else q_text)(label, default=cur_val, style=_STYLE).ask()
                if val and val != cur_val:
                    if is_secret:
                        _set_secret(toml_data, path, val)
                    else:
                        _sv(toml_data, path, val)
                    toml_dirty = True
                    ok(f"{label} set")

        # ── Cache ────────────────────────────────────────────────────────────
        elif sel == "cache":
            hdr("Cache Backend")
            dim("Leave Redis URL blank to use fast in-process LRU (default, no deps).")
            dim("Set Redis URL to share cache across processes or workers.")
            for label, path, hint, is_secret in _REDIS_FIELDS:
                cur_val = _gv(toml_data, path, "")
                dim(hint)
                val = q_text(label, default=cur_val, style=_STYLE).ask()
                if val is not None and val != cur_val:
                    _sv(toml_data, path, val)
                    toml_dirty = True
                    ok(f"{label} → {val or '(cleared — using LRU)'}")

    return toml_dirty, secrets_dirty


# ── Submenu: Health Check ─────────────────────────────────────────────────────

def _section_health(toml_data: dict) -> None:
    """Run live health checks: system tools, DB, LLM, daemon status."""
    hdr("Health Check")

    info("System tools...")
    tools_desc = {
        "glow":       "markdown rendering in TUI",
        "ollama":     "local LLM inference",
    }
    for tool, present in _check_system_tools().items():
        if present:
            ok(f"{tool:<14} {tools_desc.get(tool, '')}")
        else:
            warn(f"{tool:<14} not found  ({tools_desc.get(tool, 'optional')})")

    info("\nLLM API...")
    prov  = _gv(toml_data, ["ai", "default_provider"], "ollama")
    model = _gv(toml_data, ["ai", "default_model"],    "gemma3:4b")
    try:
        from sarthak.core.config import load_config
        cfg = load_config()
        dim(f"  Calling {prov}/{model}...")
        passed, msg = _test_llm_api(prov, model, cfg)
        (ok if passed else err)(f"{prov}/{model}: {msg}")
    except Exception as e:
        warn(f"No API key for '{prov}' — {str(e)[:60]}")

    info("\nOrchestrator service...")
    try:
        if sys.platform.startswith("linux"):
            result = subprocess.run(
                ["systemctl", "--user", "is-active", "sarthak-orchestrator"],
                capture_output=True, text=True, timeout=3,
            )
            state = result.stdout.strip()
            (ok if state == "active" else warn)(f"sarthak-orchestrator: {state}")
        elif sys.platform == "darwin":
            result = subprocess.run(
                ["launchctl", "list", "com.sarthak.orchestrator"],
                capture_output=True, text=True, timeout=3,
            )
            state = "active" if result.returncode == 0 else "inactive"
            (ok if state == "active" else warn)(f"com.sarthak.orchestrator: {state}")
        elif sys.platform == "win32":
            result = subprocess.run(
                ["schtasks", "/Query", "/TN", "SarthakOrchestrator", "/FO", "LIST"],
                capture_output=True, text=True, timeout=5, shell=True,
            )
            state = "active" if result.returncode == 0 else "not found"
            (ok if state == "active" else warn)(f"SarthakOrchestrator (Task Scheduler): {state}")
        else:
            warn("Service check not supported on this platform")
    except Exception as e:
        warn(f"Service check unavailable: {e}")

    q_press("\n  Press any key to return...").ask()


# ── Submenu: Quick Presets ────────────────────────────────────────────────────

_PRESETS: dict[str, dict] = {
    "local":  {"provider": "ollama",  "model": "qwen2.5:7b"},
    "best":   {"provider": "openai",  "model": "gpt-4o"},
    "budget": {"provider": "groq",    "model": "llama-3.1-8b-instant"},
}


def _section_presets(toml_data: dict) -> bool:
    """Apply a quick-start preset. Only overwrites if user explicitly confirms. Returns toml_dirty."""
    hdr("Quick-start Presets")
    dim("Applies sensible defaults. Existing settings are preserved unless you confirm overwrite.")

    choices = [
        questionary.Choice("  local   — Ollama (qwen2.5 + llava, no API)",  value="local"),
        questionary.Choice("  best    — OpenAI gpt-4o (best quality)",      value="best"),
        questionary.Choice("  budget  — Groq llama (fast + cheap API)",     value="budget"),
        questionary.Separator(),
        questionary.Choice("  <- Back",                                      value="__back__"),
    ]

    sel = q_select("Preset", choices=choices, style=_STYLE, pointer=_POINTER).ask()
    if sel in (None, "__back__"):
        return False

    cur_prov  = _gv(toml_data, ["ai", "default_provider"], "")
    cur_model = _gv(toml_data, ["ai", "default_model"],    "")

    # Only prompt for overwrite if something is already set
    if cur_prov and cur_model:
        overwrite = q_confirm(
            f"Current config: {cur_prov}/{cur_model}. Overwrite with preset '{sel}'?",
            default=False,
            style=_STYLE,
        ).ask()
        if not overwrite:
            info("Preset skipped — existing config preserved.")
            return False

    cfg = _PRESETS[sel]
    _sv(toml_data, ["ai", "default_provider"], cfg["provider"])
    _sv(toml_data, ["ai", "default_model"],    cfg["model"])

    ok(f"Preset '{sel}' applied: {cfg['provider']}/{cfg['model']}")
    return True


# ── Submenu: Export / Import ──────────────────────────────────────────────────

def _section_export_import(toml_data: dict, secrets_data: dict) -> bool:
    """Export config to / import from a portable JSON file. Returns toml_dirty."""
    hdr("Export / Import Config")

    choices = [
        questionary.Choice("  Export — save current config to file", value="export"),
        questionary.Choice("  Import — load config from file",       value="import"),
        questionary.Separator(),
        questionary.Choice("  <- Back",                               value="__back__"),
    ]
    sel = q_select("Action", choices=choices, style=_STYLE, pointer=_POINTER).ask()
    if sel in (None, "__back__"):
        return False

    if sel == "export":
        dest = q_text(
            "Export path",
            default=str(Path.home() / "sarthak_config_backup.json"),
            style=_STYLE,
        ).ask()
        if not dest:
            return False
        try:
            secrets = {}
            for name, path, _hint, _encrypt in _SECRET_FIELDS:
                val = _gv(toml_data, path, "")
                if _encrypt and val:
                    val = "(encrypted)"
                secrets[".".join(path)] = {"label": name, "value": val}

            data = {
                "exported_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                "note": "Encrypted values are masked. Copy config.toml for a full backup.",
                "secrets": secrets,
                "ai":      dict(toml_data.get("ai", {})),
                "general": dict(toml_data.get("general", {})),
                "telegram": dict(toml_data.get("telegram", {})),
            }
            Path(dest).write_text(json.dumps(data, indent=2))
            ok(f"Config exported to {dest}")
            warn("Encrypted values were masked. Re-enter them after import.")
        except Exception as e:
            err(f"Export failed: {e}")
        q_press("  Press any key...").ask()
        return False

    # Import
    src = q_text(
        "Import path",
        default=str(Path.home() / "sarthak_config_backup.json"),
        style=_STYLE,
    ).ask()
    if not src or not Path(src).exists():
        err(f"File not found: {src}")
        q_press("  Press any key...").ask()
        return False
    try:
        data = json.loads(Path(src).read_text())
        imported = 0
        for key, entry in data.get("secrets", {}).items():
            val = entry.get("value") if isinstance(entry, dict) else None
            if val and val != "(encrypted)":
                path = key.split(".")
                field = next((f for f in _SECRET_FIELDS if ".".join(f[1]) == key), None)
                if field and field[3]:
                    _set_secret(toml_data, path, str(val))
                else:
                    _sv(toml_data, path, val)
                imported += 1
        ok(f"Imported {imported} secret(s). Encrypted values require manual re-entry.")

        for section in ("ai", "general", "telegram"):
            if section in data and isinstance(data[section], dict):
                toml_data[section] = tomlkit.table()
                for k, v in data[section].items():
                    toml_data[section][k] = v
    except Exception as e:
        err(f"Import failed: {e}")
    q_press("  Press any key...").ask()
    return True


# ── Main wizard ───────────────────────────────────────────────────────────────

def _init_wizard_state() -> tuple[Path, tomlkit.TOMLDocument, dict]:
    # Ensure ~/.sarthak_ai/ is fully set up (idempotent — no-op if already done)
    from sarthak.core.setup import ensure_bootstrapped
    ensure_bootstrapped()
    config_file = BASE_DIR / "config.toml"

    toml_data = tomlkit.parse(config_file.read_text())
    _ensure_master_key()
    secrets_data = toml_data
    return config_file, toml_data, secrets_data


def _persist_wizard_state(
    config_file: Path,
    toml_data: tomlkit.TOMLDocument,
    secrets_data: dict,
    toml_dirty: bool,
    secrets_dirty: bool,
) -> None:
    saved = []
    if toml_dirty or secrets_dirty:
        config_file.write_text(tomlkit.dumps(toml_data))
        saved.append("config.toml")

    if saved:
        ok(f"Saved: {', '.join(saved)}")
        if sys.platform.startswith("linux"):
            warn("Run: systemctl --user restart sarthak-orchestrator")
        elif sys.platform == "darwin":
            plist = "~/Library/LaunchAgents/com.sarthak.orchestrator.plist"
            warn(f"Run: launchctl unload {plist} && launchctl load {plist}")
        elif sys.platform == "win32":
            warn("Run: schtasks /End /TN SarthakOrchestrator && schtasks /Run /TN SarthakOrchestrator")
        else:
            warn("Restart sarthak-orchestrator to apply changes.")
        return
    dim("No changes made.")


def run_wizard() -> None:
    """Interactive configuration wizard — main entry point."""
    config_file, toml_data, secrets_data = _init_wizard_state()
    toml_dirty = False
    secrets_dirty = False

    click.echo(f"\n{OR}{BD}  Sarthak AI — Configuration{RS}")
    dim(f"config: {config_file}")
    click.echo("")

    # On first configure, prompt tools setup upfront if whisper is missing
    if not _whisper_cli_found():
        warn("[!] Whisper STT is not installed (voice dictation unavailable).")
        ans = questionary.confirm(
            "  Set up Whisper now before continuing?",
            default=True, style=_STYLE,
        ).ask()
        if ans:
            toml_dirty |= _install_whisper_interactive(toml_data)
        click.echo("")

    while True:
        _stale: dict[str, str] = {}
        cur_prov  = _gv(toml_data, ["ai", "default_provider"], "?")
        cur_model = _gv(toml_data, ["ai", "default_model"], "?")
        tg_on     = _gv(toml_data, ["telegram", "enabled"], "false").lower()

        fb1_prov  = _gv(toml_data, ["ai", "fallback", "fallback1_provider"], "")
        fb1_model = _gv(toml_data, ["ai", "fallback", "fallback1_model"], "")
        fb_status = f"{fb1_prov}/{fb1_model}" if fb1_prov else "off"

        embed_model = _gv(toml_data, ["ai", "embeddings", "model"], "")
        embed_label = embed_model.split(":")[-1][:24] if embed_model else "unset"

        vis_prov  = _gv(toml_data, ["ai", "vision", "provider"], "")
        vis_model = _gv(toml_data, ["ai", "vision", "model"], "")
        vis_label = f"{vis_prov}/{vis_model}" if vis_prov and vis_model else "unset"

        main_choices = [
            questionary.Choice(f"  Models & Providers [{cur_prov} / {cur_model}]", value="models"),
            questionary.Choice(f"  Vision Model       [{vis_label}]",              value="vision"),
            questionary.Choice(f"  Embedding Model    [{embed_label}]",             value="embedding"),
            questionary.Choice(f"  Fallback Models    [{fb_status}]",               value="fallback"),
            questionary.Choice(f"  Secrets / Keys",                                 value="keys"),
            questionary.Choice(f"  General / UI",                                   value="general"),
            questionary.Choice(f"  Channels          [tg: {'on' if tg_on == 'true' else 'off'}, wa: {'on' if _gv(toml_data, ['whatsapp', 'enabled'], 'false').lower() == 'true' else 'off'}]", value="channels"),
            questionary.Choice(f"  Tools {'[!] whisper missing' if not _whisper_cli_found() else '[ok]'}", value="tools"),
            questionary.Choice(f"  Database Backends",                               value="database"),
            questionary.Choice(f"  Agent Sandbox",                                   value="sandbox"),
            questionary.Choice(f"  Quick Presets",                                   value="presets"),
            questionary.Choice(f"  Health Check",                                   value="health"),
            questionary.Choice(f"  Export / Import",                                value="export"),
            questionary.Separator(),
            questionary.Choice(f"  Save & Exit",    value="save"),
            questionary.Choice(f"  Discard & Exit", value="discard"),
        ]

        action = q_select(
            "Configure Sarthak AI",
            choices=main_choices,
            style=_STYLE,
            pointer=_POINTER,
        ).ask()

        if action in (None, "discard"):
            warn("Changes discarded.")
            return

        if action == "save":
            break

        if action == "embedding":
            toml_dirty |= _section_embedding(toml_data, secrets_data)
        elif action == "vision":
            vision_toml, vision_secrets = _section_vision(toml_data, secrets_data)
            toml_dirty |= vision_toml
            secrets_dirty |= vision_secrets
        elif action == "fallback":
            toml_dirty |= _section_fallback(toml_data, secrets_data)
        elif action == "models":
            model_toml, model_secrets = _model_selector(
                "AI Model (text / chat)",
                toml_data,
                secrets_data,
                prov_path=["ai", "default_provider"],
                model_path=["ai", "default_model"],
                sync_provider_model=True,
            )
            toml_dirty |= model_toml
            secrets_dirty |= model_secrets
        elif action == "keys":
            _keys_toml, _keys_secrets = _section_api_keys(toml_data, secrets_data)
            toml_dirty |= _keys_toml
            secrets_dirty |= _keys_secrets
        elif action == "general":
            toml_dirty |= _section_general(toml_data)
        elif action == "channels":
            channels_toml, channels_secrets = _section_channels(toml_data, secrets_data)
            toml_dirty |= channels_toml
            secrets_dirty |= channels_secrets
        elif action == "presets":
            toml_dirty |= _section_presets(toml_data)
        elif action == "health":
            _section_health(toml_data)
        elif action == "tools":
            toml_dirty |= _section_tools(toml_data)
        elif action == "database":
            db_toml, db_secrets = _section_database(toml_data, secrets_data)
            toml_dirty |= db_toml
            secrets_dirty |= db_secrets
        elif action == "sandbox":
            toml_dirty |= _section_agent_sandbox(toml_data)
        elif action == "export":
            toml_dirty |= _section_export_import(toml_data, secrets_data)

    # Persist changes
    _persist_wizard_state(config_file, toml_data, secrets_data, toml_dirty, secrets_dirty)


def run_quick_wizard() -> None:
    """Quick configuration wizard — models + embeddings only."""
    config_file, toml_data, secrets_data = _init_wizard_state()
    toml_dirty = False
    secrets_dirty = False

    click.echo(f"\n{OR}{BD}  Sarthak AI — Quick Setup{RS}")
    dim(f"config: {config_file}")
    click.echo("")

    model_toml, model_secrets = _model_selector(
        "AI Model (text / chat)",
        toml_data,
        secrets_data,
        prov_path=["ai", "default_provider"],
        model_path=["ai", "default_model"],
        sync_provider_model=True,
    )
    toml_dirty |= model_toml
    secrets_dirty |= model_secrets

    configure_vision = q_confirm(
        "Configure vision model for OCR/images?",
        default=False,
        style=_STYLE,
    ).ask()
    if configure_vision:
        vision_toml, vision_secrets = _section_vision(toml_data, secrets_data)
        toml_dirty |= vision_toml
        secrets_dirty |= vision_secrets

    toml_dirty |= _section_embedding(toml_data, secrets_data)

    _persist_wizard_state(config_file, toml_data, secrets_data, toml_dirty, secrets_dirty)
