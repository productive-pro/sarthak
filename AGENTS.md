# AGENTS.md — Sarthak AI Codebase Guide for AI Agents

This file is the authoritative reference for AI agents (Codex, Claude, Cursor, etc.)
working on the **Sarthak AI** codebase. Read it before touching any code.

---

## Project Overview

Sarthak AI is a **privacy-first productivity intelligence platform for effective learning and doing projects** built in Python 3.11+.
It tracks work activity, manages adaptive learning "Spaces", and runs scheduled AI agents —
all runnable fully offline.

**Primary entry point:** `sarthak` CLI → `src/sarthak/cli/`
**Tech stack:** pydantic-ai, Pydantic v2, FastAPI, Textual TUI, SQLite (aiosqlite), structlog
**Package root:** `src/sarthak/`

---

## Repository Layout

```
src/sarthak/
├── agents/          # Custom automation agent engine (create / schedule / run)
│   ├── models.py        AgentSpec, AgentRun, AgentScope, AgentTool, SandboxPolicy
│   ├── creator.py       AI-powered agent creator (natural language → AgentSpec)
│   ├── runner.py        Agent executor: sandbox → LLM → save run → notify
│   ├── scheduler.py     Cron scheduler + 4 built-in system agents
│   ├── store.py         JSON persistence for specs and run history
│   ├── roadmap_agents.py  generate_roadmap / build_digest / stream_explain
│   └── sandbox/         Sandboxing subsystem (see below)
├── cli/             # Click CLI commands
├── core/            # Config, logging, constants, notifications
│   └── ai_utils/        LLM provider plumbing (multi-provider, fallback model)
├── features/
│   ├── ai/              Orchestrator agent + specialist sub-agents
│   │   ├── agent.py         Public API: ask_orchestrator(), analyse_snapshot(), etc.
│   │   ├── agents/
│   │   │   ├── orchestrator.py  Primary user-facing pydantic-ai Agent (all channels)
│   │   │   ├── summary.py
│   │   │   └── vision.py
│   │   ├── deps.py          Pydantic dep/result models (OrchestratorDeps, OrchestratorResult)
│   │   ├── skills/          User-editable skill snippets injected into system prompt
│   │   └── tools/           @agent.tool functions registered on the orchestrator
│   ├── channels/        Telegram bot, TUI, web channel adapters
│   ├── mcp/             MCP server integration
│   └── tui/             Textual TUI
├── orchestrator/    # Top-level routing: route() → ask_orchestrator()
├── spaces/          # Learning Spaces subsystem
│   ├── models.py        Core data models (SpaceProfile, LearnerProfile, LearningTask…)
│   ├── sub_agents.py    15 stateless specialist agents (curriculum, math, assessment…)
│   ├── store.py         Space profile persistence
│   ├── roadmap/         RoadmapDB (SQLite), SRS engine, recommendations
│   └── orchestrator.py  Spaces session orchestration
└── storage/         # SQLite activity store helpers
```


---

## Agent Architecture

### 1. Orchestrator Agent (`features/ai/agents/orchestrator.py`)

The **single entry point** for all user-facing text input (TUI, Telegram, Web).

- Built with `pydantic-ai` `Agent[OrchestratorDeps, OrchestratorResult]`
- Uses **agent delegation** via `@agent.tool` to specialist sub-agents (`vision`, `summary`)
- Registered tools: `query_activity`, `run_shell`, `spaces_*`, `rag_*`, skill CRUD, web search
- System prompt built from `core/ai_utils/prompts/` + injected user skills
- **Do not add heavy logic here.** Route new capabilities to a new tool or sub-agent.

**Call path:** user input → `orchestrator.route()` → `features/ai/agent.ask_orchestrator()` → `Agent.run()`

### 2. Custom Agent Engine (`agents/`)

Lets users define their own scheduled automation agents in natural language.

| File | Responsibility |
|---|---|
| `models.py` | `AgentSpec` (persistent definition), `AgentRun` (execution record), `SandboxPolicy` |
| `creator.py` | `create_agent_from_description()` — LLM parses NL → `AgentSpec`, saves to disk |
| `runner.py` | `run_agent()` — orchestrates sandbox → pydantic-ai `Agent.run()` → save run → Telegram |
| `scheduler.py` | `tick()` runs every 60 s; fires due agents as background `asyncio.Task`s |
| `store.py` | JSON spec files + registry; `save_agent`, `load_agent`, `list_agents`, `save_run` |

**Storage layout:**
- Global agents: `~/.sarthak_ai/agents/<agent_id>/spec.json`
- Space agents: `<space_dir>/.spaces/agents/<agent_id>/spec.json`
- Run history: `<agent_dir>/runs/<run_id>.json` (capped at 50)
- Registry index: `~/.sarthak_ai/agents/registry.json`


**Built-in system agents** (auto-registered on startup via `scheduler.ensure_builtin_agents()`):

| agent_id | Schedule | Purpose |
|---|---|---|
| `sarthak-daily-digest` | `0 8 * * *` | Daily learning digest per space → Telegram |
| `sarthak-srs-push` | `0 9 * * *` | SRS due cards reminder → Telegram |
| `sarthak-recommendations` | `0 * * * *` | Hourly next-concept refresh for all spaces |
| `sarthak-weekly-digest` | `0 9 * * 0` | Full week-in-review → Telegram |

### 3. Spaces Sub-Agents (`spaces/sub_agents.py`)

15 **stateless** specialist agents. Each has ONE responsibility.
Called by the Spaces orchestrator and by the custom agent scheduler, never directly by user input.

| Class | Role |
|---|---|
| `OnboardingAgent` | Detect learner background; set personalization flags |
| `CurriculumAgent` | ZPD-based next-concept selection |
| `MathAgent` | Mathematical explanations at the right depth |
| `TaskBuilderAgent` | Hands-on tasks with starter code, hints, bonus |
| `ProjectAgent` | Scaffold and guide end-to-end projects |
| `EngagementAgent` | Transform dry content into engaging Markdown |
| `AssessmentAgent` | Evaluate submissions; detect novel approaches |
| `WorkspaceAgent` | Non-destructive workspace restructuring |
| `SpacedRepetitionAgent` | SM-2 review scheduling (pure logic, no LLM) |
| `BadgeAgent` | Achievement system (pure logic, no LLM) |
| `QuickTestAgent` | 5-minute micro-task generation |
| `WorkspaceAnalyserAgent` | Produce `Optimal_Learn.md` from workspace snapshot |
| `ExternalToolsAgent` | Detect and recommend external tools (VS Code, Colab…) |
| `EnvironmentAgent` | Real OS scan → missing tool recommendations |

All LLM-calling agents use `_call_llm_json(system, prompt, fallback)` — returns a `dict`,
never raises, falls back to the provided `fallback` dict on any LLM failure.

### 4. Roadmap Agents (`agents/roadmap_agents.py`)

Three pydantic-ai agents for the Spaces roadmap feature:

- `generate_roadmap()` — structured output → `Roadmap` with chapters/topics/concepts
- `build_digest()` — real learner data → Markdown daily digest (evidence-based SRS sync included)
- `stream_explain()` — async SSE token stream for inline concept explanations


---

## Sandbox System (`agents/sandbox/`)

Every custom agent run is wrapped by `enforce_sandbox()` from `sandbox/enforcer.py`.

```
enforce_sandbox(spec, execute_fn)
  ├── build_sandbox_config(spec)   # derive SandboxConfig from AgentSpec
  ├── scrub(spec.prompt)           # strip secrets before LLM sees them
  ├── asyncio.wait_for(execute_fn, timeout=cfg.wall_timeout)
  ├── scrub(output)                # strip secrets from output
  └── truncate output to cfg.output_cap
```

Key `SandboxConfig` fields:
- `allow_shell`, `allow_web`, `allow_file_read`, `allow_file_write`, `allow_http_fetch`
- `write_roots`, `read_roots` — `PathGuard` enforces these strictly
- `wall_timeout` (default 120 s system / 300 s space), `memory_cap`, `cpu_seconds`
- `output_cap` (64 KB), `max_web_calls` (10 per run)

**Override resolution order:** per-agent `SandboxPolicy` > `config.toml [agents.sandbox.*]` > hardcoded defaults

Disable sandbox for dev only:
```toml
# config.toml
[agents.sandbox.system]
enabled = false
```

---

## LLM Provider Plumbing

All agents use two helpers from `features/ai/agents/_base.py`:

```python
resolve_provider_model(provider?, model?)  # → (provider_str, model_str)
build_pydantic_model(provider, model)      # → FallbackModel chain (3-tier)
```

`build_fallback_model()` in `core/ai_utils/multi_provider.py` builds a 3-tier fallback
chain so agents survive transient provider failures.

**Config:** `config.toml` → `[ai]` section → `default_provider`, per-provider `text_model`.

One-shot LLM call shared by all agents:
```python
from sarthak.features.ai.agents._base import run_llm
result: str = await run_llm(system_prompt, user_prompt)
```

---

## Core Data Models

### AgentSpec (`agents/models.py`)
```python
agent_id: str           # slug, e.g. "daily-digest"
name: str
prompt: str             # task instruction
schedule: str           # cron expression
tools: list[AgentTool]  # WEB_SEARCH | SHELL | FILE_READ | FILE_WRITE | HTTP_FETCH
scope: AgentScope       # GLOBAL | SPACE
sandbox: SandboxPolicy  # optional resource overrides
```

### SpaceProfile / LearnerProfile (`spaces/models.py`)
Core learning state persisted as JSON via `spaces/store.py`.
Key learner fields: `skill_level`, `mastered_concepts`, `struggling_concepts`,
`concept_mastery_map`, `xp`, `streak_days`, `badges`, `is_technical`.

### OrchestratorResult (`features/ai/deps.py`)
```python
reply: str          # Markdown response to user
action_taken: str   # what the agent did ("query_activity", "spaces_session", "error"…)
```


---

## Key Conventions

1. **No regex routing** — all free-text goes to the orchestrator agent. Deterministic
   button/command actions are dispatched in the channel layer before calling the orchestrator.

2. **Stats only from storage** — activity tools return aggregated stats, never raw rows,
   to avoid LLM context bloat.

3. **Stateless sub-agents** — Spaces sub-agents hold no session state. Pass everything
   they need (SpaceContext, primitives) on every call.

4. **JSON output from LLM** — any agent that needs structured data from an LLM must:
   - Put `Output ONLY valid JSON: {...}` at the end of the system prompt.
   - Parse with `parse_json_response(raw)` (strips markdown fences before `json.loads`).
   - Provide a `fallback` dict so the call never crashes on LLM failure.

5. **Pydantic v2** — use `model.model_dump_json()`, `Model.model_validate_json()`,
   `model.model_copy()`. Do **not** use v1 `.dict()` / `.parse_raw()`.

6. **Async throughout** — all I/O (LLM, DB, filesystem) is `async`.
   Use `asyncio.create_task()` for fire-and-forget agent runs in the scheduler.

7. **Structured logging** — always `structlog.get_logger(__name__)` or `get_logger(__name__)`.
   Log with key-value pairs: `log.info("event_name", key=value)`.

8. **Secret scrubbing** — `sandbox/secret_scrubber.py` runs automatically via `enforce_sandbox`.
   Never pass API keys in agent prompts or custom tool inputs.

9. **AGENTS.md in Space workspaces** — `WorkspaceAnalyserAgent._sample_workspace()` reads any
   `AGENTS.md` found in the learner's workspace (up to 600 chars) and includes it in the
   `Optimal_Learn.md` prompt context. Place an AGENTS.md in a Space to give the orchestrator
   persistent project context.

---

## How-To: Adding New Functionality

### Add a new tool to the Orchestrator

1. Implement the tool function in `features/ai/tools/` (follow existing tool patterns).
2. Import and register it in `features/ai/agents/orchestrator.py`.
3. Use `@agent.tool` if you need `RunContext[OrchestratorDeps]` (for pool/cwd/flags).
   Use `@agent.tool_plain` for stateless helpers with no deps.
4. Add a clear docstring — pydantic-ai exposes it to the LLM as the tool description.

### Add a new AgentTool capability

1. Add enum value to `AgentTool` in `agents/models.py`.
2. Add a `_make_<tool>_tool()` builder in `agents/runner.py`.
3. Register it in `_build_tools()` gated on the relevant `SandboxConfig.allow_*` flag.
4. Add the corresponding `allow_*` field to `SandboxConfig` in `sandbox/config.py`.

### Add a new built-in system agent

1. Add a dict entry to `_BUILTIN_AGENTS` in `agents/scheduler.py`.
2. Add a handler `_run_<name>_agent(spec)` and register it in the `handlers` dict in
   `_run_agent_with_context()`.
3. Keep handlers focused — delegate to existing helpers (`build_digest`, `get_due`, etc.).

---

## Running Tests & Linting

```bash
uv run pytest                  # all tests (asyncio_mode = auto)
uv run pytest tests/agents/    # agent engine tests only

uv run ruff check src/
uv run ruff format src/
```

---

## File Locations Quick Reference

| What | Where |
|---|---|
| CLI commands | `src/sarthak/cli/` |
| App config | `config.toml` (project root) or `~/.sarthak_ai/config.toml` |
| System prompts | `src/sarthak/core/ai_utils/prompts/` |
| Agent prompts | `src/sarthak/agents/prompts/` |
| Provider normalization | `src/sarthak/core/ai_utils/multi_provider.py` |
| Global agent storage | `~/.sarthak_ai/agents/` |
| Space data | `<space_dir>/.spaces/` |
| Optimal_Learn.md | `<space_dir>/.spaces/Optimal_Learn.md` |
| SRS database | `<space_dir>/.spaces/sarthak.db` |
| Run logs | `logs/` (project root) |

---

## Scripts (`scripts/`)

| Script | Platform | Purpose |
|---|---|---|
| `install.sh` | Linux / macOS | Full installer: uv, venv, wizard, config patch, CLI wrapper, systemd/launchd service |
| `install.ps1` | Windows | Same flow for PowerShell: uv, venv, wizard, config patch, CLI wrapper, Task Scheduler |
| `uninstall.sh` / `uninstall.ps1` | Both | Remove install dir and service |
| `status.sh` / `status.ps1` | Both | Run `sarthak status` (finds binary from PATH or `~/.local/bin`) |
| `build_binary.sh` | Linux / macOS | Nuitka `--onefile` binary → `dist/sarthak` |
| `build_binary.ps1` | Windows | Same for Windows `.exe` |
| `install-binary.sh` / `.ps1` | Both | Install a pre-built binary release |
| `gen_ref_pages.py` | Dev | Generate MkDocs API reference pages |
| `sync_catalog.py` | Dev | Fetch live model lists from OpenRouter, OpenAI, Ollama, AIMLAPI, GitHub Copilot → `providers.json` |

### `install.sh` / `install.ps1` — three install modes

```bash
# Dev (local repo)
LOCAL_INSTALL=1 bash scripts/install.sh

# Specific release
RELEASE_TAG=v0.1.0 bash scripts/install.sh

# Latest HEAD (default)
bash scripts/install.sh
```

Environment variables: `SKIP_WIZARD=true` skips interactive config, `REPO_BRANCH` overrides the branch.

### `sync_catalog.py` — API keys needed

```bash
OPENROUTER_API_KEY=... OPENAI_API_KEY=... uv run scripts/sync_catalog.py
```

Reads `providers.json`, merges new models (never deletes existing), writes back. Ollama synced automatically if `localhost:11434` is reachable.

### `rebuild_frontend.sh`

```bash
bash rebuild_frontend.sh
```

Runs `npm run build` inside `frontend/`, copies `dist/` → `src/sarthak/web/react_dist/`. **Run this any time you change frontend code** before restarting the server.

---

## Frontend (`frontend/`)

React 19 + Vite 7 SPA. Served by the FastAPI backend from `src/sarthak/web/react_dist/`.

### Stack

- React 19, Vite 7, Zustand 5 (state), React Router DOM 7 (hash-based routing)
- CodeMirror 6 (`@uiw/react-codemirror`) for Markdown editing
- `react-markdown` + `remark-gfm` + `rehype-highlight` + `rehype-katex` for rendering
- No TypeScript — plain JSX throughout

### Source layout

```
frontend/src/
├── api.js            Thin fetch wrapper: api(path, opts) + fmt/fmtDur/nowTs helpers
├── App.jsx           Root component: hash-based page routing + popstate sync
├── store/index.js    Zustand store: theme, navigation, toasts, Spaces state
├── pages/
│   ├── Dashboard.jsx Active space hero + spaces grid + AW activity + agents strip
│   ├── Chat.jsx      SSE streaming chat with session history picker
│   ├── Spaces.jsx    Full Spaces UI (list → home → chapter → topic views)
│   ├── SpacePanels.jsx  Slide-in panel host (notes, tasks, SRS, graph, digest…)
│   ├── Agents.jsx    CRUD for custom agents
│   └── Config.jsx    config.toml live editor (Ctrl+S to save)
├── components/
│   ├── Sidebar.jsx   Navigation sidebar
│   ├── Toast.jsx     Toast notification stack
│   ├── Modal.jsx     Reusable modal dialog
│   ├── Overlay.jsx   Slide-in overlay panel
│   ├── MarkdownEditor.jsx  CodeMirror edit / rendered read modes with STT and file import
│   ├── PromptInline.jsx    Inline prompt bar for LLM generation flows
│   ├── DropdownMenu.jsx    Context menu component
│   ├── ForceGraph.jsx      D3 force-directed concept graph
│   └── ConceptGraph.jsx    Wrapper for ForceGraph
├── sarthak/
│   ├── ConceptTabs.jsx     ExplainsTab, QuickTestTab, MediaRecorderTab, NotebookTab, PlaygroundTab
│   └── web/                (generated files — do not edit)
└── hooks/
    └── useResizable.js     Drag-to-resize sidebar hook (persists width in localStorage)
```

### API calls

All API calls go through `api(path, opts)` in `src/api.js`. It prepends `/api` and throws on non-2xx. **Streaming chat** uses `fetch` directly and reads SSE line-by-line. The backend runs on port `4848` in dev; Vite proxies `/api` to it automatically in dev mode.

### State management (Zustand)

All global state lives in `src/store/index.js`. Key slices:
- `page` + `setPage()` — hash-based navigation with `history.pushState`
- `isDark` / `toggleTheme()` — persisted to `localStorage`
- `toasts` / `ok()` / `err()` — toast notifications
- `currentSpace`, `currentChapter`, `currentTopic`, `spaceRoadmap` — Spaces drill-down state

### Building / developing

```bash
cd frontend
npm install
npm run dev        # dev server (proxies /api to localhost:4848)
npm run build      # production build → dist/
npm run lint       # eslint

# From repo root — build + deploy to FastAPI serving dir:
bash rebuild_frontend.sh
```
