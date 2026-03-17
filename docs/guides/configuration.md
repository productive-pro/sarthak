# Configuration

The easiest way to configure Sarthak is through the **Config** page in the web UI at [http://localhost:4848](http://localhost:4848), or by running the setup wizard in the terminal:

```bash
sarthak configure
```

All configuration lives in `~/.sarthak_ai/config.toml`. Sensitive values are stored as encrypted `ENC:...` strings and decrypted at load time — they are never stored in plain text.

---

## AI provider setup

Sarthak supports many AI providers. Pick one to start:

### OpenRouter (free models — recommended for quick start)

1. Sign up at [openrouter.ai](https://openrouter.ai) and copy your API key
2. Encrypt it: `sarthak encrypt "sk-or-v1-yourkey"` — copy the `ENC:...` output
3. Edit `~/.sarthak_ai/config.toml`:

```toml
[ai]
default_provider = "openrouter"
default_model    = "meta-llama/llama-3.1-8b-instruct:free"

[ai.openrouter]
model   = "meta-llama/llama-3.1-8b-instruct:free"
api_key = "ENC:your-encrypted-key"
timeout = 30
```

Free models: `meta-llama/llama-3.1-8b-instruct:free`, `mistralai/mistral-7b-instruct:free`, `google/gemma-2-9b-it:free`

### Ollama (fully local, no key needed)

1. Install from [ollama.com](https://ollama.com) and pull a model: `ollama pull gemma3:4b`

```toml
[ai]
default_provider = "ollama"
default_model    = "gemma3:4b"

[ai.ollama]
base_url   = "http://localhost:11434/v1"
text_model = "gemma3:4b"
```

### OpenAI

```bash
pip install "sarthak[cloud]"
sarthak encrypt "sk-..."    # copy the ENC:... output
```

```toml
[ai]
default_provider = "openai"
default_model    = "gpt-4o-mini"

[ai.openai]
model   = "gpt-4o-mini"
api_key = "ENC:your-encrypted-key"
```

### Anthropic (Claude)

```bash
pip install "sarthak[cloud]"
sarthak encrypt "sk-ant-..."
```

```toml
[ai]
default_provider = "anthropic"
default_model    = "claude-3-5-haiku-20241022"

[ai.anthropic]
model   = "claude-3-5-haiku-20241022"
api_key = "ENC:your-encrypted-key"
```

### Google Gemini

```toml
[ai]
default_provider = "gemini"
default_model    = "gemini-2.0-flash"

[ai.gemini]
model   = "gemini-2.0-flash"
api_key = "ENC:your-encrypted-key"
```

### Groq (fast, generous free tier)

```toml
[ai]
default_provider = "groq"
default_model    = "llama-3.3-70b-versatile"

[ai.groq]
model   = "llama-3.3-70b-versatile"
api_key = "ENC:your-encrypted-key"
```

### GitHub Models / GitHub Copilot

```bash
sarthak copilot login    # device-flow authentication, no manual key needed
```

### Custom OpenAI-compatible endpoint

```toml
[ai.custom]
compat   = "openai"          # openai | anthropic
base_url = "http://localhost:1234/v1"
model    = "your-model-name"
api_key  = "none"            # or ENC:... if required
```

---

## Fallback chain

If your primary model fails (network error, rate limit, etc.), Sarthak automatically tries fallback models. Set up 1–2 fallbacks:

```toml
[ai.fallback]
fallback1_provider = "openrouter"
fallback1_model    = "mistralai/mistral-7b-instruct:free"
fallback2_provider = "ollama"
fallback2_model    = "gemma3:4b"
```

---

## Encrypting secrets

Never store API keys in plain text. Always encrypt first:

```bash
sarthak encrypt "sk-..."
# Output: ENC:abc123...
```

Paste the `ENC:...` value into `config.toml` or the Config page in the web UI.

To decrypt for inspection:

```bash
sarthak decrypt "ENC:..."
```

---

## Telegram notifications

Receive agent outputs and learning digests on your phone:

1. Search **@BotFather** on Telegram → `/newbot` → copy the token
2. Get your chat ID from **@userinfobot** on Telegram
3. Encrypt the token: `sarthak encrypt "1234567890:AAF..."`
4. Edit `config.toml`:

```toml
[telegram]
enabled         = true
bot_token       = "ENC:your-encrypted-token"
allowed_user_id = 123456789
```

Or set it in the **Config** page → Telegram section.

---

## Web UI port

The web UI runs on port 4848 by default. Change it in Config → Web, or directly:

```toml
[web]
host = "127.0.0.1"
port = 4848
```

Restart Sarthak after changing the port.

---

## RAG / document search

By default, Sarthak uses `sqlite-vec` for vector search — embedded, zero extra setup. For production or large indexes you can switch:

```toml
[storage]
vector_backend = "sqlite_vec"   # default, zero deps
# vector_backend = "chroma"     # pip install "sarthak[chroma]"
# vector_backend = "qdrant"     # pip install "sarthak[qdrant]"
# vector_backend = "lancedb"    # pip install "sarthak[lancedb]"
```

---

## Speech-to-text provider

```toml
[stt]
provider = "whisper"    # whisper | openai | groq | deepgram | assemblyai

[stt.whisper]
model  = "base.en"   # tiny | base | small | medium | large
device = "CPU"       # CPU | GPU | NPU

[stt.groq]
# Groq Whisper — very fast, generous free tier
api_key = "ENC:..."
model   = "whisper-large-v3-turbo"
```

---

## Agent sandbox limits

Tune how much resource scheduled agents can use:

```toml
[agents.sandbox.system]
wall_timeout  = 120      # seconds per run
output_cap    = 65536    # bytes of output
max_web_calls = 10       # HTTP calls per run

[agents.sandbox.space]
wall_timeout  = 300
output_cap    = 65536
max_web_calls = 10
```

Set `enabled = false` only in local development — this disables all sandbox enforcement.
