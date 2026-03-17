# Agents

Agents are automations that run on a schedule. You describe what you want in plain language and Sarthak handles the rest — timing, tools, and delivery. Results can be sent to Telegram so you get updates on your phone without opening the app.

---

## What agents can do

An agent can do anything Sarthak can do, on a schedule:

- Summarise your learning progress across all Spaces
- Review your weakest concepts and prepare a study plan
- Fetch news or research on a topic you are studying
- Monitor something in your workspace and notify you when it changes
- Generate weekly reports of your focus time and test scores

---

## Creating an agent

### Web UI

Go to **Agents** in the sidebar → click **+ New Agent**. Write a plain-language description of what you want:

- `"Every morning at 8am, send me a summary of what I should study today"`
- `"Every Sunday, send a weekly review of my progress across all Spaces"`
- `"Check for new papers on transformers and summarise them on Fridays"`

Tick **Send results to Telegram** to get output on your phone. Click **Save** — the agent appears in your list and starts running on schedule.

### CLI

```bash
# Global system agent
sarthak agents create "Every morning, send me a digest of what I should study" --telegram

# Space-scoped agent (has access to that Space's roadmap and notes)
sarthak agents create --space --dir ~/ml-project "Daily summary of my notes and weak concepts"
```

---

## Agent types

**Global agents** (`--system`, the default) can span multiple Spaces. They live in `~/.sarthak_ai/agents/`.

**Space-scoped agents** (`--space --dir <path>`) have access to a specific Space's roadmap, learner profile, and notes. They live in `<space_dir>/.spaces/agents/`. Create them from the Space home → **Agents** panel.

---

## Built-in agents

Sarthak includes five built-in agents registered automatically at startup:

| Agent | Schedule | What it does |
|---|---|---|
| **Daily Digest** | Every morning (8am) | Sends a summary of your active Spaces, streak, and suggested focus for the day |
| **SRS Review Push** | Every morning (9am) | Lists every concept due for spaced repetition review today |
| **Recommendations** | Every hour | Updates the suggestions for what to study next based on your recent sessions |
| **Weekly Digest** | Every Sunday (9am) | A full week-in-review: focus time, concepts touched, test scores, recommendations |
| **Workspace Analyser** | Every 30 minutes | Re-checks Spaces, refreshes `Optimal_Learn.md`, and updates lightweight recommendations when files changed |

Built-in agents can be paused but not deleted.

---

## Managing agents

### Web UI

Each agent card shows its name, schedule, and status. You can:

- **Pause / Enable** — stop or resume the schedule at any time
- **Run** — trigger the agent right now and see the output immediately
- **Logs** — review the last 10 runs with timestamps and success/failure status
- **Delete** — remove the agent permanently

### CLI

```bash
sarthak agents list                        # all agents
sarthak agents list --system               # global agents only
sarthak agents list --space                # all space agents
sarthak agents list --dir ~/ml-project    # space agents for one directory

sarthak agents run <agent-id>              # run immediately, ignore schedule
sarthak agents logs <agent-id>             # show recent run history
sarthak agents logs <agent-id> --limit 10  # last 10 runs

sarthak agents enable <agent-id>
sarthak agents disable <agent-id>
sarthak agents delete <agent-id>
sarthak agents delete <agent-id> --force   # skip confirmation
```

---

## Sandbox and safety

Every agent run is wrapped in the sandbox before the LLM executes it:

- **Shell** — disabled unless the agent was explicitly created with shell access
- **File access** — limited to allowed read/write roots
- **Secrets** — the agent prompt is scrubbed for secrets before the LLM sees them; output is scrubbed before storage or delivery
- **Time limit** — system agents default to 120s, space agents to 300s
- **Output cap** — 64 KB per run
- **Web calls** — capped at 10 per run by default

Tune these limits in `config.toml`:

```toml
[agents.sandbox.system]
wall_timeout  = 120
output_cap    = 65536
max_web_calls = 10

[agents.sandbox.space]
wall_timeout  = 300
output_cap    = 65536
max_web_calls = 10
```

---

## Telegram setup

To receive agent results on your phone:

1. Search **@BotFather** on Telegram → `/newbot` → copy the token
2. Get your chat ID from **@userinfobot** on Telegram
3. Go to **Config** in the web UI → Telegram section → add token and chat ID → enable

Or edit `~/.sarthak_ai/config.toml`:

```toml
[telegram]
enabled         = true
bot_token       = "ENC:..."       # sarthak encrypt "1234:AAF..."
allowed_user_id = 123456789
```

Once enabled, any new agent can be created with `--telegram` to deliver results to your phone.

---

## How agents are stored

| Path | Contents |
|---|---|
| `~/.sarthak_ai/agents/registry.json` | Global agent registry |
| `~/.sarthak_ai/agents/<id>/spec.json` | Global agent definition |
| `~/.sarthak_ai/agents/<id>/runs/` | Global run history |
| `<space_dir>/.spaces/agents/<id>/spec.json` | Space-scoped agent definition |
| `<space_dir>/.spaces/agents/<id>/runs/` | Space-scoped run history |

---

## Under the hood

When you type a plain-language description, Sarthak's `creator.py` sends it to your configured LLM and extracts:

- **Schedule** — parsed into a cron expression
- **Tool list** — from `web_search`, `shell`, `file_read`, `file_write`, `http_fetch`
- **Sandbox policy** — resource limits for this specific agent

The agent spec is saved as JSON. The scheduler (`scheduler.py`) ticks every 60 seconds, finds agents whose cron schedule is due, and fires them as async tasks. Each run calls the LLM, captures output, scrubs secrets, and saves the `AgentRun` record.
