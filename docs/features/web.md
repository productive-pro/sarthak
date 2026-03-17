# Using Sarthak — Web UI

Sarthak opens as a web app in your browser. Start everything with:

```bash
sarthak service install   # background service (recommended)
# or
sarthak orchestrator      # run in the foreground
```

Then open **[http://localhost:4848](http://localhost:4848)**.

The sidebar on the left switches between five sections: **Dashboard**, **Spaces**, **Chat**, **Agents**, and **Config**.

---

## Dashboard

The Dashboard is your daily home screen. At a glance you see where your learning stands and what to do next.

Your **active Space** is shown as a hero card at the top — XP earned, current level, streak, sessions completed, and an XP progress bar. Concepts recently mastered appear in green; ones flagged for review appear in red.

Below that is a **grid of all your Spaces**. Each card shows a progress ring, XP, streak, and how many concepts you have mastered. Click any card to open that Space.

The **Learning Activity** section shows tracked focus time for the period you select (last 3 hours, 8 hours, 24 hours, 3 days, or week). It shows total time, focus time, and a breakdown by application.

The **Agents strip** at the bottom shows your automation agents and whether each is active.

---

## Spaces

### Creating a Space

Click **+ New Space** and fill in the form:

- **Workspace directory** — the folder on your machine where this Space lives
- **Type** — Data Science, AI Engineering, Software Engineering, Medicine, Education, Exam Prep, Research, or Custom
- **Display name** — friendly name shown in the UI
- **Your background** — describe your experience: `"doctor with no coding experience"`, `"Python dev, 2 years"`
- **Learning goal** — `"master ML for my GATE exam"`, `"understand transformers well enough to fine-tune them"`
- **Enable document search** — tick to index your existing notes, PDFs, and code

Sarthak generates a full AI curriculum roadmap when the Space is created.

### Space Home

Clicking a Space opens its home, which shows the roadmap board and a header with your progress ring, XP, streak, and session count.

A **Continue Learning** banner appears at the top if Sarthak knows where you left off — click it to jump directly back to that concept.

The **roadmap board** is a Kanban board with four columns: Not Started, In Progress, Review, Completed. Each card is a chapter of your curriculum.

Things you can do on the board:

- **Drag a card** between columns to update its status
- **Drag within a column** to reorder
- **Double-click a title** to rename it
- **Click the ⋮ menu** to edit description, generate topics with AI, or delete
- **Click + Chapter** to add a chapter manually

### Chapters and Topics

Clicking a chapter card opens its topics as cards showing concept count, test coverage, and a progress bar. Click a topic to open it.

### Concept Workspace

Inside a topic, you see a **concepts sidebar** on the left and a **workspace** on the right with six tabs:

**Notes** — Markdown editor. Drop in a PDF or Word doc to auto-convert it. Dictate using the microphone icon (speech-to-text). Notes are versioned and saved automatically.

**Explains** — ask Sarthak to explain the concept, generate a summary, or answer a specific question. Answers are grounded in your own notes when they exist.

**QuickTest** — take a short timed test on this concept and see results immediately.

**Record** — record an audio or video note; Sarthak transcribes it and adds it to your notes.

**Notebook** — a live code notebook for experimenting as you learn.

**Playground** — an interactive sandbox tied to this concept.

### Side panels

The toolbar buttons in the top-right of the Space home open slide-over panels:

| Panel | What it's for |
|---|---|
| **Notes** | All notes across this Space, searchable and editable |
| **Tasks** | To-do manager tied to this Space |
| **Workspace** | Browse files inside your Space folder |
| **SRS** | Concepts due for spaced repetition review today |
| **Graph** | Interactive knowledge graph of concepts and how they connect |
| **Digest** | AI-generated summary of recent activity and suggested next steps |
| **Practice** | Run a full timed test from your roadmap or your notes |
| **Insights** | Session analytics — focus scores and understanding trends |
| **Agents** | Agents scoped to this Space |

---

## Chat

The Chat page gives you a direct conversation with the Sarthak AI. It has full context of your learning history, active Space, and session data.

Ask it anything:

- `"What should I study today?"`
- `"Explain attention mechanisms as if I'm a doctor"`
- `"What am I struggling with this week?"`
- `"Summarise what I learned yesterday"`

Past sessions are listed on the left — click any to continue that conversation.

---

## Agents

Agents are automations that run on a schedule. Click **+ New Agent** and type a description in plain language:

- `"Every morning, summarise my study progress and send it to Telegram"`
- `"Every Sunday, review my weakest concepts from the past week"`

Tick **Send results to Telegram** before saving to get updates on your phone.

Each agent card shows its name, schedule, and status. You can:

- **Pause / Enable** — stop or resume the schedule
- **Run** — trigger it immediately and see output
- **Logs** — review recent run history
- **Delete** — remove the agent

See the full [Agents guide](agents.md) for details on built-in agents, sandbox limits, and Telegram setup.

---

## Config

The Config page is a live editor for your Sarthak settings. Changes are validated and saved instantly.

Common things to change here:

- **AI provider** — switch between OpenRouter, Ollama, OpenAI, Anthropic, or Gemini
- **Model** — pick a specific model for your provider
- **Telegram** — enable notifications and add your bot token and chat ID
- **Web port** — change the port the app runs on (requires restart)

For API keys and other secrets, use the encrypt command so they are never stored in plain text:

```bash
sarthak encrypt "your-api-key"
# Output: ENC:abc123...  ← paste this into Config
```

See the [Configuration guide](../guides/configuration.md) for all provider setup instructions.
