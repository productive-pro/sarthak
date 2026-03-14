# System Architecture

Sarthak is composed of two independent subsystems — the Spaces mastery engine and the custom agent engine — that share the same orchestration layer, AI provider abstraction, and storage primitives.

## High-level layout

```
src/sarthak/
  cli/                # Click entrypoint — spaces_cli, agents_cli, analytics_cli
  orchestrator/       # Service runner — starts all daemons
  features/
    ai/               # Pydantic AI orchestrator, specialist tools, LLM provider resolution
    capture/          # Window, terminal, snapshot daemons
    mcp/              # MCP server (stdio transport)
    tui/              # Textual dashboard
    channels/         # Telegram and other notification channels
  core/               # Config loader, logging (structlog), encryption utilities
  storage/            # Repository pattern: SQLite / Postgres / DuckDB + vector backends
  spaces/             # Mastery engine — see Spaces section
  agents/             # Scheduler, runner, creator, store, models
  analytics/          # Focus, resume, debug, weekly, trends reports
  web/                # React 19 + FastAPI web UI (served from web/react_dist/)
```

## Single-orchestrator rule

All channels (Telegram, TUI, Web) route through `features/channels/` → `orchestrator/orchestrator.py` → `features/ai/agent.py`. No channel does its own routing.

All scheduled automation runs through `agents/scheduler.py`, started as the `agent_scheduler` service.

## Storage

All activity data lives in SQLite at `~/.sarthak_ai/sarthak.db` by default (via the repository pattern in `storage/`). Alternative backends — PostgreSQL, DuckDB, and LibSQL — are also available through `config.toml`.

Spaces data lives inside each workspace under `.spaces/`:

| Path | Contents |
|:---|:---|
| `.spaces/sarthak.db` | AI roadmap — chapters, topics, concepts, file index |
| `.spaces/rag/` | Default local RAG storage area, including `sarthak.vec` for sqlite-vec |
| `.spaces/roadmap.json` | Session history, XP, streak (last 200 sessions) |
| `.spaces/Optimal_Learn.md` | Workspace analysis written after each session |
| `.spaces/sessions/` | `SpaceSession` JSON records (one per tracked session) |
| `.spaces/agents/` | Space-scoped agent specs and run history |
| `.spaces/SOUL.md` | Agent identity for this domain (set once at init) |
| `.spaces/USER.md` | Live learner state snapshot (updated every `save_profile`) |
| `.spaces/HEARTBEAT.md` | SRS due + daily checks (updated hourly) |
| `.spaces/MEMORY.md` | Long-term learner patterns (LLM distill, updated weekly) |
| `.spaces/memory/YYYY-MM-DD.md` | Raw daily session logs |

Global state:

| Path | Contents |
|:---|:---|
| `~/.sarthak_ai/sarthak.db` | Activity events (SQLite) |
| `~/.sarthak_ai/spaces.json` | Global spaces registry |
| `~/.sarthak_ai/active_space.json` | Active space pointer |
| `~/.sarthak_ai/agents/` | Global agent specs and run history |

## Universal storage layer

Business logic never imports DB drivers directly. Everything goes through the repository pattern in `storage/`:

```python
from sarthak.storage.factory import get_activity_repo, get_embedding_repo, get_cache

repo  = get_activity_repo()            # process singleton, thread-safe
erepo = await get_embedding_repo(dir)  # per-space singleton, async-safe
cache = get_cache()                    # Redis or LRU, transparent fallback
```

**Activity backends** (`storage/backends/`): SQLite (default), PostgreSQL, DuckDB, LibSQL.

**Vector backends** (`storage/vector/`): sqlite-vec (default, embedded offline), Qdrant, Chroma, pgvector, LanceDB, Weaviate.

Backend is set in `config.toml → [storage]`. Migrate between backends with `sarthak storage migrate`.

## ActivityWatch integration

ActivityWatch is the sole source of app-time data. The bridge in `spaces/activity_bridge.py` translates AW bucket events into `ActivityContext` objects. This context is a low-weight supplementary signal in curriculum planning. High-quality signals come from self-reports and practice test results.

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

### Space memory files

Each Space has a set of persistent Markdown files read and written by agents. They form a running context block that the orchestrator injects at the start of every session.

| File | Updated by | Purpose |
|:---|:---|:---|
| `SOUL.md` | Set once at init | Agent identity and domain framing |
| `USER.md` | Every `save_profile()` | Live learner state snapshot |
| `HEARTBEAT.md` | Hourly (`sarthak-memory-sync`) | SRS due counts + daily check |
| `MEMORY.md` | Weekly (LLM distill, Sundays) | Long-term learner patterns |
| `memory/YYYY-MM-DD.md` | Every session end | Raw session logs |

Read path: `read_context_block_async(space_dir)` — cached in Redis/LRU for 120 s, invalidated on every write.

### Session tracker

`spaces/session_tracker.py` — records `SpaceSession` objects: active seconds, idle seconds, files edited, lines written, git commits, composite depth score. Saved to `.spaces/sessions/` after `end_session`.

### Signal optimizer

`spaces/optimizer.py` — `SignalOptimizer` reads recent `SpaceSession` records plus `LearnerContext` (self-reports, test results, SRS history) and produces ranked `SessionOptimization` objects. Called after every session and on demand via `sarthak spaces optimize`.

### Practice engine

`spaces/practice.py` — `PracticeEngine` generates `PracticeTest` objects and grades `TestResult` objects. Questions are sourced from the LLM, workspace RAG index, or a custom prompt.

### RAG system

`spaces/rag.py` — vector index over workspace files via the configured vector backend (sqlite-vec by default). Supports incremental indexing (mtime-based), full re-index, hybrid BM25+vector search, status, and watchdog-based auto-reindex. Injected into agents via `orch.get_rag_tool()`.

### Roadmap database

`spaces/roadmap/db.py` — `RoadmapDB` stores the AI-generated curriculum as a SQLite schema: chapters, topics, concepts, workspace files. Regenerate with `sarthak spaces roadmap --regen`.

## Agent engine

`agents/` — custom scheduled automation.

| File | Responsibility |
|:---|:---|
| `scheduler.py` | Cron tick; runs built-in agents such as digest, SRS push, recommendations, and workspace analysis |
| `runner.py` | Execute agent spec; inject context; sandbox enforcement |
| `creator.py` | AI-powered agent creation from natural-language description |
| `store.py` | Agent spec + run history persistence |
| `models.py` | `AgentSpec`, `AgentRun`, `AgentScope`, `AgentTool`, `SandboxPolicy` |
| `roadmap_agents.py` | `generate_roadmap`, `build_digest`, `stream_explain` |

Agents can be global (`~/.sarthak_ai/agents/`) or space-scoped (`.spaces/agents/`). Each agent has a cron schedule, a tool list (`web_search`, `shell`, `file_read`, `file_write`, `http_fetch`), and an optional `SandboxPolicy` with per-run resource limits.

Every run passes through `agents/sandbox/`, which enforces tool gating, path guards, time and memory limits, secret scrubbing, and output truncation before results are stored or delivered.

## AI layer

All agents use Pydantic AI with a 3-tier `FallbackModel` chain built from `config.toml`. Provider configuration lives in `core/ai_utils/`. If the primary model fails, Sarthak retries with fallback1, then fallback2 — agents never crash on transient provider errors.

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

## Extension points

- Add a new orchestrator tool in `features/ai/tools/`, then register it in `features/ai/agents/orchestrator.py`
- Add a new custom agent capability by extending `AgentTool`, `agents/runner.py`, and `agents/sandbox/config.py`
- Add a new built-in system agent in `agents/scheduler.py` and keep its handler narrow
