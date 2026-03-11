from __future__ import annotations

import os
from pathlib import Path

import tomlkit
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

router = APIRouter()


def _config_path() -> Path:
    env = os.environ.get("SARTHAK_CONFIG", "").strip()
    return Path(env) if env else Path.home() / ".sarthak_ai" / "config.toml"


@router.get("/api/config")
async def get_config() -> dict:
    path = _config_path()
    if not path.exists():
        raise HTTPException(404, "Config not found")
    return {"path": str(path), "content": path.read_text(encoding="utf-8")}


class ConfigSave(BaseModel):
    content: str


@router.put("/api/config")
async def save_config(body: ConfigSave) -> dict:
    try:
        tomlkit.parse(body.content)
    except Exception as exc:
        raise HTTPException(400, f"Invalid TOML: {exc}")
    path = _config_path()
    path.write_text(body.content, encoding="utf-8")
    return {"ok": True, "path": str(path)}
