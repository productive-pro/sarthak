<div align="center">

<img src="docs/icons/sarthak_icon.svg" alt="Sarthak AI Logo" width="80" />

# Sarthak AI

**Privacy-first AI learning companion and productivity intelligence platform.**  
Local. Offline-capable. Works for engineers, doctors, teachers, researchers — anyone learning anything.

[![License: AGPL v3](https://img.shields.io/badge/License-AGPL%20v3-blue.svg)](LICENSE)
[![Python 3.11+](https://img.shields.io/badge/Python-3.11%2B-blue)](https://www.python.org/)
[![PyPI](https://img.shields.io/pypi/v/sarthak)](https://pypi.org/project/sarthak/)
[![Docs](https://img.shields.io/badge/docs-mkdocs-informational)](https://productive-pro.github.io/sarthak)

[Quick Start (5 min)](#-quick-start-openrouter-free) · [Features](#features) · [All Providers](#ai-providers) · [CLI Reference](#cli-reference) · [Docs](https://productive-pro.github.io/sarthak)

</div>

---

## What is Sarthak?

Sarthak is a **local-first learning and productivity platform** — it runs on your machine, stores all data locally, and works fully offline. It gives you two things:

**Spaces** — a personalized mastery engine. Tell it your domain (Data Science, Medicine, Exam Prep…) and your background. It builds a full curriculum, teaches every concept the way a senior mentor would (adapted to your background), tracks your progress with XP and spaced repetition, and selects your next concept at the exact edge of your current ability.

**Agents** — scheduled automations you create by describing what you want in plain English. "Every morning, send me a digest of what I should study." Done.

Everything runs through a web UI at `localhost:4848`, a terminal UI, or your phone via Telegram.

---

## ⚡ Quick Start (OpenRouter — Free)

The fastest way to get started: OpenRouter gives you access to many models, including free ones, with a single API key.

**Step 1 — Get a free OpenRouter key**

Go to [openrouter.ai](https://openrouter.ai) → sign up → copy your API key from the Keys page.

**Step 2 — Install Sarthak**

```bash
# Recommended: uv (fast, isolated)
uv tool install sarthak

# Or pip
pip install sarthak
```

**Step 3 — Configure with OpenRouter**

```bash
sarthak configure
```

When prompted:
- Provider → choose **OpenRouter**
- API key → paste your key from Step 1
- Model → type a free model such as `meta-llama/llama-3.1-8b-instruct:free`

> **Free models on OpenRouter** — search `openrouter.ai/models?q=free` and filter by `:free` suffix. Good options: `meta-llama/llama-3.1-8b-instruct:free`, `mistralai/mistral-7b-instruct:free`, `google/gemma-2-9b-it:free`.

**Step 4 — Start**

```bash
sarthak service install     # installs as background service (recommended)
# OR
sarthak orchestrator        # run in the terminal foreground
```

Open **[http://localhost:4848](http://localhost:4848)** in your browser.

**Step 5 — Create your first Space**

1. Click **Spaces** in the sidebar → **+ New Space**
2. Choose a domain (e.g. Data Science), describe your background, set a goal
3. Sarthak generates a full curriculum — you're ready to learn

---

## AI Providers

Sarthak works with any of these. You can switch at any time from the Config page.

| Provider | Free? | Notes |
|---|---|---|
| **OpenRouter** | ✅ Free models available | Single key, many models. Best for quick start. |
| **Ollama** | ✅ Fully free | Local, offline, no key needed. Install from [ollama.com](https://ollama.com). |
| **GitHub Models** | ✅ Free tier | GitHub personal access token. `sarthak copilot login`. |
| **Groq** | ✅ Free tier | Very fast. Get key at [console.groq.com](https://console.groq.com). |
| **Google Gemini** | ✅ Free tier | [aistudio.google.com](https://aistudio.google.com) → Get API key. |
| **OpenAI** | 💳 Paid | GPT-4o and friends. [platform.openai.com](https://platform.openai.com). |
| **Anthropic** | 💳 Paid | Claude models. `pip install "sarthak[cloud]"` first. |
| **Custom** | — | Any OpenAI-compatible endpoint (self-hosted, LM Studio, etc.) |

### Configuring OpenRouter manually (config.toml)

```toml
[ai]
default_provider = "openrouter"
default_model    = "meta-llama/llama-3.1-8b-instruct:free"

[ai.openrouter]
model   = "meta-llama/llama-3.1-8b-instruct:free"
# Encrypt your key first: sarthak encrypt "sk-or-..."
# Then paste the ENC:... value here:
api_key = "ENC:your-encrypted-key-here"
timeout = 30
```

Encrypt your key so it's never stored in plain text:

```bash
sarthak encrypt "sk-or-v1-yourkey..."
# Output: ENC:abc123...  ← paste this into config.toml
```

### Fallback chain

If your primary model fails, Sarthak automatically tries fallback models:

```toml
[ai.fallback]
fallback1_provider = "openrouter"
fallback1_model    = "mistralai/mistral-7b-instruct:free"
fallback2_provider = "ollama"
fallback2_model    = "gemma3:4b"
```

---

## Features

### Spaces — Adaptive Learning Engine

- **Personalized curriculum** — generates a full roadmap (chapters → topics → concepts) for any domain, adapted to your background and goal
- **Zone of Proximal Development** — always picks the next concept at the edge of what you know; too-easy and too-hard are deprioritized automatically
- **Spaced repetition (SM-2)** — concepts cycle back on an evidence-based review schedule
- **15 specialist AI sub-agents** — dedicated agents for curriculum planning, math explanations, task generation, project scaffolding, assessment, and more
- **Knowledge graph** — interactive D3 visualization of how your concepts connect
- **XP and streak tracking** — gamified progress that rewards consistency
- **Practice tests** — timed tests drawn from your roadmap or your own notes/files
- **Speech-to-text notes** — dictate notes inside any concept tab
- **RAG over your workspace** — Sarthak indexes your notes, PDFs, and code and uses them as grounding context
- **Domain templates** — Data Science, AI Engineering, Software Engineering, Medicine, Education, Exam Prep, Research, Custom

### Agents — Scheduled Automations

- **Natural-language creation** — describe what you want; Sarthak infers schedule, tools, and sandbox policy
- **5 built-in agents** — daily digest, SRS reminders, hourly recommendations, weekly review, workspace analyser
- **Telegram delivery** — receive results on your phone
- **Sandbox safety** — every run is sandboxed with time limits, secret scrubbing, and path guards
- **Space-scoped agents** — agents that have access to a specific Space's roadmap and notes

### Interfaces

- **Web UI** — React 19 SPA at `localhost:4848`; no cloud, no accounts
- **Terminal UI (TUI)** — Textual dashboard with activity feed and chat
- **CLI** — full `sarthak` command suite
- **MCP server** — expose Sarthak to Claude Code, Gemini CLI, opencode, Zed
- **Telegram bot** — full chat interface on your phone
- **WhatsApp bot** — QR-login personal account bot

### Privacy & Architecture

- **All data is local** — nothing leaves your machine
- **AES-GCM encryption at rest** — all secrets encrypted before storage
- **Secret scrubbing** — sensitive patterns stripped before any LLM call
- **Offline-capable** — works fully offline with Ollama or any local model
- **3-tier fallback chain** — agents never crash on transient provider errors
- **Cross-platform** — Linux, macOS, Windows

---

## Installation

### Requirements

- Python 3.11 or higher
- An AI provider (see table above; start free with OpenRouter or Ollama)

### One-line install — Linux / macOS

```bash
curl -fsSL https://raw.githubusercontent.com/productive-pro/sarthak/main/scripts/install.sh | bash
```

### One-line install — Windows (PowerShell)

```powershell
irm https://raw.githubusercontent.com/productive-pro/sarthak/main/scripts/install.ps1 | iex
```

### Install from PyPI

```bash
uv tool install sarthak                 # recommended
pip install sarthak                     # minimal
pip install "sarthak[cloud]"            # with OpenAI / Anthropic support
```

### Install from source

```bash
git clone https://github.com/productive-pro/sarthak
cd sarthak
uv sync
uv run sarthak --help
```

---

## CLI Reference

### Core

```bash
sarthak configure           # interactive setup wizard
sarthak configure --mode quick   # fast minimal setup
sarthak orchestrator        # start all services in foreground
sarthak status              # check config, DB, and web health
sarthak tui                 # open terminal UI
sarthak mcp                 # start MCP server (stdio)
sarthak encrypt "my-key"    # encrypt a secret → ENC:...
sarthak decrypt "ENC:..."   # decrypt a secret
sarthak reset               # wipe all data and config
sarthak uninstall           # remove package and/or config
```

### Service management

```bash
sarthak service install     # install + start background service
sarthak service uninstall   # stop + remove service
sarthak service status      # show service status
```

### Spaces

```bash
sarthak spaces init --dir . --type data_science --background "Python dev" --goal "learn ML"
sarthak spaces list                        # list all spaces
sarthak spaces activate --dir ./my-space  # set active space
sarthak spaces status --dir .              # show mastery status
sarthak spaces learn --dir .               # run a quick learning session
sarthak spaces session --dir . --concept "gradient descent" --minutes 45
sarthak spaces practice --type concept --scope "backprop" --source llm
sarthak spaces roadmap --dir .             # view curriculum
sarthak spaces roadmap --dir . --regen    # regenerate roadmap via AI
sarthak spaces roadmap-sync --dir .       # re-index files + rebuild RAG
sarthak spaces rag index --dir .           # index workspace files
sarthak spaces rag search --dir . --query "numpy arrays"
sarthak spaces optimize --dir . --last 10  # show personalized recommendations
sarthak spaces evaluate "gradient descent" --dir .
sarthak spaces project --dir .             # scaffold a project
sarthak spaces refine --dir . --answers "beginner, practical focus"
```

### Agents

```bash
sarthak agents create "Every morning, summarise what I should study" --telegram
sarthak agents create --space --dir ~/ml-space "Daily notes digest"
sarthak agents list                    # all agents
sarthak agents list --system           # global agents only
sarthak agents list --space            # space agents only
sarthak agents run <agent-id>          # run now, ignore schedule
sarthak agents logs <agent-id>         # recent run history
sarthak agents enable <agent-id>
sarthak agents disable <agent-id>
sarthak agents delete <agent-id>
```

### Channels

```bash
sarthak channels status     # show Telegram, WhatsApp, and web status
```

---

## Configuration

All config lives in `~/.sarthak_ai/config.toml`. Edit it directly or use the **Config** page in the web UI.

```toml
[ai]
default_provider = "openrouter"
default_model    = "meta-llama/llama-3.1-8b-instruct:free"

[ai.openrouter]
model   = "meta-llama/llama-3.1-8b-instruct:free"
api_key = "ENC:..."       # sarthak encrypt "sk-or-..."

[ai.fallback]
fallback1_provider = "ollama"
fallback1_model    = "gemma3:4b"

[web]
host = "127.0.0.1"
port = 4848

[telegram]
enabled         = false
# bot_token       = "ENC:..."
# allowed_user_id = 123456789
```

See [`config.toml`](config.toml) for all options and comments.

---

## Data locations

| Path | Contents |
|---|---|
| `~/.sarthak_ai/config.toml` | Configuration |
| `~/.sarthak_ai/master.key` | Local encryption key (never share) |
| `~/.sarthak_ai/sarthak.db` | Global activity events |
| `~/.sarthak_ai/agents/` | Global agent specs and run history |
| `<space_dir>/.spaces/sarthak.db` | AI curriculum (chapters, topics, concepts) |
| `<space_dir>/.spaces/roadmap.json` | XP, streak, session history |
| `<space_dir>/.spaces/SOUL.md` | Agent identity for this domain |
| `<space_dir>/.spaces/MEMORY.md` | Long-term learner patterns |
| `<space_dir>/.spaces/HEARTBEAT.md` | SRS due counts, daily checks |
| `<space_dir>/.spaces/memory/YYYY-MM-DD.md` | Daily session logs |
| `<space_dir>/.spaces/rag/` | Vector index for document search |
| `<space_dir>/.spaces/Optimal_Learn.md` | Workspace analysis (updated each session) |

---

## MCP — Use Sarthak from Claude Code / Gemini CLI

```json
{
  "mcpServers": {
    "sarthak": {
      "command": "sarthak",
      "args": ["mcp"]
    }
  }
}
```

Add this to `.claude/mcp.json`, `~/.config/gemini/mcp.json`, or your tool's equivalent. Sarthak exposes your learning history, active space, and session summaries to any connected AI assistant.

---

## Development

```bash
git clone https://github.com/productive-pro/sarthak && cd sarthak
uv sync
uv run pytest                   # run tests
uv run ruff check src/          # lint
uv run ruff format src/         # format

# Frontend (React 19 + Vite 7)
cd frontend && npm install && npm run dev    # dev server at :5173
bash rebuild_frontend.sh                    # build + copy for FastAPI
```

Read [`AGENTS.md`](AGENTS.md) before contributing — it is the authoritative codebase guide.

---

## License

[AGPL-3.0](LICENSE). For commercial licensing without AGPL obligations, contact [hello@sarthak.ai](mailto:hello@sarthak.ai).

---

<div align="center">

Built with the belief that every person deserves a senior mentor — available every day.

</div>
