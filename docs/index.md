<div class="md-hero" markdown>

# Sarthak AI

Your personal AI learning companion. Local, private, and built around how you actually work.

[Get started in 5 minutes](guides/installation.md){ .md-button .md-button--primary }
[Browse features](features/spaces.md){ .md-button }

</div>

## What is Sarthak?

Sarthak is a **local-first learning and productivity platform**. Everything runs on your machine — no accounts, no cloud sync, no subscriptions. It works fully offline with a local AI model, or with any cloud provider you choose.

It has two core parts that work together:

**Sarthak Spaces** is the learning engine. Give it a domain and your background, and it builds a personal curriculum, teaches each concept the way a senior mentor would (adapted to your background), tracks your progress with XP and spaced repetition, and selects your next concept at the exact edge of your current ability. Works for engineers, doctors, teachers, business analysts, researchers, and exam candidates.

**Sarthak Agents** lets you create automations from plain-language descriptions. "Every morning at 8am, send me a digest of what I should study today." Sarthak handles the rest.

---

## Quick start — 5 minutes

The fastest way is [OpenRouter](https://openrouter.ai), which offers free models with one API key.

```bash
# 1. Install
uv tool install sarthak   # or: pip install sarthak

# 2. Set up — choose OpenRouter, paste your key, pick a free model
sarthak configure

# 3. Start
sarthak service install   # background service (recommended)
# or: sarthak orchestrator  # foreground

# 4. Open
# http://localhost:4848
```

> **Free models on OpenRouter**: Sign up at [openrouter.ai](https://openrouter.ai), go to Keys, copy your key. In `sarthak configure`, choose **OpenRouter** and enter a model like `meta-llama/llama-3.1-8b-instruct:free`. Browse free models at [openrouter.ai/models?q=free](https://openrouter.ai/models?q=free).

---

## Privacy

Everything Sarthak stores is local. Sensitive patterns (passwords, tokens, keys) are automatically stripped from captured data before anything is saved. API keys are encrypted at rest with AES-GCM and never leave your machine in raw form.

Sarthak sends zero telemetry.

---

## Where to go next

<div class="grid cards" markdown>

-   **Install and first setup**

    Get Sarthak running in 5 minutes with a free AI provider.

    [Installation guide](guides/installation.md)

-   **Configure your provider**

    Set up OpenRouter, Ollama, or any other provider. Add Telegram.

    [Configuration guide](guides/configuration.md)

-   **Learning with Spaces**

    How the mastery engine works — curriculum, ZPD, spaced repetition.

    [Spaces guide](features/spaces.md)

-   **Automation Agents**

    Create, schedule, and manage automations in plain English.

    [Agents guide](features/agents.md)

-   **Web UI walkthrough**

    Every page and panel in the Sarthak browser app explained.

    [Web UI guide](features/web.md)

-   **MCP integration**

    Use Sarthak with Claude Code, Gemini CLI, opencode, or Zed.

    [MCP guide](features/mcp.md)

</div>
