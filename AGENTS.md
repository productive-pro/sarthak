# AGENTS.md — Sarthak AI Codebase Guide for AI Agents

This file is the authoritative reference for AI agents (Codex, Claude, Cursor, etc.)
working on the **Sarthak AI** codebase. Read it before touching any code.

---

## Project Overview

Sarthak AI is a **privacy-first productivity intelligence platform for effective learning and
doing projects** built in Python 3.11+. It tracks work activity, manages adaptive learning
"Spaces", and runs scheduled AI agents — all runnable fully offline.

**Primary entry point:** `sarthak` CLI → `src/sarthak/cli/`
**Tech stack:** pydantic-ai, Pydantic v2, FastAPI, Textual TUI, SQLite (aiosqlite), structlog
**Package root:** `src/sarthak/`

---

## Repository Layout

```
src/sarthak/
├── agents/              Custom automation agent engine
│   ├── models.py            AgentSpec, AgentRun, AgentScope, AgentTool, SandboxPolicy
│   ├── creator.py           AI-powered agent creator (NL → AgentSpec)
│   ├── runner.py            Executor: sandbox → LLM → save run → notify
│   ├── scheduler.py         Cron scheduler + built-in system agents
│   ├── store.py             JSON persistence for specs and run history
│   ├── roadmap_agents.py    generate_roadmap / build_digest / stream_explain
│   └── sandbox/             Sandboxing subsystem
├── cli/                 Click CLI commands
├── core/                Config, logging, constants, notifications
│   └── ai_utils/            LLM provider plumbing (multi-provider, fallback chain)
├── features/
│   ├── ai/
│   │   ├── agent.py         ★ PRIMARY API: ask_orchestrator(), stream_orchestrator(),
│   │   │                      _classify_intent(), _compact_history(), analyse_snapshot()
│   │   ├── agents/
│   │   │   ├── orchestrator.py  pydantic-ai Agent[OrchestratorDeps, OrchestratorResult]
│   │   │   ├── summary.py       Daily summary + activity insights agents
│   │   │   └── vision.py        Screenshot analysis agent
│   │   ├── deps.py          OrchestratorDeps, OrchestratorResult, SarthakResult, …
│   │   ├── skills/          User-editable skill snippets (injected into system prompt)
│   │   └── tools/           @agent.tool functions registered on the orchestrator
│   ├── channels/
│   │   ├── __init__.py      ★ dispatch() / stream_dispatch() / save_chat_turn() / load_history_messages()
│   │   ├── telegram/bot.py  Telegram bot (streaming via placeholder-edit loop)
│   │   └── whatsapp/        neonize QR-login bot (streaming via edit_message)
│   ├── mcp/             MCP server
│   └── tui/             Textual TUI
├── orchestrator/
│   └── orchestrator.py  Thin compat shim → features/ai/agent.ask_orchestrator()
├── spaces/              Learning Spaces subsystem
│   ├── models.py            SpaceProfile, LearnerProfile, LearningTask, …
│   ├── agents/              Stateless specialist agents (curriculum, math, assessment, …)
│   ├── store.py             Space profile persistence
│   ├── learner_context.py   build_learner_context() — real signal aggregator
│   ├── memory.py            SOUL/MEMORY/HEARTBEAT per-space files
│   ├── roadmap/             RoadmapDB (SQLite), SRS (SM-2), recommendations
│   ├── roadmap_init.py      ensure_roadmap() — per-space lock via weakref
│   └── orchestrator.py      Spaces session orchestration
└── storage/             SQLite activity store, repositories, vector backends
```

---

## Request Flow (Any Channel → LLM → Response)

```
User input (Web / TUI / Telegram / WhatsApp)
  │
  ├── Web (POST /api/chat)
  │     web/services/chat.py::stream_chat_sse()
  │       → load_history_messages(sid)       [SQLite, once, capped at 40]
  │       → _compact_history() if >32 msgs   [fast model summary]
  │       → agent.run_stream()               [intent-classified groups]
  │           ↳ SSE: tool_start/tool_done events + text chunks
  │       → save_chat_turn(sid, q, reply)
  │
  ├── TUI / Telegram / WhatsApp
  │     features/channels/__init__.py::stream_dispatch() or dispatch()
  │       → load_history_messages(sid)
  │       → features/ai/agent.py::stream_orchestrator() or ask_orchestrator()
  │           → _classify_intent(question)   [keyword → tool_groups, <1ms]
  │           → _compact_history()           [if history > 32 messages]
  │           → get_agent("orchestrator", groups=…)  [cached by (p,m,groups)]
  │           → agent.run() / run_stream()   [pydantic-ai tool loop]
  │       → save_chat_turn(sid, q, reply)
  │
  └── MCP  features/mcp/server.py → dispatch()
```

**Critical invariant:** ALL channels call `ask_orchestrator()` or `stream_orchestrator()`
from `features/ai/agent.py`. Never build an agent directly in a channel adapter.

---

## Context Budget Management

Implemented in `features/ai/agent.py`. Mirrors OpenCode and Claude Code patterns.

| Constant | Value | Meaning |
|---|---|---|
| `_MAX_HISTORY` | 40 | Hard cap: keep last 20 Q/A pairs |
| `_COMPACT_THRESHOLD` | 32 | Compact when history exceeds this |

**`_classify_intent(question)`** — keyword scan (<1 ms) → `frozenset[str]` of tool groups.
Fewer groups = fewer tool schemas injected = smaller system prompt = more room for history.
Groups: `spaces`, `activity`, `system`, `shell`, `rag`, `workspace`, `skills`, `web`.

**`_compact_history(history)`** — when `len(history) > _COMPACT_THRESHOLD`:
1. Split: old half → summarise via fast model (max 200 words)
2. Replace old messages with one synthetic `[Conversation summary]` assistant message
3. Keep recent `_MAX_HISTORY` messages intact
4. Never mutates the input list

**Memory extraction** — `_fire_memory_extraction(cwd, q, reply, action)`:
Fire-and-forget after every learning exchange (Taught/Evaluated/QuickTest).
Appends one bullet to `.spaces/MEMORY.md` if the exchange reveals a behavioural pattern.


---

## Agent Architecture

### 1. Orchestrator Agent (`features/ai/agents/orchestrator.py`)

Single entry point for all user-facing text input (Web, TUI, Telegram, WhatsApp, MCP).

- `Agent[OrchestratorDeps, OrchestratorResult]` built with pydantic-ai
- Tool groups loaded on-demand based on `_classify_intent()` (lean schemas)
- Agent cache keyed on `(provider, model, frozenset(groups))` — rebuilt on config change
- **Do not add heavy logic here.** Route new capabilities to a new `@agent.tool`.

**Call path:**
```
any channel → features/channels/__init__.dispatch/stream_dispatch
           → features/ai/agent.ask_orchestrator / stream_orchestrator
           → features/ai/agents/orchestrator.build(provider, model, tool_groups)
           → Agent.run() / Agent.run_stream()
```

### 2. Custom Agent Engine (`agents/`)

User-defined scheduled automation agents.

| File | Responsibility |
|---|---|
| `models.py` | `AgentSpec`, `AgentRun`, `SandboxPolicy` |
| `creator.py` | NL → `AgentSpec` via LLM |
| `runner.py` | sandbox → `Agent.run()` → save → notify |
| `scheduler.py` | `tick()` every 60s, fires as `asyncio.Task`s |
| `store.py` | JSON spec files + registry |

**Built-in agents** (auto-registered via `ensure_builtin_agents()`):

| agent_id | Schedule | Purpose |
|---|---|---|
| `sarthak-daily-digest` | `0 8 * * *` | Digest per space → Telegram |
| `sarthak-srs-push` | `0 9 * * *` | SRS due reminder → Telegram |
| `sarthak-recommendations` | `0 * * * *` | Hourly next-concept refresh |
| `sarthak-weekly-digest` | `0 9 * * 0` | Week-in-review → Telegram |
| `sarthak-workspace-analyse` | `*/30 * * * *` | Refresh Optimal_Learn.md |

**Thread-safety note:** `_write_recommendations_summary` runs in `asyncio.to_thread` and uses
stdlib `sqlite3` (not aiosqlite) to avoid cross-thread asyncio.Lock issues.

### 3. Spaces Sub-Agents (`spaces/agents/`)

Stateless specialists. Each has one responsibility. Called by the Spaces orchestrator.

`OnboardingAgent` · `CurriculumAgent` · `MathAgent` · `TaskBuilderAgent` · `ProjectAgent`
`EngagementAgent` · `AssessmentAgent` · `WorkspaceAgent` · `SpacedRepetitionAgent`
`BadgeAgent` · `QuickTestAgent` · `WorkspaceAnalyserAgent` · `ExternalToolsAgent` · `EnvironmentAgent`

### 4. Roadmap Agents (`agents/roadmap_agents.py`)

- `generate_roadmap()` — structured output → `Roadmap`
- `build_digest()` — real learner data → Markdown digest + SRS sync
- `stream_explain()` — async SSE token stream for concept explanation

---

## Learning Pipeline

```
build_learner_context(space_dir, profile)    [spaces/learner_context.py]
  → ingest notes, media notes, activity store, test results, sessions, RAG index
  → ConceptEvidence per concept (mastery_confidence = 40%test + 30%understand + 20%notes + 10%qt)
  → LearnerContext { strong, weak, in_progress, srs_due_by_evidence, … }
        ↓
recommend_with_reasons(roadmap, mastered, struggling, review_due)
  [spaces/roadmap/recommend.py]
  → Score: struggle(100) > review(80) > prereq_ready(60) > in_progress(40)
           > tag_overlap(10×) > order_decay(-1×)
  → writes recommendations.md every 30min (no LLM)
        ↓
sync_from_digest(db_path, DigestSignals)     [spaces/roadmap/srs.py]
  → SM-2 upsert per concept based on evidence grade
  → stuck→grade0, test_failed→1, weak→1, no_note→2, strong→4
        ↓
get_due(db_path)                             [spaces/roadmap/srs.py]
  → cards due today or overdue, ordered by urgency
```

**SRS pool safety:** `srs._POOL_LOCK` is an `asyncio.Lock` bound to the main event loop.
All callers (`get_due`, `sync_from_digest`, `upsert_card`) run in the main event loop. ✅
`_write_recommendations_summary` uses stdlib `sqlite3` — safe in worker threads. ✅

---

## Space Memory Files

| File | Created | Updated | Purpose |
|---|---|---|---|
| `SOUL.md` | space init | never | Agent identity, domain goal, learner rules |
| `MEMORY.md` | space init | post-LLM (fire-and-forget) | Behavioural patterns |
| `HEARTBEAT.md` | space init | session end | SRS due + streak |
| `memory/YYYY-MM-DD.md` | first session | session end | Raw daily session logs |

**Read path:** `read_context_block_async(space_dir, include_heartbeat)` — cached 120s.
Default: SOUL + MEMORY only (~600 chars). HEARTBEAT only for SRS/streak questions.

**Write path:** All writes are atomic (write-to-tmp → rename).
Weekly `distill_memory()` rewrites MEMORY.md as a clean deduplicated bullet list.

---

## Sandbox System (`agents/sandbox/`)

Every custom agent run is wrapped by `enforce_sandbox(spec, execute_fn)`:

```
enforce_sandbox(spec, execute_fn)
  ├── build_sandbox_config(spec)     # derive SandboxConfig from AgentSpec
  ├── scrub(spec.prompt)             # strip secrets before LLM
  ├── asyncio.wait_for(execute_fn, timeout=cfg.wall_timeout)
  ├── scrub(output)                  # strip secrets from output
  └── truncate to cfg.output_cap
```

Key fields: `allow_shell`, `allow_web`, `allow_file_read`, `allow_file_write`,
`write_roots`, `read_roots`, `wall_timeout` (120s), `output_cap` (64 KB).

---

## Key Conventions

1. **All free-text → orchestrator.** Never add routing logic in channel adapters.
2. **Use `ask_orchestrator()` / `stream_orchestrator()`** — never call `get_agent()` directly
   in channel code. These functions apply intent classification + history compaction.
3. **Stats only from storage** — activity tools return aggregates, never raw rows.
4. **Stateless sub-agents** — pass everything they need on each call.
5. **JSON from LLM** — end system prompt with `Output ONLY valid JSON: {...}`.
   Parse with `parse_json_response(raw)`. Always provide a `fallback` dict.
6. **Pydantic v2** — `model.model_dump_json()`, `Model.model_validate_json()`.
   Do NOT use v1 `.dict()` / `.parse_raw()`.
7. **Async throughout** — all I/O is `async`. Fire-and-forget via `asyncio.create_task()`.
8. **Structured logging** — `get_logger(__name__)`, log with key-value pairs.
9. **`_write_recommendations_summary` is sync (stdlib sqlite3)** — safe for `asyncio.to_thread`.

---

## Adding New Functionality

### New orchestrator tool
1. Implement in `features/ai/tools/` following existing patterns.
2. Register in `features/ai/agents/orchestrator.py` with `@agent.tool` or `@agent.tool_plain`.
3. Add keyword(s) to `_KW` in `features/ai/agent._classify_intent()` so the tool is
   included only when needed (keeps system prompt lean).

### New built-in system agent
1. Add dict to `_BUILTIN_AGENTS` in `agents/scheduler.py`.
2. Add handler `_run_<n>_agent(spec)` and register in `_HANDLERS`.
3. Delegate to existing helpers (`build_digest`, `get_due`, etc.).

### New AgentTool capability
1. Add enum to `AgentTool` in `agents/models.py`.
2. Add `_make_<tool>_tool()` in `agents/runner.py`.
3. Register in `_build_tools()` gated on `SandboxConfig.allow_*`.
4. Add `allow_*` field to `SandboxConfig` in `sandbox/config.py`.

---

## File Locations Quick Reference

| What | Where |
|---|---|
| Primary LLM API | `features/ai/agent.py` |
| Channel dispatch | `features/channels/__init__.py` |
| Orchestrator agent build | `features/ai/agents/orchestrator.py` |
| Agent registry + cache | `features/ai/agents/__init__.py` |
| Provider plumbing | `core/ai_utils/multi_provider.py` |
| App config | `~/.sarthak_ai/config.toml` |
| Space data | `<space_dir>/.spaces/` |
| SRS database | `<space_dir>/.spaces/sarthak.db` |
| Recommendations | `<space_dir>/.spaces/recommendations.md` |
| Space Memory files | `<space_dir>/.spaces/{SOUL,MEMORY,HEARTBEAT}.md` |
| Global agent storage | `~/.sarthak_ai/agents/` |
| Prompt history logs | `~/.sarthak_ai/prompt_history/` |
| Vector index | `<space_dir>/.spaces/rag/` |

---

## Dead / Tombstone Files

These files are kept for git blame readability but contain no live code:

| File | Superseded by |
|---|---|
| `agents/prompts/roadmap.py` | `data/agents/**/*.md` |
| `agents/_recs_helper.py` | `agents/scheduler._load_roadmap_sync` |
| `spaces/roadmap_tracker.py` | `spaces/roadmap/db.RoadmapDB` |
| `orchestrator/orchestrator.py` | `features/ai/agent.ask_orchestrator` (now a 4-line shim) |
| `features/channels/whatsapp/bot.py` | `neonize_bot.py` |
| `features/channels/whatsapp/client.py` | `neonize_bot.send_message_standalone` |
