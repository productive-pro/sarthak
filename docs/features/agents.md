# Agents

Agents are automations that run on a schedule. You describe what you want in plain language and Sarthak sets up the rest — timing, tools, and delivery. Results can be sent to you on Telegram.

Everything described here is available in the web UI under **Agents**. The [Web UI guide](web.md) has a full walkthrough of the interface.

---

## What agents can do

An agent can do anything Sarthak can do, on a schedule:

- Summarise your learning progress across Spaces
- Review your weakest concepts and prepare a study plan
- Fetch news or research on a topic you are studying
- Monitor something in your workspace and notify you when it changes
- Generate weekly reports of your focus time and test scores

---

## Creating an agent

Go to **Agents** and click **+ New Agent**. Write a plain-language description of what you want. A few examples:

- "Every morning at 8am, send me a summary of what I should study today"
- "Every Sunday, send a weekly review of my progress across all Spaces"
- "Whenever I finish a session, remind me of the three weakest concepts from today"

Tick **Send results to Telegram** if you want the output delivered to your phone.

Sarthak reads your description, decides on a schedule and the right tools, and saves the agent. You can see and run it immediately from the Agents page.

Under the hood, each saved agent becomes an `AgentSpec` with:

- a cron schedule
- a prompt
- a tool list such as `web_search`, `shell`, `file_read`, `file_write`, or `http_fetch`
- an optional sandbox policy with per-run limits

The scheduler checks due agents every 60 seconds and starts runs in the background.

---

## Built-in agents

Sarthak includes five built-in agents that are registered automatically:

| Agent | When | What it does |
|:---|:---|:---|
| Daily Digest | Every morning | Sends a summary of your active Spaces, streak, and suggested focus for the day |
| SRS Review Push | Every morning | Lists the concepts due for spaced repetition review today |
| Recommendations | Every hour | Updates the suggestions for what to study next based on your recent sessions |
| Weekly Digest | Every Sunday | A full week-in-review: focus time, concepts touched, test scores, and recommendations |
| Workspace Analyser | Every 30 minutes | Re-checks Spaces, refreshes `Optimal_Learn.md`, and updates lightweight recommendations when the workspace changed |

These can be paused but not deleted.

---

## Space-scoped agents

Agents can be created inside a specific Space. Space-scoped agents have access to that Space's roadmap, learner profile, and notes as context. Open a Space → click the **Agents** panel button in the top-right toolbar to manage agents for that Space.

Space-scoped agent specs are stored under `<space_dir>/.spaces/agents/` rather than the global `~/.sarthak_ai/agents/`.

Global agents live under `~/.sarthak_ai/agents/` and can span multiple Spaces.

---

## Sandbox and safety

Every agent run is wrapped by the sandbox layer before the LLM executes it.

- Shell access is disabled unless the agent was created with the `shell` tool
- File access is limited to allowed read and write roots
- Output is scrubbed for secrets before it is stored or sent
- Run time, memory, CPU, and web-call counts are capped

The default limits come from the agent scope and can be overridden in `config.toml` under `agents.sandbox.system` and `agents.sandbox.space`, or per agent through its saved sandbox policy.

Typical defaults:

- system agents: 120 second wall timeout
- space agents: 300 second wall timeout
- output cap: 64 KB
- max web calls: 10 per run

---

## Telegram notifications

Agents can deliver results to Telegram so you get updates on your phone without opening the app.

To set it up: go to **Config** in the sidebar, find the Telegram section, and add your bot token and chat ID. Enable Telegram there and it will be available as a delivery option when creating agents.

If you need to create a Telegram bot, search for **@BotFather** on Telegram and follow the instructions — it takes about two minutes.

---

## Where agent data is stored

| Path | Contents |
|:---|:---|
| `~/.sarthak_ai/agents/<agent_id>/spec.json` | Global agent definition |
| `~/.sarthak_ai/agents/<agent_id>/runs/` | Global run history |
| `~/.sarthak_ai/agents/registry.json` | Global agent registry |
| `<space_dir>/.spaces/agents/<agent_id>/spec.json` | Space-scoped agent definition |
| `<space_dir>/.spaces/agents/<agent_id>/runs/` | Space-scoped run history |
