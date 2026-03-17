# CLI Reference

All Sarthak functionality is available from the `sarthak` command. Run `sarthak --help` or `sarthak <command> --help` for detailed usage.

---

## Core commands

```bash
sarthak configure                  # Interactive setup wizard (provider, key, Telegram)
sarthak configure --mode quick     # Minimal setup — just provider and key
sarthak orchestrator               # Start all services in the foreground (Ctrl+C to stop)
sarthak status                     # Check config, database, and web server health
sarthak tui                        # Open terminal UI
sarthak mcp                        # Start MCP server (stdio transport)
sarthak resume                     # Show most recent Space session summary
sarthak summarize                  # Generate AI summary for today
sarthak summarize --date 2026-03-10  # Summary for a specific date
sarthak encrypt "sk-..."           # Encrypt a secret → ENC:...
sarthak decrypt "ENC:..."          # Decrypt a secret back to plain text
sarthak reset                      # Wipe all data and config (with confirmation)
sarthak reset --force              # Wipe without confirmation
sarthak uninstall                  # Remove config only, or full package uninstall
```

---

## Service management

```bash
sarthak service install     # Install + start as background service
sarthak service uninstall   # Stop + remove the service
sarthak service status      # Show service status
```

Platform details:
- **Linux** — systemd user service (`~/.config/systemd/user/sarthak-orchestrator.service`)
- **macOS** — launchd LaunchAgent (`~/Library/LaunchAgents/com.sarthak.orchestrator.plist`)
- **Windows** — Task Scheduler job (`SarthakOrchestrator`)

---

## Spaces commands

```bash
# Create a new Space
sarthak spaces init \
  --dir ~/my-project \
  --type data_science \
  --background "Python dev, 2 years" \
  --goal "learn ML for production" \
  --name "Alice"

# List and manage spaces
sarthak spaces list                        # list all spaces (* marks the active one)
sarthak spaces activate --dir ~/my-project  # set active space
sarthak spaces status --dir .               # show mastery status and progress
sarthak spaces context --dir .              # print active space context summary

# Learning sessions
sarthak spaces learn --dir .               # quick session — next concept, math, task
sarthak spaces session --dir . --concept "gradient descent" --minutes 45
sarthak spaces session --dir . --type struggle_fix --concept "backpropagation"

# Practice and evaluation
sarthak spaces practice --type concept --scope "gradient descent"
sarthak spaces practice --type topic --scope beginner --source rag
sarthak spaces practice --source prompt --prompt "focus on edge cases"
sarthak spaces practice --type full_space --time 90
sarthak spaces evaluate "gradient descent" --dir . --file ./solution.py

# Roadmap
sarthak spaces roadmap --dir .             # view curriculum roadmap
sarthak spaces roadmap --dir . --regen    # regenerate roadmap via AI
sarthak spaces roadmap-sync --dir .       # re-index files + rebuild RAG vectors
sarthak spaces refine --dir . --answers "beginner, practical focus"  # refine after init

# Document search (RAG)
sarthak spaces rag index --dir .           # index workspace files (incremental)
sarthak spaces rag index --dir . --full   # full re-index
sarthak spaces rag search --dir . --query "numpy broadcasting"
sarthak spaces rag status --dir .          # show index size and doc count
sarthak spaces rag watch --dir .           # auto-reindex on file changes

# Optimization and project
sarthak spaces optimize --dir . --last 10  # personalized recommendations from recent sessions
sarthak spaces project --dir .             # scaffold an end-to-end project
sarthak spaces quick --dir .              # 5-minute micro-task
sarthak spaces setup --dir .              # scan environment, set up expert tools

# Profile
sarthak spaces profile --dir . --background "doctor" --goal "clinical ML"
```

**Supported types for `--type`:** `data_science`, `ai_engineering`, `software_engineering`, `medicine`, `education`, `exam_prep`, `business`, `research`, `custom`

---

## Agents commands

```bash
# Create agents
sarthak agents create "Every morning, send me what I should study" --telegram
sarthak agents create --system "Daily AI news digest"
sarthak agents create --space --dir ~/ml-space "Weekly notes summary"

# List
sarthak agents list                        # all agents
sarthak agents list --system               # global agents only
sarthak agents list --space                # space-scoped agents only
sarthak agents list --dir ~/ml-space      # agents for one specific space

# Run and manage
sarthak agents run <agent-id>              # run immediately (ignore schedule)
sarthak agents logs <agent-id>             # recent run history
sarthak agents logs <agent-id> --limit 10  # last 10 runs
sarthak agents enable <agent-id>
sarthak agents disable <agent-id>
sarthak agents delete <agent-id>
sarthak agents delete <agent-id> --force   # skip confirmation
```

---

## Channels

```bash
sarthak channels status     # show Telegram, WhatsApp, and web UI connection status
```

---

## GitHub Copilot

```bash
sarthak copilot login       # device-flow authentication (opens browser)
```

---

## Storage

```bash
sarthak storage status                     # show active backends
sarthak storage migrate --from sqlite --to postgres   # migrate between backends
```

---

## Spaces session types (`--type` for `sarthak spaces session`)

| Type | When to use |
|---|---|
| `new_concept` (default) | Starting a fresh concept for the first time |
| `review` | Revisiting a concept you've already seen |
| `struggle_fix` | You're stuck on something specific — gets targeted help |
| `project_step` | Working on an ongoing project milestone |

---

## Practice sources (`--source` for `sarthak spaces practice`)

| Source | What it does |
|---|---|
| `llm` (default) | Questions generated by the AI |
| `rag` | Questions sourced from your own notes and workspace files |
| `prompt` | Questions generated from a custom prompt you provide via `--prompt` |
