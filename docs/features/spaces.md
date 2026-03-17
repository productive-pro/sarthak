# Sarthak Spaces

Sarthak Spaces is the learning engine at the heart of Sarthak. Give it a domain and your background, and it builds a personalized curriculum, teaches every concept the way a senior mentor would, tracks your progress with XP and spaced repetition, and always picks your next concept at the exact edge of your current ability.

Everything described here is available in the web UI under **Spaces**, via the CLI (`sarthak spaces`), or through Telegram/WhatsApp.

---

## Creating a Space

### Web UI

Open **Spaces** in the sidebar → click **+ New Space**. Fill in:

- **Workspace directory** — a folder on your machine. Sarthak sets up a learning structure inside it.
- **Type** — choose the domain closest to your goal
- **Display name** — a friendly label shown in the UI
- **Your background** — describe your experience in plain language: `"doctor with no coding experience"`, `"Python developer, 2 years"`, `"complete beginner"`
- **Learning goal** — what you want to achieve: `"pass the GATE exam"`, `"build ML models for clinical data"`, `"switch careers into AI"`
- **Enable document search** — tick this if you have notes, PDFs, or code in the folder

Sarthak generates a full curriculum roadmap when the Space is created.

### CLI

```bash
sarthak spaces init \
  --dir ~/my-ml-project \
  --type data_science \
  --background "software engineer, no ML experience" \
  --goal "build production ML pipelines"
```

**Supported types:** `data_science`, `ai_engineering`, `software_engineering`, `medicine`, `education`, `exam_prep`, `business`, `research`, `custom`

For `custom`, Sarthak discovers the domain from your background and goal, asks clarifying questions, and tailors the roadmap.

---

## How Sarthak teaches you

### Zone of Proximal Development

Sarthak always picks the concept at the exact edge of what you already know — not so easy it's boring, not so far ahead it's confusing. Concepts you are struggling with come back sooner; concepts you have mastered come back on a spaced repetition schedule.

### Background-adaptive explanations

Every explanation is adapted to your background. If you are a doctor, Sarthak uses clinical analogies. If you are a business analyst, it avoids unnecessary code. If you are an engineer, it connects concepts to systems you already know. If you want deeper math, just ask.

### Specialist sub-agents

Fifteen stateless AI agents work together to drive your session:

| Agent | What it does |
|---|---|
| CurriculumAgent | ZPD-based concept selection, adapts to your signals |
| MathAgent | Derives equations at the right depth + NumPy equivalents |
| TaskBuilderAgent | Creates hands-on tasks with real-world hooks |
| ProjectAgent | Scaffolds end-to-end projects with a ROADMAP.md |
| AssessmentAgent | Evaluates your submissions, detects novel approaches |
| SpacedRepetitionAgent | SM-2 scheduling for review cycles |
| WorkspaceAnalyserAgent | Writes `Optimal_Learn.md` after each session |
| PracticeEngine | Generates and grades timed tests from LLM, RAG, or custom prompt |
| SignalOptimizer | Analyzes sessions and surfaces high-impact recommendations |
| BadgeAgent | Achievement system |
| ExternalToolsAgent | Detects VS Code, Colab, Obsidian from your filesystem |
| EnvironmentAgent | Scans real OS PATH and importlib — no guessing |

---

## Progression: XP, levels, streaks

As you complete sessions and pass tests, you earn XP and level up.

| Level | XP required |
|---|---|
| Novice | 0 |
| Beginner | 100 |
| Intermediate | 300 |
| Advanced | 700 |
| Expert | 1500 |

Your **streak** tracks consecutive days with at least one learning session. Your level, XP, streak, and mastered concepts are visible on the Dashboard and in every Space card.

---

## The roadmap board

Your curriculum is organized into chapters → topics → concepts on a Kanban board with four columns: **Not Started**, **In Progress**, **Review**, **Completed**.

- **Drag a chapter** to a new column to update its status
- **Double-click a title** to rename it
- **Click ⋮** on a card to generate topics with AI, edit the description, or delete
- **Click + Chapter** to add one manually

---

## Working inside a concept

Click into a topic, then click a concept. The workspace has six tabs:

**Notes** — write in Markdown. Drop in a PDF or Word document to convert it automatically. Dictate using speech-to-text (microphone icon). Notes are versioned and saved automatically.

**Explains** — ask Sarthak to explain this concept, generate a summary, or answer a specific question. Answers are grounded in your own notes when they exist.

**QuickTest** — take a short timed test on this concept and get immediate feedback with scores and explanations.

**Record** — record audio or video and get an automatic transcript added to your notes.

**Notebook** — a live code notebook for experimenting as you learn.

**Playground** — an interactive sandbox tied to this concept.

---

## Side panels

From the Space home, the toolbar buttons open side panels:

| Panel | What it's for |
|---|---|
| **SRS** | Every concept due for spaced repetition review today, ranked by urgency |
| **Practice** | Run a full timed test drawn from your roadmap or your own notes |
| **Insights** | Session analytics: focus scores, understanding trends, recommendations |
| **Graph** | Interactive D3 knowledge graph — how concepts connect to each other |
| **Digest** | AI-generated narrative summary of recent learning + suggested next steps |
| **Notes** | All notes across this Space in one searchable view |
| **Tasks** | To-do manager tied to this Space |
| **Workspace** | Browse the files inside your Space folder |
| **Agents** | Agents scoped to this Space |

---

## Spaced repetition (SRS)

Sarthak uses the SM-2 algorithm. After every session, test, and self-report, the review schedule updates:

- **Stuck on it** → review tomorrow
- **Test failed** → review in 1 day
- **Weak** → review in 1 day
- **No notes** → review in 2 days
- **Strong** → review in 4+ days (interval increases each time)

The SRS panel shows what's due today. The built-in `SRS Review Push` agent sends a morning reminder to Telegram.

---

## Document search (RAG)

When you enable document search for a Space, Sarthak indexes your notes, PDFs, and code files and uses them as grounding context during sessions, explanations, and practice tests. The index updates automatically when files change.

```bash
# Manual operations
sarthak spaces rag index --dir ~/my-space          # index (incremental by default)
sarthak spaces rag index --dir ~/my-space --full   # full re-index
sarthak spaces rag search --dir ~/my-space --query "numpy broadcasting"
sarthak spaces rag status --dir ~/my-space         # show doc count and DB size
sarthak spaces rag watch  --dir ~/my-space         # auto-reindex on file changes
```

---

## CLI learning workflow

```bash
# Quick learning session — next concept, math, and task
sarthak spaces learn --dir ~/my-space

# Tracked session with self-report at the end (writes SpaceSession record)
sarthak spaces session --dir ~/my-space --concept "gradient descent" --minutes 45

# Run a practice test
sarthak spaces practice --type concept --scope "backpropagation"
sarthak spaces practice --type full_space --time 90        # full exam, 90s per question
sarthak spaces practice --source rag --type topic --scope beginner  # from your own notes

# Evaluate your work on a concept
sarthak spaces evaluate "gradient descent" --dir ~/my-space --file ./my-solution.py

# See personalized recommendations from recent sessions
sarthak spaces optimize --dir ~/my-space --last 10

# Scaffold a project
sarthak spaces project --dir ~/my-space

# Show current mastery status
sarthak spaces status --dir ~/my-space

# Regenerate roadmap
sarthak spaces roadmap --dir ~/my-space --regen
```

---

## Space memory files

Sarthak maintains a set of Markdown files in `.spaces/` that form the persistent context for your learning:

| File | Purpose |
|---|---|
| `SOUL.md` | Agent identity and domain framing for this Space — set once at init |
| `MEMORY.md` | Long-term learner patterns — updated weekly by a distillation pass |
| `HEARTBEAT.md` | SRS due counts and daily streaks — updated hourly |
| `memory/YYYY-MM-DD.md` | Raw session logs for each day |
| `Optimal_Learn.md` | Workspace analysis written after each session |

These are plain text files you can read and edit at any time.

---

## For non-technical learners

If your background is non-technical, Sarthak adapts automatically:

- Every concept starts with why it matters in your field before any technical content
- Analogies come from your domain (medical, business, education, legal, etc.)
- Tasks have no-code alternatives using spreadsheets or interactive tools
- Mathematical notation is kept minimal unless you ask for more depth
- The workspace structure mirrors how practitioners in your field organize their work
