"""
Sarthak AI — Configuration loader.
Pure function: load_config(path) -> dict. No side effects.

Cross-platform data directory:
  Linux   : ~/.local/share/sarthak  (XDG_DATA_HOME)
  macOS   : ~/Library/Application Support/sarthak
  Windows : %APPDATA%\\sarthak
"""
from __future__ import annotations

import os
import sys
import tomllib
from pathlib import Path
from typing import Any


_PRODUCTION_DIR    = Path.home() / ".sarthak_ai"
_PRODUCTION_CONFIG = _PRODUCTION_DIR / "config.toml"


def _default_data_dir() -> Path:
    if sys.platform == "win32":
        base = Path(os.environ.get("APPDATA", Path.home() / "AppData" / "Roaming"))
        return base / "sarthak"
    if sys.platform == "darwin":
        return Path.home() / "Library" / "Application Support" / "sarthak"
    # Linux — respect XDG_DATA_HOME
    xdg = os.environ.get("XDG_DATA_HOME", "")
    base = Path(xdg) if xdg else Path.home() / ".local" / "share"
    return base / "sarthak"


def get_config_path(path: str | Path | None = None) -> Path:
    if path:
        return Path(path)
    env = os.environ.get("SARTHAK_CONFIG", "")
    if env:
        return Path(env)
    return _PRODUCTION_CONFIG


def load_config(path: str | Path | None = None) -> dict[str, Any]:
    """Load config.toml (single source of truth).

    Priority (highest wins):
      1. Explicitly passed path
      2. SARTHAK_CONFIG env var
      3. ~/.sarthak_ai/config.toml

    Returns a nested dict. Callers use cfg[section][key].
    """
    config_path = get_config_path(path)
    if not config_path.exists():
        raise FileNotFoundError(f"Config not found: {config_path}")

    with open(config_path, "rb") as f:
        cfg: dict[str, Any] = tomllib.load(f)

    cfg = _expand_paths(cfg)

    # Fill in a sensible default for data_dir if not set
    general = cfg.setdefault("general", {})
    if not general.get("data_dir"):
        general["data_dir"] = str(_default_data_dir())

    # Merge encrypted secrets (if present)
    secrets_path = config_path.parent / "secrets.toml"
    _merge_into(cfg, _load_secrets(secrets_path))

    return cfg


def _expand_paths(cfg: dict[str, Any]) -> dict[str, Any]:
    """Recursively expand ~ and %USERPROFILE% in all string values."""
    result = {}
    for k, v in cfg.items():
        if isinstance(v, dict):
            result[k] = _expand_paths(v)
        elif isinstance(v, str) and ("~" in v or "%USERPROFILE%" in v):
            result[k] = str(Path(os.path.expanduser(v.replace("%USERPROFILE%", "~"))))
        elif isinstance(v, list):
            result[k] = [
                str(Path(os.path.expanduser(i.replace("%USERPROFILE%", "~"))))
                if isinstance(i, str) and ("~" in i or "%USERPROFILE%" in i)
                else i
                for i in v
            ]
        else:
            result[k] = v
    return result


def _merge_into(base: dict[str, Any], override: dict[str, Any]) -> None:
    """Recursively merge override into base (mutates base)."""
    for key, val in override.items():
        if isinstance(val, dict) and isinstance(base.get(key), dict):
            _merge_into(base[key], val)
        else:
            base[key] = val


def _load_secrets(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    with open(path, "rb") as f:
        data = tomllib.load(f)
    return _decrypt_tree(data)


def _decrypt_tree(value: Any) -> Any:
    if isinstance(value, dict):
        return {k: _decrypt_tree(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_decrypt_tree(v) for v in value]
    if isinstance(value, str) and value.startswith("ENC:"):
        from sarthak.storage.encrypt import decrypt_string
        return decrypt_string(value)
    return value


def get_encryption_key(cfg: dict[str, Any]) -> str:  # noqa: ARG001
    from sarthak.storage.encrypt import get_master_key_b64
    return get_master_key_b64()


def get_hyprland_socket() -> str:
    """Return path to Hyprland socket2 for the current session.

    Raises RuntimeError if not running under Hyprland or not on Linux.
    """
    if sys.platform != "linux":
        raise RuntimeError("Hyprland is only available on Linux")
    sig = os.environ.get("HYPRLAND_INSTANCE_SIGNATURE")
    if not sig:
        raise RuntimeError(
            "HYPRLAND_INSTANCE_SIGNATURE not set — is Hyprland running?"
        )
    xdg_runtime = os.environ.get("XDG_RUNTIME_DIR", f"/run/user/{os.getuid()}")
    return f"{xdg_runtime}/hypr/{sig}/.socket2.sock"


def ensure_data_dir(cfg: dict[str, Any]) -> Path:
    """Create data directory (and subdirs) if needed, return Path."""
    d = Path(cfg["general"]["data_dir"])
    d.mkdir(parents=True, exist_ok=True)
    (d / "logs").mkdir(exist_ok=True)
    (d / "cache").mkdir(exist_ok=True)
    return d
