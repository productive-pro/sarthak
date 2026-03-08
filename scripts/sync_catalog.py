from __future__ import annotations

import os
from pathlib import Path
import re
import subprocess

import httpx
import json


ROOT = Path(__file__).resolve().parents[1]
CATALOG = ROOT / "providers.json"


def _capabilities_from_openrouter(model: dict) -> list[str]:
    caps = {"text"}
    arch = model.get("architecture", {})
    input_mods = set(arch.get("input_modalities", []) or [])
    if "image" in input_mods:
        caps.add("vision")
    if "audio" in input_mods:
        caps.add("audio")
    supported = set(model.get("supported_parameters", []) or [])
    if "tools" in supported:
        caps.add("tools")
    if "reasoning" in model.get("tags", []):
        caps.add("reasoning")
    return sorted(caps)


def _write_json(path: Path, data: dict) -> None:
    path.write_text(json.dumps(data, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _capabilities_from_aimlapi(features: list[str]) -> list[str]:
    caps: set[str] = set()
    features_set = set(features)

    # Map AIMLAPI features to our capability system
    if any("vision" in f for f in features_set):
        caps.add("vision")
    if any("function" in f or "tool" in f for f in features_set):
        caps.add("tools")
    if any("audio" in f for f in features_set):
        caps.add("audio")
    if any("code" in f for f in features_set):
        caps.add("code")
    if any("reasoning" in f or "thinking" in f for f in features_set):
        caps.add("reasoning")
    if any("embed" in f for f in features_set):
        caps.add("embedding")

    return sorted(caps)


def _tier_from_openrouter(model: dict) -> str:
    pricing = model.get("pricing") or {}
    try:
        prompt = float(pricing.get("prompt", "0") or 0)
        completion = float(pricing.get("completion", "0") or 0)
    except Exception:
        return "unknown"
    if prompt == 0.0 and completion == 0.0:
        return "free"
    return "paid"


def _merge_models(existing: list[dict], incoming: list[dict]) -> list[dict]:
    existing_map = {m.get("id", ""): m for m in existing}
    merged: list[dict] = []
    for item in incoming:
        mid = item.get("id", "")
        if not mid:
            continue
        if mid in existing_map:
            merged.append(existing_map[mid])
        else:
            merged.append(item)
    incoming_ids = {m.get("id", "") for m in incoming}
    for m in existing:
        if m.get("id", "") not in incoming_ids:
            merged.append(m)
    return merged


def _sync_openrouter(doc: dict) -> None:
    token = os.getenv("OPENROUTER_API_KEY", "").strip()
    if not token:
        return
    headers = {"Authorization": f"Bearer {token}"}
    with httpx.Client(timeout=15, headers=headers) as client:
        resp = client.get("https://openrouter.ai/api/v1/models/user")
        resp.raise_for_status()
        data = resp.json()

    models = []
    for m in data.get("data", []):
        model_id = m.get("id") or ""
        if not model_id:
            continue
        models.append(
            {
                "id": model_id,
                "name": m.get("name", model_id),
                "context_window": int(m.get("context_length") or 0),
                "capabilities": _capabilities_from_openrouter(m),
                "tier": _tier_from_openrouter(m),
                "speed": "unknown",
                "notes": "",
                "pricing": m.get("pricing") or {},
                "architecture": m.get("architecture") or {},
                "supported_parameters": m.get("supported_parameters") or [],
                "tags": m.get("tags") or [],
            }
        )

    current = doc["providers"]["openrouter"].get("models", [])
    doc["providers"]["openrouter"]["models"] = _merge_models(current, models)


def _sync_aimlapi(doc: dict) -> None:
    # https://api.aimlapi.com/models is a public endpoint — no API key required.
    # Optionally attach key for authenticated rate limits.
    api_key = os.getenv("AIMLAPI_API_KEY", "").strip()
    headers = {"Authorization": f"Bearer {api_key}"} if api_key else {}
    with httpx.Client(timeout=30, headers=headers) as client:
        resp = client.get("https://api.aimlapi.com/models")
        resp.raise_for_status()
        data = resp.json()

    models = []
    for m in data.get("data", []):
        model_id = m.get("id") or ""
        if not model_id:
            continue

        info = m.get("info", {})
        features = m.get("features", [])
        endpoints = m.get("endpoints", [])
        model_type = m.get("type", "")

        caps = _capabilities_from_aimlapi(features)

        if "openai/chat-completion.reasoning" in features:
            caps_set = set(caps)
            caps_set.add("reasoning")
            caps = sorted(caps_set)

        model_type_lower = str(model_type).lower()
        if "embedding" in model_type_lower:
            caps_set = set(caps)
            caps_set.add("embedding")
            caps = sorted(caps_set)
        if "chat" in model_type_lower or "completion" in model_type_lower:
            caps_set = set(caps)
            caps_set.add("text")
            caps = sorted(caps_set)

        # Estimate speed from model name
        name_lower = model_id.lower()
        if any(kw in name_lower for kw in ("mini", "small", "flash", "fast", "haiku")):
            speed = "fast"
        elif any(kw in name_lower for kw in ("large", "ultra", "opus", "405b")):
            speed = "slow"
        else:
            speed = "medium"

        models.append(
            {
                "id": model_id,
                "name": info.get("name", model_id),
                "context_window": int(info.get("contextLength") or 0),
                "capabilities": caps,
                "tier": "paid",
                "speed": speed,
                "notes": info.get("developer", ""),
                "features": features,
                "type": model_type,
                "info": info,
                "endpoints": endpoints,
            }
        )

    current = doc["providers"]["aimlapi"].get("models", [])
    doc["providers"]["aimlapi"]["models"] = _merge_models(current, models)


def _sync_github_copilot(doc: dict) -> None:
    """Sync the GitHub Copilot model catalog.

    The /models endpoint requires the oauth_token (not a PAT) obtained from
    ~/.config/github-copilot/apps.json after JetBrains/VSCode Copilot sign-in,
    plus the 'Copilot-Integration-Id: vscode-chat' header.
    """
    import json as _json
    from pathlib import Path as _Path

    def _read_token() -> str:
        t = os.getenv("GITHUB_COPILOT_TOKEN", "").strip()
        if t:
            return t
        for path in [
            _Path.home() / ".config" / "github-copilot" / "apps.json",
            _Path.home() / ".config" / "github-copilot" / "hosts.json",
        ]:
            if not path.exists():
                continue
            try:
                data = _json.loads(path.read_text(encoding="utf-8"))
                for entry in data.values():
                    if isinstance(entry, dict) and entry.get("oauth_token"):
                        return entry["oauth_token"]
            except Exception:
                continue
        return os.getenv("GITHUB_TOKEN", "").strip()

    token = _read_token()
    if not token:
        return

    headers = {
        "Authorization": f"Bearer {token}",
        "Copilot-Integration-Id": "vscode-chat",
        "editor-version": "vscode/1.96.0",
        "editor-plugin-version": "copilot-chat/0.23.2",
        "Content-Type": "application/json",
    }
    with httpx.Client(timeout=15, headers=headers) as client:
        resp = client.get("https://api.githubcopilot.com/models")
        if resp.status_code != 200:
            return
        data = resp.json()

    models = []
    for m in data.get("data", []):
        model_id = m.get("id") or ""
        if not model_id:
            continue
        caps = ["text"]
        if m.get("capabilities", {}).get("supports", {}).get("tool_calls"):
            caps.append("tools")
        if m.get("capabilities", {}).get("supports", {}).get("vision"):
            caps.append("vision")
        models.append(
            {
                "id": model_id,
                "name": m.get("name", model_id),
                "context_window": int(
                    (m.get("capabilities", {}).get("limits") or {}).get("max_context_window_tokens") or 0
                ),
                "capabilities": sorted(set(caps)),
                "tier": "free",
                "speed": "unknown",
                "notes": m.get("vendor", ""),
            }
        )

    current = doc["providers"]["github-copilot"].get("models", [])
    doc["providers"]["github-copilot"]["models"] = _merge_models(current, models)


def _sync_openai_compat(doc: dict, provider: str, base_url: str, env_key: str) -> None:
    token = os.getenv(env_key, "").strip()
    if not token:
        return
    url = base_url.rstrip("/") + "/models"
    headers = {"Authorization": f"Bearer {token}"}
    with httpx.Client(timeout=15, headers=headers) as client:
        resp = client.get(url)
        resp.raise_for_status()
        data = resp.json()

    models = []
    for m in data.get("data", []):
        model_id = m.get("id") or ""
        if not model_id:
            continue
        models.append(
            {
                "id": model_id,
                "name": model_id,
                "context_window": 0,
                "capabilities": ["text"],
                "tier": "unknown",
                "speed": "unknown",
                "notes": "",
                "owned_by": m.get("owned_by", ""),
                "created": m.get("created", 0),
            }
        )

    current = doc["providers"][provider].get("models", [])
    doc["providers"][provider]["models"] = _merge_models(current, models)


def _is_embedding(model_id: str) -> bool:
    """Heuristic: detect embedding/reranker models by ID pattern."""
    lm = model_id.lower()
    return any(kw in lm for kw in ("embed", "embedding", "rerank", "e5-", "bge-", "minilm"))


def _parse_ollama_show(text: str) -> dict:
    section = ""
    model: dict[str, str] = {}
    params: dict[str, str] = {}
    caps: list[str] = []
    license_lines: list[str] = []

    for raw_line in text.splitlines():
        line = raw_line.strip()
        if not line:
            continue
        if line in ("Model", "Capabilities", "Parameters", "License"):
            section = line.lower()
            continue
        if section == "capabilities":
            caps.append(line)
            continue
        if section == "license":
            license_lines.append(line)
            continue
        if section in ("model", "parameters"):
            parts = re.split(r"\s{2,}", line, maxsplit=1)
            if len(parts) != 2:
                continue
            key = parts[0].strip().lower().replace(" ", "_")
            value = parts[1].strip()
            if section == "model":
                model[key] = value
            if section == "parameters":
                params[key] = value

    return {
        "model": model,
        "capabilities": caps,
        "parameters": params,
        "license": license_lines,
    }


def _ollama_show(model_id: str) -> dict:
    result = subprocess.run(
        ["ollama", "show", model_id],
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode != 0:
        return {}
    return _parse_ollama_show(result.stdout)


def _ollama_capabilities_from_show(show: dict) -> list[str]:
    caps = set()
    raw_caps = show.get("capabilities", [])
    for c in raw_caps:
        cl = str(c).strip().lower()
        if cl == "completion":
            caps.add("text")
        if cl == "vision":
            caps.add("vision")
        if cl == "tools":
            caps.add("tools")
        if cl == "thinking":
            caps.add("reasoning")
        if cl == "embedding":
            caps.add("embedding")
    return sorted(caps)


def _digits(value: str) -> int:
    digits = re.sub(r"[^\d]", "", value or "")
    if not digits:
        return 0
    return int(digits)


def _sync_openai(doc: dict) -> None:
    token = os.getenv("OPENAI_API_KEY", "").strip()
    if not token:
        return
    headers = {"Authorization": f"Bearer {token}"}
    with httpx.Client(timeout=15, headers=headers) as client:
        resp = client.get("https://api.openai.com/v1/models")
        resp.raise_for_status()
        data = resp.json()

    models = []
    for m in data.get("data", []):
        model_id = m.get("id") or ""
        if not model_id:
            continue
        caps = ["embedding"] if _is_embedding(model_id) else ["text"]
        models.append(
            {
                "id": model_id,
                "name": model_id,
                "context_window": 0,
                "capabilities": caps,
                "tier": "unknown",
                "speed": "unknown",
                "notes": "",
                "owned_by": m.get("owned_by", ""),
                "created": m.get("created", 0),
            }
        )

    current = doc["providers"]["openai"].get("models", [])
    doc["providers"]["openai"]["models"] = _merge_models(current, models)


def _sync_ollama(doc: dict) -> None:
    base = doc["providers"]["ollama"].get("base_url", "http://localhost:11434/v1")
    base = base.replace("/v1", "")
    url = base.rstrip("/") + "/api/tags"
    with httpx.Client(timeout=5) as client:
        resp = client.get(url)
        if resp.status_code != 200:
            return
        data = resp.json()

    models = []
    for m in data.get("models", []):
        model_id = m.get("name") or ""
        if not model_id:
            continue
        show = _ollama_show(model_id)
        caps = _ollama_capabilities_from_show(show)
        if not caps and _is_embedding(model_id):
            caps = ["embedding"]
        if not caps:
            caps = ["text"]
        show_model = show.get("model", {}) if isinstance(show, dict) else {}
        context_window = _digits(str(show_model.get("context_length", "")))
        embedding_length = _digits(str(show_model.get("embedding_length", "")))
        models.append(
            {
                "id": model_id,
                "name": model_id,
                "context_window": context_window,
                "capabilities": caps,
                "tier": "free",
                "speed": "unknown",
                "notes": "",
                "details": m.get("details", {}),
                "size": m.get("size", 0),
                "digest": m.get("digest", ""),
                "ollama_show": show,
                "embedding_length": embedding_length,
            }
        )

    current = doc["providers"]["ollama"].get("models", [])
    doc["providers"]["ollama"]["models"] = _merge_models(current, models)


def main() -> None:
    if not CATALOG.exists():
        raise SystemExit("providers.json not found")

    doc = json.loads(CATALOG.read_text(encoding="utf-8"))

    _sync_openrouter(doc)
    _sync_openai(doc)
    _sync_aimlapi(doc)
    _sync_github_copilot(doc)

    for provider, pdata in doc.get("providers", {}).items():
        kind = str(pdata.get("kind", ""))
        base_url = str(pdata.get("base_url", "")).strip()
        env_key = str(pdata.get("env_key", "")).strip()
        if kind != "openai-compat":
            continue
        if provider in ("openrouter", "ollama", "aimlapi", "github-copilot"):
            continue
        if not base_url or not env_key:
            continue
        _sync_openai_compat(doc, provider, base_url, env_key)

    _sync_ollama(doc)

    CATALOG.write_text(json.dumps(doc, indent=2, sort_keys=True) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
