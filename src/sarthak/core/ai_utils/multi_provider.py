"""
Sarthak AI — Multi-Provider Management System
==============================================

Unified interface for managing multiple LLM providers via pydantic-ai.

Design principles:
  - Provider-agnostic: switch by changing one string
  - Builder registry pattern — no if/elif ladder for new providers
  - FallbackModel chain with fast failover (max_retries=0 on clients)
  - Typed error taxonomy with retryable classification
  - Cached agents (stateless), built once per (provider, model, system) key
  - Config: config.toml [ai.<provider>] or env var
"""
from __future__ import annotations

import os
from enum import Enum
from functools import lru_cache
from typing import Any, Callable

import structlog

log = structlog.get_logger(__name__)


# ── Providers ─────────────────────────────────────────────────────────────────

class Provider(str, Enum):
    OPENAI         = "openai"
    ANTHROPIC      = "anthropic"
    GEMINI         = "google-gla"
    GROQ           = "groq"
    OLLAMA         = "ollama"
    OPENROUTER     = "openrouter"
    GITHUB_COPILOT = "github-copilot"
    CUSTOM         = "custom"

    @classmethod
    def from_str(cls, value: str) -> "Provider":
        _ALIASES: dict[str, Provider] = {
            "gemini":         cls.GEMINI,
            "gla":            cls.GEMINI,
            "google":         cls.GEMINI,
            "or":             cls.OPENROUTER,
            "copilot":        cls.GITHUB_COPILOT,
            "github_copilot": cls.GITHUB_COPILOT,
        }
        value = value.strip().lower()
        if value in _ALIASES:
            return _ALIASES[value]
        for member in cls:
            if member.value == value:
                return member
        raise ValueError(
            f"Unknown provider: '{value}'. Supported: {[p.value for p in cls]}"
        )


# ── Default model tables ───────────────────────────────────────────────────────

DEFAULT_MODELS: dict[Provider, str] = {
    Provider.OPENAI:         "gpt-4o",
    Provider.ANTHROPIC:      "claude-sonnet-4-6",
    Provider.GEMINI:         "gemini-2.5-flash",
    Provider.GROQ:           "llama-3.3-70b-versatile",
    Provider.OLLAMA:         "gemma3:4b",
    Provider.OPENROUTER:     "openai/gpt-4o",
    Provider.GITHUB_COPILOT: "gpt-4o",
    Provider.CUSTOM:         "",
}

# Quality-first selection (verified real model IDs as of 2026)
LATEST_MODELS: dict[Provider, str] = {
    Provider.OPENAI:         "gpt-4o",          # update when gpt-5 ships publicly
    Provider.ANTHROPIC:      "claude-opus-4-6",
    Provider.GEMINI:         "gemini-2.5-flash",
    Provider.GROQ:           "llama-3.3-70b-versatile",
    Provider.OLLAMA:         "gemma3:12b",
    Provider.OPENROUTER:     "anthropic/claude-opus-4-6",
    Provider.GITHUB_COPILOT: "claude-opus-4-6",
    Provider.CUSTOM:         "",
}

# Latency-first selection
FAST_MODELS: dict[Provider, str] = {
    Provider.OPENAI:         "gpt-4o-mini",
    Provider.ANTHROPIC:      "claude-haiku-4-5-20251001",
    Provider.GEMINI:         "gemini-2.5-flash",
    Provider.GROQ:           "llama-3.3-70b-versatile",
    Provider.OLLAMA:         "gemma3:4b",
    Provider.OPENROUTER:     "openai/gpt-4o-mini",
    Provider.GITHUB_COPILOT: "gpt-4o-mini",
    Provider.CUSTOM:         "",
}

# Env-var keys (None = no key required, e.g. Ollama)
ENV_KEYS: dict[Provider, str | None] = {
    Provider.OPENAI:         "OPENAI_API_KEY",
    Provider.ANTHROPIC:      "ANTHROPIC_API_KEY",
    Provider.GEMINI:         "GEMINI_API_KEY",
    Provider.GROQ:           "GROQ_API_KEY",
    Provider.OLLAMA:         None,
    Provider.OPENROUTER:     "OPENROUTER_API_KEY",
    Provider.GITHUB_COPILOT: "GITHUB_COPILOT_TOKEN",  # optional; device-flow is preferred
    Provider.CUSTOM:         None,
}

# Map provider → config.toml [ai.<key>] section name
_CONFIG_KEYS: dict[Provider, str] = {
    Provider.OPENAI:         "openai",
    Provider.ANTHROPIC:      "anthropic",
    Provider.GEMINI:         "gemini",
    Provider.GROQ:           "groq",
    Provider.OLLAMA:         "ollama",
    Provider.OPENROUTER:     "openrouter",
    Provider.GITHUB_COPILOT: "github-copilot",
    Provider.CUSTOM:         "custom",
}


# ── Error taxonomy ─────────────────────────────────────────────────────────────

class LLMError(Exception):
    retryable: bool = False

    def __init__(self, message: str, provider: str | None = None, cause: Exception | None = None):
        super().__init__(message)
        self.provider = provider
        self.cause = cause


class AuthenticationError(LLMError):
    retryable = False

class RateLimitError(LLMError):
    retryable = True
    def __init__(self, message: str, retry_after: float | None = None, **kw: Any):
        super().__init__(message, **kw)
        self.retry_after = retry_after

class ServerError(LLMError):
    retryable = True

class ContextLengthError(LLMError):
    retryable = False

class ContentFilterError(LLMError):
    retryable = False

class ConfigurationError(LLMError):
    retryable = False

class NetworkError(LLMError):
    retryable = True


def classify_error(error: Exception, provider: str | None = None) -> LLMError:
    """Translate a pydantic-ai / httpx exception into a typed LLMError."""
    msg = str(error).lower()
    kw: dict[str, Any] = {"provider": provider, "cause": error}
    if "401" in msg or "authentication" in msg or "unauthorized" in msg or "invalid api key" in msg:
        return AuthenticationError(str(error), **kw)
    if "429" in msg or "rate limit" in msg or "rate_limit" in msg:
        return RateLimitError(str(error), **kw)
    if "context length" in msg or "context window" in msg or "too many tokens" in msg or "413" in msg:
        return ContextLengthError(str(error), **kw)
    if "content filter" in msg or "safety" in msg or "moderation" in msg:
        return ContentFilterError(str(error), **kw)
    if any(c in msg for c in ("500", "502", "503", "504", "server error")):
        return ServerError(str(error), **kw)
    if any(c in msg for c in ("connection", "resolve", "network", "timeout")):
        return NetworkError(str(error), **kw)
    return LLMError(str(error), **kw)


# ── Provider config resolver ───────────────────────────────────────────────────

class ProviderConfig:
    """Resolves API keys, base URLs, and models for a provider.

    Priority: config.toml → env var → hard-coded defaults.
    """

    def __init__(self, provider: Provider, cfg: dict[str, Any]) -> None:
        self.provider = provider
        section_key = _CONFIG_KEYS[provider]
        raw = cfg.get("ai", {}).get(section_key, {})
        self._cfg: dict[str, Any] = raw if isinstance(raw, dict) else {}

    @property
    def api_key(self) -> str:
        raw = self._cfg.get("api_key", "")
        if raw:
            return self._decrypt(raw)
        env_key = ENV_KEYS.get(self.provider)
        return os.getenv(env_key, "") if env_key else ""

    @property
    def base_url(self) -> str | None:
        return self._cfg.get("base_url") or None

    @property
    def timeout(self) -> float:
        try:
            return float(self._cfg.get("timeout", 30))
        except (TypeError, ValueError):
            return 30.0

    @property
    def default_model(self) -> str:
        return (
            self._cfg.get("model")
            or self._cfg.get("text_model")
            or DEFAULT_MODELS.get(self.provider, "")
        )

    def is_configured(self) -> bool:
        if ENV_KEYS.get(self.provider) is None:
            return True           # Ollama: no key needed
        return bool(self.api_key)

    @staticmethod
    def _decrypt(value: str) -> str:
        if value.startswith("ENC:"):
            try:
                from sarthak.storage.encrypt import decrypt_string
                return decrypt_string(value)
            except Exception:
                return value
        return value.strip()


# ── Model builder registry ────────────────────────────────────────────────────
# Each builder is a pure function: (ProviderConfig, model_name) → pydantic-ai model.
# Adding a new provider = write one function + one entry in _BUILDERS.

def _build_openai(pc: ProviderConfig, model_name: str) -> Any:
    from openai import AsyncOpenAI
    from pydantic_ai.models.openai import OpenAIChatModel
    from pydantic_ai.providers.openai import OpenAIProvider
    if not pc.api_key:
        raise ConfigurationError(
            "OpenAI API key not set. Set [ai.openai] api_key or OPENAI_API_KEY.",
            provider=pc.provider.value,
        )
    client = AsyncOpenAI(api_key=pc.api_key, max_retries=0, timeout=pc.timeout)
    return OpenAIChatModel(model_name, provider=OpenAIProvider(openai_client=client))


def _build_anthropic(pc: ProviderConfig, model_name: str) -> Any:
    from pydantic_ai.models.anthropic import AnthropicModel
    from pydantic_ai.providers.anthropic import AnthropicProvider
    if not pc.api_key:
        raise ConfigurationError(
            "Anthropic API key not set. Set [ai.anthropic] api_key or ANTHROPIC_API_KEY.",
            provider=pc.provider.value,
        )
    return AnthropicModel(model_name, provider=AnthropicProvider(api_key=pc.api_key))


def _build_gemini(pc: ProviderConfig, model_name: str) -> Any:
    from pydantic_ai.models.gemini import GeminiModel
    from pydantic_ai.providers.google_gla import GoogleGLAProvider
    if not pc.api_key:
        raise ConfigurationError(
            "Gemini API key not set. Set [ai.gemini] api_key or GEMINI_API_KEY.",
            provider=pc.provider.value,
        )
    return GeminiModel(model_name, provider=GoogleGLAProvider(api_key=pc.api_key))


def _build_groq(pc: ProviderConfig, model_name: str) -> Any:
    from groq import AsyncGroq
    from pydantic_ai.models.groq import GroqModel
    from pydantic_ai.providers.groq import GroqProvider
    if not pc.api_key:
        raise ConfigurationError(
            "Groq API key not set. Set [ai.groq] api_key or GROQ_API_KEY.",
            provider=pc.provider.value,
        )
    return GroqModel(model_name, provider=GroqProvider(groq_client=AsyncGroq(api_key=pc.api_key)))


def _build_openai_compat(
    pc: ProviderConfig,
    model_name: str,
    *,
    default_base_url: str,
    strip_openai_prefix: bool = False,
    require_key: bool = True,
    api_key_override: str = "",
) -> Any:
    """Shared builder for all OpenAI-compatible endpoints."""
    from openai import AsyncOpenAI
    from pydantic_ai.models.openai import OpenAIChatModel
    from pydantic_ai.providers.openai import OpenAIProvider

    api_key = api_key_override or pc.api_key
    if require_key and not api_key:
        raise ConfigurationError(
            f"{pc.provider.value} key not set — check config.toml or env var.",
            provider=pc.provider.value,
        )
    base_url = pc.base_url or default_base_url
    if strip_openai_prefix and model_name.startswith("openai/"):
        model_name = model_name.split("/", 1)[1]
    client = AsyncOpenAI(
        base_url=base_url,
        api_key=api_key or "none",
        max_retries=0,
        timeout=pc.timeout,
    )
    return OpenAIChatModel(model_name, provider=OpenAIProvider(openai_client=client))


def _build_custom(pc: ProviderConfig, model_name: str) -> Any:
    """Build a model for a custom OpenAI-compat or Anthropic-compat endpoint.

    Reads [ai.custom] compat, base_url, api_key from config.
    compat = 'openai'    → OpenAIChatModel via _build_openai_compat
    compat = 'anthropic' → AnthropicModel pointed at a custom base_url
    """
    from sarthak.core.config import load_config
    cfg = load_config()
    custom_cfg = cfg.get("ai", {}).get("custom", {})
    compat   = str(custom_cfg.get("compat", "openai")).strip().lower()
    base_url = str(custom_cfg.get("base_url", "")).strip()
    # load_config() already decrypts config.toml values, so api_key is plaintext here
    api_key = str(custom_cfg.get("api_key", "")).strip() or os.getenv("CUSTOM_API_KEY", "")

    if not base_url:
        raise ConfigurationError(
            "Custom provider base_url not set. Run 'sarthak configure' and set it under Custom.",
            provider="custom",
        )

    if compat == "anthropic":
        from anthropic import AsyncAnthropic
        from pydantic_ai.models.anthropic import AnthropicModel
        from pydantic_ai.providers.anthropic import AnthropicProvider
        client = AsyncAnthropic(
            base_url=base_url,
            api_key=api_key or "none",
            max_retries=0,
            timeout=pc.timeout,
        )
        return AnthropicModel(model_name, provider=AnthropicProvider(anthropic_client=client))

    # Default: openai-compat
    return _build_openai_compat(
        pc, model_name,
        default_base_url=base_url,
        require_key=False,
        api_key_override=api_key,
    )


def _build_github_copilot(pc: ProviderConfig, model_name: str) -> Any:
    """Build an OpenAI-compat client for the GitHub Copilot API.

    Token strategy (mirrors OpenClaw):
      1. Try env var GITHUB_COPILOT_TOKEN (direct Copilot JWT — advanced use)
      2. Fall back to device-flow token managed by github_copilot_auth module
    The token is fetched synchronously here (builder is called once at agent
    construction time); the auth module handles caching + refresh internally.
    """
    from openai import AsyncOpenAI
    from pydantic_ai.models.openai import OpenAIChatModel
    from pydantic_ai.providers.openai import OpenAIProvider
    from sarthak.core.ai_utils.github_copilot_auth import (
        get_copilot_token_sync, is_configured,
    )

    # Allow a raw Copilot token via env var for CI/non-interactive use
    token = os.getenv("GITHUB_COPILOT_TOKEN", "").strip()
    if not token:
        if not is_configured():
            raise ConfigurationError(
                "GitHub Copilot not authenticated. Run: sarthak copilot login",
                provider=pc.provider.value,
            )
        token = get_copilot_token_sync()

    base_url = pc.base_url or "https://api.githubcopilot.com"
    client = AsyncOpenAI(
        base_url=base_url,
        api_key=token,
        max_retries=0,
        timeout=pc.timeout,
        default_headers={"Copilot-Integration-Id": "vscode-chat"},
    )
    return OpenAIChatModel(model_name, provider=OpenAIProvider(openai_client=client))


# Registry: Provider → builder callable
_BUILDERS: dict[Provider, Callable[[ProviderConfig, str], Any]] = {
    Provider.OPENAI:    _build_openai,
    Provider.ANTHROPIC: _build_anthropic,
    Provider.GEMINI:    _build_gemini,
    Provider.GROQ:      _build_groq,
    Provider.OLLAMA: lambda pc, m: _build_openai_compat(
        pc, m,
        default_base_url="http://localhost:11434/v1",
        require_key=False,
        api_key_override="ollama",
    ),
    Provider.OPENROUTER: lambda pc, m: _build_openai_compat(
        pc, m,
        default_base_url="https://openrouter.ai/api/v1",
    ),
    Provider.GITHUB_COPILOT: _build_github_copilot,
    Provider.CUSTOM:         _build_custom,
}


def register_provider(
    provider: Provider | str,
    builder: Callable[[ProviderConfig, str], Any],
) -> None:
    """Register or override a provider builder at runtime."""
    resolved = provider if isinstance(provider, Provider) else Provider.from_str(provider)
    _BUILDERS[resolved] = builder


def build_model(provider: Provider, model_name: str, cfg: dict[str, Any]) -> Any:
    """Build a pydantic-ai model object for the given provider + model."""
    builder = _BUILDERS.get(provider)
    if builder is None:
        raise ConfigurationError(f"Unsupported provider: {provider.value}")
    pc = ProviderConfig(provider, cfg)
    return builder(pc, model_name)


# ── Fallback chain ────────────────────────────────────────────────────────────

def build_fallback_chain(
    primary_provider: Provider,
    primary_model: str,
    cfg: dict[str, Any],
) -> Any:
    """Build primary → fallback1 → fallback2 chain from [ai.fallback] config."""
    from pydantic_ai.models.fallback import FallbackModel

    primary = build_model(primary_provider, primary_model, cfg)
    fallback_cfg = cfg.get("ai", {}).get("fallback", {})
    models: list[Any] = [primary]

    for slot in (1, 2):
        fb_provider_str = fallback_cfg.get(f"fallback{slot}_provider", "").strip()
        fb_model = fallback_cfg.get(f"fallback{slot}_model", "").strip()
        if not fb_provider_str or not fb_model:
            continue
        try:
            fb_provider = Provider.from_str(fb_provider_str)
            fb_pc = ProviderConfig(fb_provider, cfg)
            if not fb_pc.is_configured():
                log.warning("fallback_skipped", slot=slot, provider=fb_provider_str,
                            error=f"{fb_provider_str} key not set — check config.toml or env var.")
                continue
            models.append(build_model(fb_provider, fb_model, cfg))
            log.debug("fallback_registered", slot=slot, provider=fb_provider_str, model=fb_model)
        except Exception as exc:
            log.warning("fallback_skipped", slot=slot, provider=fb_provider_str, error=str(exc))

    if len(models) == 1:
        return primary
    return FallbackModel(*models, fallback_on=(Exception,))


# ── Provider registry ──────────────────────────────────────────────────────────

class ProviderRegistry:
    """Discovers and validates configured providers.

    Usage:
        registry = ProviderRegistry.from_config(cfg)
        if registry.is_available(Provider.OPENAI):
            model = registry.build_model(Provider.OPENAI)
    """

    def __init__(self, cfg: dict[str, Any]) -> None:
        self._cfg = cfg
        self._configs: dict[Provider, ProviderConfig] = {
            p: ProviderConfig(p, cfg) for p in Provider
        }

    @classmethod
    def from_config(cls, cfg: dict[str, Any] | None = None) -> "ProviderRegistry":
        if cfg is None:
            from sarthak.core.config import load_config
            cfg = load_config()
        return cls(cfg)

    def is_available(self, provider: Provider) -> bool:
        if provider == Provider.GITHUB_COPILOT:
            from sarthak.core.ai_utils.github_copilot_auth import is_configured as _cop_configured
            return _cop_configured() or bool(os.getenv("GITHUB_COPILOT_TOKEN", ""))
        return self._configs[provider].is_configured()

    def available_providers(self) -> list[Provider]:
        return [p for p in Provider if self.is_available(p)]

    def get_config(self, provider: Provider) -> ProviderConfig:
        return self._configs[provider]

    def build_model(self, provider: Provider, model_name: str | None = None) -> Any:
        pc = self._configs[provider]
        return build_model(provider, model_name or pc.default_model, self._cfg)

    def build_fallback_chain(
        self, primary_provider: Provider, primary_model: str | None = None
    ) -> Any:
        pc = self._configs[primary_provider]
        return build_fallback_chain(
            primary_provider, primary_model or pc.default_model, self._cfg
        )

    def status(self) -> dict[str, bool]:
        return {p.value: self.is_available(p) for p in Provider}


# ── Agent cache ───────────────────────────────────────────────────────────────

@lru_cache(maxsize=32)
def _get_cached_agent(provider_str: str, model_name: str, system: str | None, cfg_hash: int):
    """
    Build and cache a pydantic-ai Agent.

    Keyed on (provider, model, system, cfg_hash) so config changes invalidate
    the cache automatically — no manual invalidation needed.
    """
    from pydantic_ai import Agent
    from sarthak.core.config import load_config

    cfg = load_config()
    provider = Provider.from_str(provider_str)
    model = ProviderRegistry(cfg).build_fallback_chain(provider, model_name)
    kwargs: dict[str, Any] = {"model": model}
    if system:
        kwargs["system_prompt"] = system
    return Agent(**kwargs)


_CFG_HASH_CACHE: tuple[int, int] | None = None  # (id(cfg), hash)


def _cfg_hash(cfg: dict[str, Any]) -> int:
    """Stable hash of the AI section of config to detect key/model changes."""
    import json
    global _CFG_HASH_CACHE
    cfg_id = id(cfg)
    if _CFG_HASH_CACHE and _CFG_HASH_CACHE[0] == cfg_id:
        return _CFG_HASH_CACHE[1]
    ai_section = cfg.get("ai", {})
    try:
        h = hash(json.dumps(ai_section, sort_keys=True, default=str))
    except Exception:
        h = 0
    _CFG_HASH_CACHE = (cfg_id, h)
    return h


def invalidate_agent_cache() -> None:
    """Force rebuild of all cached agents (e.g. after model change)."""
    _get_cached_agent.cache_clear()
    log.debug("agent_cache_invalidated")


# ── call_llm ──────────────────────────────────────────────────────────────────

async def call_llm(
    prompt: str,
    provider: str | None = None,
    model: str | None = None,
    system: str | None = None,
    image_b64: str | None = None,
    max_tokens: int = 1024,
    temperature: float = 0.2,
    cfg: dict[str, Any] | None = None,
) -> str:
    """High-level single-turn LLM call. Returns text or a descriptive error string."""
    if cfg is None:
        from sarthak.core.config import load_config
        cfg = load_config()

    ai_cfg = cfg.get("ai", {})
    provider_str = (
        provider or ai_cfg.get("default_provider", Provider.OLLAMA.value)
    ).strip()
    resolved_provider = Provider.from_str(provider_str)
    pc = ProviderConfig(resolved_provider, cfg)
    model_str = model or pc.default_model or DEFAULT_MODELS[resolved_provider]

    log.debug("llm_call", provider=resolved_provider.value, model=model_str)

    user_content: list[Any] = [prompt]
    if image_b64:
        import base64
        from pydantic_ai import BinaryContent
        user_content.append(
            BinaryContent(data=base64.b64decode(image_b64), media_type="image/png")
        )

    try:
        agent = _get_cached_agent(
            resolved_provider.value, model_str, system, _cfg_hash(cfg)
        )
        result = await agent.run(user_content)
        # pydantic-ai uses .output in recent versions; guard for future changes
        try:
            return result.output
        except AttributeError:
            return result.data

    except Exception as raw_exc:
        typed_err = classify_error(raw_exc, provider=resolved_provider.value)
        log.error(
            "llm_error",
            provider=resolved_provider.value,
            model=model_str,
            error_type=type(typed_err).__name__,
            error=str(typed_err),
        )
        _error_msgs: dict[type, str] = {
            AuthenticationError: f"[Error: Authentication failed for {resolved_provider.value}. Check your API key.]",
            RateLimitError:      f"[Error: Rate limit exceeded for {resolved_provider.value}. Try again later.]",
            ContextLengthError:  f"[Error: Input too large for {model_str}. Reduce prompt length.]",
            ContentFilterError:  f"[Error: Content filtered by {resolved_provider.value}.]",
            ConfigurationError:  f"[Error: {resolved_provider.value} not configured. Run 'sarthak configure'.]",
            NetworkError:        f"[Error: Network failure connecting to {resolved_provider.value}. Check connectivity.]",
        }
        return _error_msgs.get(type(typed_err),
               f"[Error: LLM failure ({resolved_provider.value}/{model_str}): {typed_err}]")


# ── Legacy helpers (moved from providers.py) ─────────────────────────────────

def normalize_model_name(provider: str, model_name: str) -> str:
    return model_name


def build_pydantic_model(provider: str, model_name: str, cfg: dict | None = None):
    """Build a pydantic-ai model object."""
    if cfg is None:
        from sarthak.core.config import load_config
        cfg = load_config()
    p = Provider.from_str(provider)
    model_name = normalize_model_name(provider, model_name)
    return build_model(p, model_name, cfg)


def build_fallback_model(provider: str, model_name: str, cfg: dict | None = None):
    """Build a FallbackModel chain."""
    if cfg is None:
        from sarthak.core.config import load_config
        cfg = load_config()
    p = Provider.from_str(provider)
    model_name = normalize_model_name(provider, model_name)
    return build_fallback_chain(p, model_name, cfg)


def build_openai_client() -> tuple[Any, str]:
    """
    Return (openai.OpenAI-compatible client, model_name) for use with MarkItDown vision.

    Reads the vision model from config (ai.vision.model or ai.openai.model).
    Raises ConfigurationError if no vision-capable provider is configured.
    """
    from sarthak.core.config import load_config
    import openai

    cfg   = load_config()
    ai    = cfg.get("ai", {})
    # Prefer explicit vision config, fall back to general OpenAI
    model = (
        ai.get("vision", {}).get("model")
        or ai.get("openai", {}).get("model")
        or "gpt-4o"
    )
    api_key  = ai.get("vision", {}).get("api_key") or ai.get("openai", {}).get("api_key") or os.environ.get("OPENAI_API_KEY", "")
    base_url = ai.get("vision", {}).get("base_url") or ai.get("openai", {}).get("base_url") or None
    if not api_key:
        raise ConfigurationError("Vision LLM not configured. Set [ai.openai] api_key in config.toml.")
    client = openai.OpenAI(api_key=api_key, base_url=base_url) if base_url else openai.OpenAI(api_key=api_key)
    return client, model


# ── Model tier resolution ─────────────────────────────────────────────────────

def resolve_model_for_tier(
    provider: str,
    tier: "str",  # ModelTier = "fast" | "balanced" | "powerful"
    cfg: dict[str, Any] | None = None,
) -> str:
    """
    Return the correct model name for a given quality/speed tier.

    Resolution order:
      1. config.toml [ai.<provider>.fast_model / balanced_model / powerful_model]
      2. Hard-coded tier tables (FAST_MODELS / DEFAULT_MODELS / LATEST_MODELS)

    Strategy 2 — Model Routing by Task Complexity.
    """
    if cfg is None:
        from sarthak.core.config import load_config
        cfg = load_config()
    p = Provider.from_str(provider)
    ai = cfg.get("ai", {})
    section_key = _CONFIG_KEYS.get(p, p.value)
    provider_cfg = ai.get(section_key, {})
    if not isinstance(provider_cfg, dict):
        provider_cfg = {}

    tier_key_map = {
        "fast":     "fast_model",
        "balanced": "text_model",
        "powerful": "powerful_model",
    }
    cfg_key = tier_key_map.get(tier, "text_model")
    from_cfg = provider_cfg.get(cfg_key, "").strip()
    if from_cfg:
        return from_cfg

    table_map = {
        "fast":     FAST_MODELS,
        "balanced": DEFAULT_MODELS,
        "powerful": LATEST_MODELS,
    }
    table = table_map.get(tier, DEFAULT_MODELS)
    return table.get(p, DEFAULT_MODELS.get(p, ""))

