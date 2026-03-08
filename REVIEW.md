# Code Review — Sarthak

## Bugs

### 1. `_INIT_DONE` race condition in `storage/db.py`
`init_db()` sets `_INIT_DONE = True` before `db.commit()` completes. Under
concurrent async callers the schema may not be applied yet.
**Fix**: set flag only after commit.

### 2. `spaces_cli.py` — `spaces_practice` imports unused `SelfReport`
`from sarthak.spaces.models import SelfReport` is imported but never used in
`spaces_practice`. Minor but produces a noise warning.

### 3. `notes.py` — `asyncio.get_event_loop()` deprecated (Python 3.10+)
`loop = asyncio.get_event_loop()` raises `DeprecationWarning` and may return
a closed loop when called outside an async context.  The two call sites in
`take_concept_note` / `sync_frontend_note` use it only to schedule background
tasks; both are already `async def`, so the loop is running — use
`asyncio.get_running_loop()`.

### 4. `rag.py` — `start_watcher` calls `asyncio.run()` inside a background
thread that may share an event loop with the main process.
When the main process already has a running loop (e.g. under uvicorn/fastapi),
`asyncio.run()` raises `RuntimeError: This event loop is already running`.
**Fix**: use `asyncio.new_event_loop()` inside the thread.

### 5. `session_tracker.py` — `asyncio.wait_for(asyncio.shield(...))` misuse
`asyncio.shield(self._stop.wait())` creates a new coroutine on each poll loop
iteration; `wait_for` then cancels the inner `shield` wrapper on timeout, but
the underlying `_stop.wait()` coroutine leaks because `shield` detaches it.
Over long sessions this creates hundreds of leaked coroutines.
**Fix**: replace with `asyncio.wait_for(asyncio.sleep(self.POLL_INTERVAL))`.

### 6. `spaces/store.py` — `_registry_cache` not thread-safe
The module-level `_registry_cache` is mutated without a lock. Under a
multi-threaded server (e.g. Gradio / Uvicorn `--workers 1 --threads N`) two
writers racing can corrupt the list. Use `threading.Lock`.

### 7. `orchestrator.py` (`SpacesOrchestrator.run_practice`) — blocking
`input()` on the async event loop
`spaces_cli.py` runs the whole coroutine with `asyncio.run()`, which is fine,
but `run_practice(interactive=True)` calls `input()` directly inside an `async
def`. This blocks the event loop thread for the entire duration the user is
typing, which will block every other `asyncio` task running in the same loop.
**Fix**: wrap `input()` calls with `await asyncio.to_thread(input, ...)`.

### 8. `agents/runner.py` — `_execute` ignores `retries` from config
`Agent(... retries=retries)` is set correctly in `run_llm` (in `_base.py`),
but `_execute` calls `Agent(...)` without `retries`, so agent tool calls have
no retry on transient errors.

### 9. `spaces/practice.py` — `load_test_results` silently swallows parse errors
The `for line in lines` loop has no `try/except`; a single corrupt JSON line
raises `ValidationError` and discards all subsequent results.
**Fix**: wrap with `try/except Exception: continue`.

### 10. `learner_context.py` — `_ingest_test_results` running-average formula wrong
```python
ev.test_percent = (ev.test_percent * (ev.test_attempts - 1) + 0) / ev.test_attempts
```
`ev.test_attempts` is incremented **before** the formula runs, so the weight
is off-by-one on the very first attempt (denominator is 1 but no prior value
exists). Identical bug in `_ingest_activity_store` for `practice_test`.
**Fix**: increment after the formula, or use a running-sum approach.

---

## Improvements

### A. `_now()` is duplicated in 5+ modules
`spaces/models.py`, `agents/models.py`, `spaces/store.py`, `agents/store.py`,
`spaces/roadmap_tracker.py` all define the same `def _now() -> str`.
**Fix**: move to `core/constants.py` or a tiny `core/utils.py` and import.

### B. `notes.py` — `NoteRecord` is a `@dataclass` but the rest of the codebase uses Pydantic
`NoteRecord` uses `@dataclass` with manual `to_dict()` / `from_dict()`.
Everything else — `SpaceProfile`, `AgentSpec`, `TestResult` etc. — uses
Pydantic `BaseModel` with `.model_dump()` / `.model_validate()`. This means
notes are not validated, have no coercion, and require manual serialization.
**Fix**: convert `NoteRecord` to `BaseModel`.

### C. `spaces_cli.py` — `spaces_practice` icon dict built on every optimization
```python
icon = {"high": "🔴", "medium": "🟡", "low": "🟢"}.get(o.priority, "")
```
Appears twice (also in `spaces_tracked_session`). Extract as a module-level
constant `_PRIORITY_ICONS`.  Also: per AGENTS.md "No emojis" — these should
be removed or replaced with `[HIGH]` / `[MED]` / `[LOW]`.

### D. `optimizer.py` — `analyze()` (legacy sync) rebuilds sessions and tests
every call. If called from a hot path (e.g. Gradio refresh), this reads N
JSONL files on each request. Add a simple TTL cache or accept a pre-built
`LearnerContext`.

### E. `storage/db.py` — no connection pooling
Every helper opens and closes a fresh `aiosqlite.connect()` per query via the
`connect()` context manager. For high-frequency endpoints (Gradio, web API)
this creates a new file-handle on every call. Use a single per-process
connection with WAL mode (already set) and pass it around, or use
`aiosqlite` connection reuse.

### F. `sub_agents.py` `EnvironmentAgent.scan` — `importlib.util.find_spec`
inside a loop with no package-name normalisation
```python
if importlib.util.find_spec(pkg.replace("-", "_")):
```
`find_spec` may emit `ModuleNotFoundError` for packages with namespace issues
(e.g. `google-cloud-*`). The bare `except Exception: pass` hides these. This
is fine functionally, but the loop over ~25 packages runs synchronously inside
an `async def scan()`. Wrap in `asyncio.to_thread` so it doesn't block the
event loop.

### G. `rag.py` — `_open_db` / `_upsert_chunks` not async but called from async
The SQLite writes in `_upsert_chunks` are synchronous (`sqlite3` module) and
may block the event loop for large indexing jobs. Wrap in `asyncio.to_thread`.

### H. `roadmap_tracker.py` `record_session_to_roadmap` — synchronous JSON read/write
called from `asyncio.to_thread` in the orchestrator, which is correct. But the
`init_roadmap` → `_build_phases` → `get_domain` import chain runs every time
a session is recorded, even when phases have not changed. Cache the domain
lookup at module level.

### I. `agents/scheduler.py` `_is_due` — croniter called on every tick per agent
`croniter.match(spec.schedule, now)` re-parses the cron expression on every 60 s
tick for every agent. With many agents this is wasteful. Use `spec.next_run_at`
(already computed and stored) as the sole gate; only recompute on miss.

### J. `spaces/store.py` `_registry_cache` comment warns about multi-worker staleness
but the warning is buried in a comment. The `_registry_cache` should use a
proper invalidation mechanism. Simplest fix for single-worker: use
`functools.lru_cache(maxsize=1)` with a file-mtime check.

---

## Files to merge

### `spaces/store.py` absorbs `spaces/profile_store.py` — already done
AGENTS.md says `profile_store.py` is "a shim — re-exports from store.py".
Confirm it is genuinely empty and delete it (or it will confuse future readers
into thinking it has distinct logic).

### `storage/read.py` + `storage/write.py` → `storage/helpers.py`
These two files are small (~60 + ~80 lines), always imported together, and
logically cohesive (SQLite CRUD). Merge into a single `storage/helpers.py`
(or keep as `storage/db_helpers.py`) to reduce module count without losing
clarity. The `db.py` module keeps schema/init.

### `spaces/optimizer.py` `analyze()` (sync legacy) vs `analyze_from_context()`
The sync `analyze()` path duplicates logic that already exists in the
context-driven path. Remove `analyze()` and `_analyze_sync_fallback()`; callers
that need a sync result can `asyncio.run(build_learner_context(...))` once.
The only caller is `spaces_cli.py` `spaces_optimize`, which already uses
`asyncio.run`.
