# Installation

## Requirements

- Python 3.11 or higher
- An AI provider — Ollama (local and free), or a cloud provider like OpenAI or Anthropic
- ActivityWatch — optional but recommended for focus tracking

## Install on Linux or macOS

```bash
curl -fsSL https://raw.githubusercontent.com/1bharath-yadav/sarthak/main/scripts/install.sh | bash
```

The installer sets up Sarthak, registers it as a background service, and generates your local encryption key.

## Install on Windows

Open PowerShell and run:

```powershell
irm https://raw.githubusercontent.com/1bharath-yadav/sarthak/main/scripts/install.ps1 | iex
```

## Install from PyPI

```bash
uv tool install sarthak
pip install sarthak
```

For cloud AI provider support (OpenAI, Anthropic):

```bash
pip install "sarthak[cloud]"
```

## First-time setup

After installing, run the setup wizard:

```bash
sarthak configure
```

This walks you through choosing an AI provider, adding your API key, and setting basic preferences. Run `sarthak configure --mode quick` if you want a minimal setup.

## Starting Sarthak

```bash
sarthak orchestrator
```

This starts everything the web UI, and the agent scheduler. Then open [http://localhost:4848](http://localhost:4848) in your browser.

## Checking that everything works

```bash
sarthak status
```

This shows whether your configuration, AI provider connection, and background services are all working.


## Speech-to-text (optional)

Sarthak supports voice note dictation inside the concept workspace. To enable it, the installer handles this automatically. If you need to set it up manually:


The default model (`base.en`) is a good balance of speed and accuracy. Larger models are more accurate but slower on CPU.

## Uninstalling

```bash
bash scripts/uninstall.sh    # Linux / macOS
.\scripts\uninstall.ps1      # Windows
```

This removes the background service but does not delete your learning data. Add `--purge` if you want to remove everything including your Spaces and activity history.
