# Using Sarthak

Sarthak opens as a web app in your browser. Open it at [http://localhost:4848](http://localhost:4848) start everything at once with `sarthak orchestrator`, or install deamon with `sarthak service install`

The sidebar on the left lets you switch between the five sections: **Dashboard**, **Spaces**, **Chat**, **Agents**, and **Config**.

---

## Dashboard

The Dashboard is your daily home screen. At a glance you can see where your learning stands and what to do next.

<!-- ![Dashboard](../assets/screenshots/dashboard.png) -->

Your **active Space** is shown as a hero card at the top — XP earned, current level, streak, sessions completed, and an XP bar showing progress toward your next level. Concepts you recently mastered appear in green; ones flagged for review appear in red.

Below that is a **grid of all your Spaces**. Each card shows a progress ring, XP, streak, and how many concepts you have mastered. Click any card to open a detailed profile for that Space.

The **Agents** strip at the bottom shows your automation agents and whether each is currently active.

---

## Spaces

Spaces is where all your structured learning happens. Click **Spaces** in the sidebar.

<!-- ![Spaces list](../assets/screenshots/spaces-list.png) -->

### Creating a Space

Click **+ New Space** and fill in the form:

- **Workspace directory** — the folder on your machine where this Space lives. Sarthak will set up a learning structure inside it.
- **Type** — choose the domain that best fits (Data Science, AI Engineering, Software Engineering, Medicine, Education, Exam Prep, Research, or Custom).
- **Display name** — a friendly name shown in the UI.
- **Your background** — describe your experience in plain language, e.g. "doctor with no coding experience" or "software engineer, 2 years Python". Sarthak uses this to personalise every explanation.
- **Learning goal** — what you want to achieve, e.g. "master ML for my GATE exam".
- **Enable document search** — tick this if you have notes, PDFs, or code in the folder and want Sarthak to search them during sessions.

Sarthak generates a full curriculum roadmap for you when the Space is created.

---

### Space Home

<!-- ![Space Home](../assets/screenshots/space-home.png) -->

Clicking a Space opens its home, which has a header bar and the roadmap board.

The **header bar** shows your overall progress ring, XP, streak, and session count. The buttons on the right open side panels for extra tools (described below).

A **Continue Learning** banner appears if Sarthak knows where you left off — click it to jump directly back to that concept.

The **roadmap board** is a Kanban board with four columns: Not Started, In Progress, Review, and Completed. Each card is a chapter of your curriculum.

Things you can do on the board:

- **Drag a card** between columns to update its status
- **Drag within a column** to change the order
- **Double-click a title** to rename it
- **Click the ⋮ menu** on a card to edit its description, generate topics with AI, or delete it
- **Click + Chapter** in the header to add a chapter manually

---

### Chapters

Clicking a chapter card opens the Chapter view.

<!-- ![Chapter view](../assets/screenshots/chapter-view.png) -->

A chapter holds **topics**, shown as cards with concept counts, test coverage, and a progress bar. You can:

- Click a topic card to open it
- Click **Generate (AI)** to have Sarthak generate topics for this chapter automatically
- Click **+ Topic** to add one manually
- Double-click any topic title to rename it

The **Notes** tab gives you a full Markdown editor for chapter-level notes.

---

### Topics and Concepts

<!-- ![Topic view](../assets/screenshots/topic-view.png) -->

Opening a topic shows a resizable **concepts sidebar** on the left and a **workspace** on the right.

The sidebar lists every concept in the topic. Click a concept to focus on it. Click the circle icon to mark it complete or in progress. Use the ⋮ menu to rename or delete.

The workspace has six tabs:

**Notes** — a rich Markdown editor for writing your own notes on this concept. You can drop in a PDF or Word document and Sarthak will convert it to Markdown for you. Speech-to-text is also available — click the microphone icon to dictate. Notes are saved automatically and version history is kept.

**Explains** — ask Sarthak to explain the concept in depth, generate a summary, or answer a specific question. The answer is grounded in your own notes when they exist.

**QuickTest** — generate a short timed test on this concept and see your results immediately.

**Record** — record an audio or video note. Sarthak transcribes it and adds it to your notes.

**Notebook** — a live code notebook for trying things out as you learn.

**Playground** — an interactive sandbox tied to this concept.

---

### Space side panels

The buttons in the top-right of the Space home open slide-over panels. Each panel provides a focused tool without navigating away.

| Panel | What it's for |
|:---|:---|
| **Notes** | All notes you have written across this Space, searchable and editable |
| **Tasks** | A task manager for to-dos tied to this Space |
| **Workspace** | Browse the files inside your Space folder |
| **SRS** | Your spaced repetition review queue — concepts Sarthak thinks you should revisit today |
| **Graph** | An interactive knowledge graph of concepts and how they connect |
| **Digest** | An AI-generated summary of your recent activity and suggested next steps |
| **Practice** | Run a full practice test drawn from your roadmap or your own notes |
| **Insights** | Session analytics — how your focus and understanding scores have trended |
| **Agents** | Agents scoped to this Space |

---

## Chat

<!-- ![Chat](../assets/screenshots/chat.png) -->

The Chat page gives you a direct conversation with the Sarthak AI. It has full context of your learning history, active Space, and session data.

Ask it anything:

- "What should I study today?"
- "Explain attention mechanisms as if I'm a doctor"
- "What am I struggling with this week?"
- "Summarise what I learned yesterday"

Past sessions are listed on the left — click any to continue that conversation.

---

## Agents

<!-- ![Agents](../assets/screenshots/agents.png) -->

Agents are automations that run on a schedule and send you results. You create them by describing what you want in plain language.

### Creating an agent

Click **+ New Agent** and type a description. For example:

- "Every morning, summarise my study progress and send it to Telegram"
- "Every Sunday, review my weakest concepts from the past week and send a study plan"

Sarthak works out the schedule and what tools the agent needs. If you want results sent to your phone, tick **Send results to Telegram** before saving.

### Managing agents

Each agent card shows its name, schedule, and whether it is active or paused. You can:

- **Pause / Enable** — stop or resume the schedule at any time
- **Run** — trigger the agent right now and see the output immediately
- **Logs** — review the last 10 runs with timestamps and success/failure status
- **Delete** — remove the agent permanently

Sarthak also includes several built-in agents that start running automatically:

| Agent | Schedule | What it does |
|:---|:---|:---|
| Daily Digest | Every morning | Summarises your learning activity across all Spaces and sends it to Telegram |
| SRS Review Push | Every morning | Reminds you of concepts due for spaced repetition review |
| Recommendations | Hourly | Refreshes your suggested next concepts based on recent progress |
| Weekly Digest | Every Sunday | A full week-in-review with activity breakdown and test scores |

---

## Config

<!-- ![Config editor](../assets/screenshots/config.png) -->

The Config page is a live editor for your Sarthak settings. Changes are validated and saved instantly.

Common things to change here:

- **AI provider** — switch between Ollama (local), OpenAI, Anthropic, or Gemini
- **Model** — pick a specific model for each provider
- **Telegram** — enable notifications and set your bot token and chat ID
- **Web port** — change the port the app runs on

For API keys and other secrets, use the encrypt command in the terminal so they are never stored in plain text:

```bash
sarthak encrypt "your-api-key"
```

Paste the result into the secrets section of Config.
