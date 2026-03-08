# System Architecture

Sarthak is composed of two independent subsystems — activity intelligence and the Spaces mastery engine — that share the same orchestration layer, AI provider abstraction, and storage primitives.

## High-level layout

```
src/sarthak/
  cli/                # Click entrypoint — spaces_cli, agents_cli, analytics_cli
  orchestrator/       # Service runner — starts all daemons
  features/
    ai/               # Pydantic AI agents, LiteLLM provider resolution
    capture/          # Window, terminal, snapshot daemons
    mcp/              # MCP server (stdio transport)
    tui/              # Textual dashboard
    channels/         # Telegram and other notification channels
  core/               # Config loader, logging (structlog), encryption utilities
  storage/            # SQLite schema (db.py), read/write helpers, rollup
  spaces/             # Mastery engine — see Spaces section
  agents/             # Scheduler, runner, creator, store, models
  analytics/          # Focus, resume, debug, weekly, trends reports
  web/                # Gradio + Plotly web UI
```

## Single-orchestrator rule

All channels (Telegram, TUI, Web) route through `features/channels/__init__.py` → `orchestrator/orchestrator.py` → `features/ai/agent.py`. No channel does its own routing.

All scheduled automation runs through `agents/scheduler.py`, started by `orchestrator/service.py` as the `agent_scheduler` service.

## Storage

All activity data lives in SQLite at `~/.sarthak_ai/sarthak.db` (via `storage/db.py`). No PostgreSQL.

Spaces data lives inside each workspace under `.spaces/`:

| File | Contents |
|:---|:---|
| `.spaces.json` | `SpaceProfile` serialized under the `__profile__` key |
| `sarthak.db` | AI roadmap — chapters, topics, concepts, file index |
| `chroma.db/` | RAG vector index (sqlite-vec) |
| `roadmap.json` | Session history, milestones, XP, streak (last 200 sessions) |
| `Optimal_Learn.md` | Workspace analysis written after each session |
| `sessions/` | `SpaceSession` JSON records (one per tracked session) |
| `agents/` | Space-scoped agent specs and run history |

Global state:

| File | Contents |
|:---|:---|
| `~/.sarthak_ai/spaces.json` | Global spaces registry |
| `~/.sarthak_ai/active_space.json` | Active space pointer |
| `~/.sarthak_ai/agents/` | Global agent specs and run history |

## ActivityWatch integration

ActivityWatch is the sole source of app-time data. Bridge: `spaces/activity_bridge.py`. The bridge translates AW bucket events into `ActivityContext` objects. This context is used as supplementary (low-weight) signal in curriculum planning. High-quality signals come from self-reports and practice test results.

## Spaces architecture

### SpacesOrchestrator

`spaces/orchestrator.py` — stateless per call. All state lives in `SpaceProfile` on disk. Agents are instantiated once at construction; all are stateless.

```
SpacesOrchestrator
  ├── EnvironmentAgent        scan real OS PATH + importlib; no guessing
  ├── OnboardingAgent         detect background; set is_technical; infer goal
  ├── CurriculumAgent         ZPD-based concept selection
  ├── MathAgent               math at right depth + NumPy equivalent
  ├── TaskBuilderAgent        hands-on task with real-world hook
  ├── ProjectAgent            scaffold end-to-end projects with ROADMAP.md
  ├── EngagementAgent         render content as Markdown for learner background
  ├── AssessmentAgent         evaluate submissions; detect novel approaches
  ├── WorkspaceAgent          reshape directory to expert structure (non-destructive)
  ├── SpacedRepetitionAgent   SM-2 scheduling (pure Python, no LLM)
  ├── BadgeAgent              achievement system (pure Python, no LLM)
  ├── WorkspaceAnalyserAgent  sample workspace; write Optimal_Learn.md
  ├── ExternalToolsAgent      detect VS Code, Colab, Obsidian from filesystem
  ├── PracticeEngine          generate and grade timed tests (LLM / RAG / prompt)
  └── SignalOptimizer         analyze session signals; produce recommendations
```

### Session tracker

`spaces/session_tracker.py` — `SpaceSessionTracker` records `SpaceSession` objects with objective signals: active seconds, idle seconds, files edited, lines written, git commits, and a composite depth score. Saved to `.spaces/sessions/` after `end_session`.

### Signal optimizer

`spaces/optimizer.py` — `SignalOptimizer` reads recent `SpaceSession` records plus `LearnerContext` (self-reports, test results, SRS history) and produces ranked `SessionOptimization` objects. Called after every tracked session and on demand via `sarthak spaces optimize`.

### Practice engine

`spaces/practice.py` — `PracticeEngine` generates `PracticeTest` objects and grades `TestResult` objects. Questions are sourced from the LLM, the workspace RAG index, or a custom prompt. Per-question timers run in a separate thread during interactive CLI sessions.

### RAG system

`spaces/rag.py` — sqlite-vec vector index over workspace files. Supports incremental indexing (mtime-based), full re-index, search, status, and watchdog-based auto-reindex. The RAG tool can be injected into any Pydantic AI agent via `orch.get_rag_tool()`.

### Roadmap database

`spaces/roadmap/db.py` — `RoadmapDB` stores the AI-generated curriculum as a SQLite schema: `roadmaps`, `chapters`, `topics`, `concepts`, `workspace_files`. `sarthak spaces roadmap --regen` calls `agents/roadmap_agents.py` to regenerate via LLM.

## Agent engine

`agents/` — custom scheduled automation.

| File | Responsibility |
|:---|:---|
| `scheduler.py` | Cron tick; runs built-in agents (digest, SRS push, recommendations) |
| `runner.py` | Execute agent spec; inject AW context for space agents |
| `creator.py` | AI-powered agent creation from natural-language description |
| `store.py` | Agent spec + run history persistence |
| `models.py` | `AgentSpec`, `AgentRun`, `AgentScope`, `AgentTool`, `SandboxPolicy` |
| `roadmap_agents.py` | `generate_roadmap`, `build_digest`, `stream_explain` |

Agents can be global (`~/.sarthak_ai/agents/`) or space-scoped (`.spaces/agents/`). Each agent has a cron schedule, a tool list (`web_search`, `shell`, `file_read`, `file_write`, `http_fetch`), and an optional `SandboxPolicy` with per-run resource limits.

## AI layer

All agents use Pydantic AI with LiteLLM for provider resolution. Provider configuration lives in `core/config.py`. All new AI agents must live in `sarthak/agents/` and use shared reusable APIs.

## Data flow (activity intelligence)

```
ActivityWatch (app focus events)
  └── activity_bridge.py
        └── ActivityContext
              └── CurriculumAgent / SummaryAgent / SignalOptimizer
```

```
Capture daemon (window, terminal, snapshot)
  └── storage/write.py → ~/.sarthak_ai/sarthak.db
        └── analytics/ → TUI / Web UI / MCP
```
