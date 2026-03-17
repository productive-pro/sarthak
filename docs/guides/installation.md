# Installation

## Requirements

- Python 3.11 or higher
- An AI provider — free options: [OpenRouter](https://openrouter.ai) (free models), [Ollama](https://ollama.com) (local), [GitHub Models](https://github.com/marketplace/models), [Groq](https://console.groq.com)

## Fastest start — OpenRouter (free, no GPU needed)

1. Sign up at [openrouter.ai](https://openrouter.ai) and copy your API key from the Keys page
2. Install Sarthak and run the wizard — choose **OpenRouter**, paste the key, pick a free model

```bash
uv tool install sarthak
sarthak configure
```

Free models to try: `meta-llama/llama-3.1-8b-instruct:free`, `mistralai/mistral-7b-instruct:free`, `google/gemma-2-9b-it:free`  
Browse all free models: [openrouter.ai/models?q=free](https://openrouter.ai/models?q=free)

---

## Install on Linux or macOS

```bash
curl -fsSL https://raw.githubusercontent.com/productive-pro/sarthak/main/scripts/install.sh | bash
```

The installer sets up Sarthak, registers it as a background service (systemd on Linux, launchd on macOS), and generates your local encryption key.

## Install on Windows

Open PowerShell and run:

```powershell
irm https://raw.githubusercontent.com/productive-pro/sarthak/main/scripts/install.ps1 | iex
```

## Install from PyPI

```bash
uv tool install sarthak                # recommended — fast and isolated
pip install sarthak                    # basic install

pip install "sarthak[cloud]"           # adds OpenAI and Anthropic support
```

## First-time setup

After installing, run the setup wizard:

```bash
sarthak configure
```

This walks you through:

1. Choosing an AI provider (OpenRouter, Ollama, OpenAI, Anthropic, Gemini, Groq, GitHub Models, or custom)
2. Entering your API key — it is encrypted immediately, never stored in plain text
3. Setting a model name — the wizard shows examples for your chosen provider
4. Optionally: setting up Telegram for phone notifications

Run `sarthak configure --mode quick` if you want just the essentials.

## Starting Sarthak

### As a background service (recommended)

```bash
sarthak service install
```

This registers Sarthak as a background service (systemd user unit on Linux, launchd on macOS, Task Scheduler on Windows) and starts everything: the web UI, agent scheduler. Then open [http://localhost:4848](http://localhost:4848).

### In the foreground

```bash
sarthak orchestrator
```

Ctrl+C to stop. Useful for troubleshooting or if you don't want a persistent service.

## Checking that everything works

```bash
sarthak status
```

This shows whether your config file, encryption key, database, and web server are all working correctly.

## Ollama (fully local, offline)

If you prefer a fully offline setup with no API key:

1. Install Ollama from [ollama.com](https://ollama.com)
2. Pull a model: `ollama pull gemma3:4b`
3. In `sarthak configure`, choose **Ollama** — no key required

```toml
# ~/.sarthak_ai/config.toml
[ai]
default_provider = "ollama"
default_model    = "gemma3:4b"

[ai.ollama]
base_url   = "http://localhost:11434/v1"
text_model = "gemma3:4b"
```

## Speech-to-text (optional)

Sarthak supports voice note dictation inside the concept workspace. The installer sets this up automatically using `whisper.cpp`. To install manually:

```bash
python scripts/install-whisper.py
```

The default model (`base.en`) is a good balance of speed and accuracy. Larger models (`small`, `medium`) are more accurate but slower on CPU.

## Uninstalling

```bash
sarthak uninstall         # interactive: remove config only, or full uninstall
# or
bash scripts/uninstall.sh    # Linux / macOS
.\scripts\uninstall.ps1      # Windows
```

This removes the background service but does not delete your learning data. Your Spaces data lives inside your own workspace folders (`.spaces/` subdirectory) — delete those manually if needed.

To wipe everything without uninstalling the package:

```bash
sarthak reset             # confirms before wiping ~/.sarthak_ai/
sarthak reset --force     # skips confirmation
```
