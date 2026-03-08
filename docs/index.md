<div class="md-hero" markdown>

# Sarthak AI

Your personal AI learning companion. Local, private, and built around how you actually work.

[Get started](guides/installation.md){ .md-button .md-button--primary }
[Spaces guide](features/spaces.md){ .md-button }

</div>

## What is Sarthak?

Sarthak is a local-first learning and productivity platform. Everything runs on your machine — no accounts, no cloud sync, no subscriptions. It works fully offline with a local AI model.

It has two core parts that work together:

**Sarthak Spaces** is the learning engine. Give it a domain and your background, and it builds a personal curriculum, teaches each concept the way an expert mentor would, tracks your progress with XP and spaced repetition, and adapts to how you are doing in real time. It works for engineers, doctors, teachers, business analysts, researchers, and exam candidates.

**Sarthak Agents** lets you create automations from plain-language descriptions. Describe what you want — Sarthak handles the rest, running it on a schedule and optionally delivering results to Telegram.

---

## What Sarthak tracks

Sarthak runs quietly in the background and captures your work context — which apps you are using, how long you are focused, and what you are working on. It turns this into daily summaries, focus scores, and learning recommendations.

All of this data stays on your machine. Nothing is sent anywhere.

---

## Quick start

```bash
# Install
curl -fsSL https://raw.githubusercontent.com/productive-pro/sarthak/main/scripts/install.sh | bash

# Set up your AI provider
sarthak configure

# Start Sarthak (capture + web UI + agents)
sarthak orchestrator
```

Then open [http://localhost:4848](http://localhost:4848) in your browser.

---

## Privacy

Everything Sarthak stores is local. Sensitive patterns (passwords, tokens, keys) are automatically stripped from captured terminal history before anything is saved. API keys are encrypted at rest and never leave your machine in raw form.

---

## Where to go next

<div class="grid cards" markdown>

-   **Install**

    Set up Sarthak on Linux, macOS, or Windows.

    [Installation guide](guides/installation.md)

-   **Configure**

    Connect an AI provider and set your preferences.

    [Configuration guide](guides/configuration.md)

-   **Using the app**

    A complete guide to the Sarthak web UI.

    [Web UI guide](features/web.md)

-   **Spaces**

    How the learning engine works and how to get the most from it.

    [Spaces guide](features/spaces.md)

</div>
