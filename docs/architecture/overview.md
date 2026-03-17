# System Architecture

Sarthak is composed of two independent subsystems — the **Spaces mastery engine** and the **custom agent engine** — that share the same orchestration layer, AI provider abstraction, and storage primitives.

---

## Package layout

```
src/sarthak/
  cli/              # Click CLI — spaces_cli, agents_cli, analytics_cli, copilot_cli
  orchestrator/     # Service runner — starts web server + agent scheduler
  features/
    ai/             # Pydantic AI orchestrator, specialist tools, LLM provider resolution
    mcp/            # MCP server (stdio transport)
    tui/            # Textual terminal dashboard
    channels/       # Telegram and WhatsApp bots, channel dispatch
  core/             # Config loader, logging (structlog), encryption utilities, AI utilities
  storage/          # Repository pattern: SQLite / Postgres / DuckDB + vector backends
  spaces/           # Mastery engine — SpacesOrchestrator, sub-agents, SRS, RAG, roadmap
  agents/           # Custom agent engine — scheduler, runner, creator, store, models
  analytics/        # Focus, resume, weekly, trends reports
  web/              # React 19 + FastAPI web UI (served from web/react_dist/)
```

---

## Request flow (any channel → LLM → response)

```
User input (Web / TUI / Telegram / WhatsApp / MCP)
  │
  ├── Web (POST /api/chat)
  │     web/services/chat.py::stream_chat_sse()
  │       → load_history_messages(sid)       [SQLite, capped at 40]
  │       → _compact_history() if >32 msgs   [fast model summary]
  │       → agent.run_stream()               [intent-classified tool groups]
  │           ↳ SSE: tool_start/tool_done events + text chunks
  │       → save_chat_turn(sid, q, reply)
  │
  ├── TUI / Telegram / WhatsApp
  │     features/channels/__init__.py::stream_dispatch()
  │       → load_history_messages(sid)
  │       → features/ai/agent.py::stream_orchestrator()
  │           → _classify_intent(question)   [keyword scan, <1ms]
  │           → _compact_history()           [if history > 32 messages]
  │           → get_agent("orchestrator", groups=…)  [cached per provider+model+groups]
  │           → agent.run() / run_stream()   [pydantic-ai tool loop]
  │       → save_chat_turn(sid, q, reply)
  │
  └── MCP   features/mcp/server.py → dispatch()
```

**Critical rule:** All channels call `ask_orchestrator()` or `stream_orchestrator()` from `features/ai/agent.py`. No channel does its own routing.

---

## Context budget management

| Constant | Value | Meaning |
|---|---|---|
| `_MAX_HISTORY` | 40 | Hard cap: keep last 20 Q/A pairs |
| `_COMPACT_THRESHOLD` | 32 | Compact when history exceeds this |

**Intent classification** (`_classify_intent`) — keyword scan in under 1ms → returns a `frozenset[str]` of tool groups. Fewer groups = smaller system prompt = more room for history.

Tool groups: `spaces`, `activity`, `system`, `shell`, `rag`, `workspace`, `skills`, `web`.

**History compaction** — when `len(history) > 32`: summarise the old half via a fast model (max 200 words), replace with a synthetic `[Conversation summary]` message, keep recent messages intact. Never mutates the input list.

---

## Spaces architecture

### SpacesOrchestrator

`spaces/orchestrator.py` — stateless per call. All state lives in `SpaceProfile` on disk. Sub-agents are instantiated once; all are stateless.

```
SpacesOrchestrator
  ├── EnvironmentAgent        scan real OS PATH; no guessing
  ├── OnboardingAgent         detect background; is_technical flag; infer goal
  ├── CurriculumAgent         ZPD-based concept selection
  ├── MathAgent               math at right depth + NumPy equivalent
  ├── TaskBuilderAgent        hands-on task with real-world hook
  ├── ProjectAgent            scaffold end-to-end projects with ROADMAP.md
  ├── EngagementAgent         render content for learner background
  ├── AssessmentAgent         evaluate submissions; detect novel approaches
  ├── WorkspaceAgent          reshape directory to expert structure (non-destructive)
  ├── SpacedRepetitionAgent   SM-2 scheduling (pure Python, no LLM)
  ├── BadgeAgent              achievement system (pure Python, no LLM)
  ├── WorkspaceAnalyserAgent  sample workspace; write Optimal_Learn.md
  ├── ExternalToolsAgent      detect VS Code, Colab, Obsidian from filesystem
  ├── PracticeEngine          generate and grade timed tests (LLM / RAG / custom prompt)
  └── SignalOptimizer         analyze session signals; produce recommendations
```

### Learning pipeline

```
build_learner_context(space_dir, profile)
  → ingest notes, media notes, activity store, test results, sessions, RAG index
  → ConceptEvidence per concept (mastery_confidence = 40%test + 30%understand + 20%notes + 10%qt)
  → LearnerContext { strong, weak, in_progress, srs_due_by_evidence, … }
        ↓
recommend_with_reasons(roadmap, mastered, struggling, review_due)
  → Score: struggle(100) > review(80) > prereq_ready(60) > in_progress(40)
           > tag_overlap(10×) > order_decay(-1×)
  → writes recommendations.md every 30min (no LLM)
        ↓
sync_from_digest(db_path, DigestSignals)
  → SM-2 upsert per concept based on evidence grade
  → stuck→grade0, test_failed→1, weak→1, no_note→2, strong→4
        ↓
get_due(db_path) → cards due today, ordered by urgency
```

---

## Agent engine

| File | Responsibility |
|---|---|
| `agents/scheduler.py` | Cron tick every 60s; fires built-in agents as async tasks |
| `agents/runner.py` | Execute agent spec; inject context; sandbox enforcement |
| `agents/creator.py` | AI-powered agent creation from natural-language description |
| `agents/store.py` | Agent spec + run history persistence (JSON) |
| `agents/models.py` | `AgentSpec`, `AgentRun`, `AgentScope`, `AgentTool`, `SandboxPolicy` |
| `agents/roadmap_agents.py` | `generate_roadmap`, `build_digest`, `stream_explain` |

Every run passes through `agents/sandbox/`, which enforces: tool gating, path guards, time and memory limits, secret scrubbing, and output truncation.

---

## AI layer

All agents use Pydantic AI with a 3-tier `FallbackModel` chain built from `config.toml → [ai.fallback]`. If the primary model fails, Sarthak retries with fallback1, then fallback2 — agents never crash on transient provider errors.

Provider configuration lives in `core/ai_utils/multi_provider.py`. Adding a new provider requires one builder function and one entry in `_BUILDERS`.

---

## Storage

All activity data lives in SQLite at `~/.sarthak_ai/sarthak.db` by default. Alternative backends are available via `config.toml → [storage]`.

Business logic never imports DB drivers directly — everything goes through the repository pattern in `storage/`:

```python
from sarthak.storage.factory import get_activity_repo, get_embedding_repo

repo  = get_activity_repo()            # process singleton, thread-safe
erepo = await get_embedding_repo(dir)  # per-space singleton, async-safe
```

**Activity backends:** SQLite (default), PostgreSQL, DuckDB, LibSQL  
**Vector backends:** sqlite-vec (default, embedded), Qdrant, Chroma, pgvector, LanceDB, Weaviate

---

## Key data locations

| Path | Contents |
|---|---|
| `~/.sarthak_ai/sarthak.db` | Activity events (SQLite) |
| `~/.sarthak_ai/agents/` | Global agent specs and run history |
| `~/.sarthak_ai/spaces.json` | Global spaces registry |
| `<space_dir>/.spaces/sarthak.db` | AI roadmap — chapters, topics, concepts |
| `<space_dir>/.spaces/rag/` | Vector index |
| `<space_dir>/.spaces/roadmap.json` | Session history, XP, streak |
| `<space_dir>/.spaces/sessions/` | `SpaceSession` JSON records |
| `<space_dir>/.spaces/agents/` | Space-scoped agent specs and runs |
| `<space_dir>/.spaces/{SOUL,USER,HEARTBEAT,MEMORY}.md` | Space memory files |
| `<space_dir>/.spaces/memory/YYYY-MM-DD.md` | Daily session logs |
| `<space_dir>/.spaces/Optimal_Learn.md` | Workspace analysis |

---

## Extension points

**New orchestrator tool:**
1. Implement in `features/ai/tools/`, register with `@agent.tool` in `features/ai/agents/orchestrator.py`
2. Add keywords to `_KW` in `_classify_intent()` so the tool is included only when needed

**New built-in system agent:**
1. Add entry to `_BUILTIN_AGENTS` in `agents/scheduler.py`
2. Add handler `_run_<n>_agent(spec)` and register in `_HANDLERS`

**New custom agent capability:**
1. Add enum to `AgentTool` in `agents/models.py`
2. Add `_make_<tool>_tool()` in `agents/runner.py`
3. Add `allow_*` field to `SandboxConfig` in `agents/sandbox/config.py`
