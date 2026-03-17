# Activity Dashboard (TUI)

The Sarthak terminal UI (`sarthak tui`) is a keyboard-driven view of your activity and learning. Open it when you want a quick read of your day without opening the browser.

```bash
sarthak tui
```

---

## What's inside

**Overview** — top activities by category, most-used applications, and concept highlights from recent sessions.

**Daily summaries** — AI-generated narratives of your day with concrete suggestions. Browse past days from the list on the left and read the full summary on the right.

**Timeline** — a chronological feed of everything Sarthak captured. Filter by keyword or navigate to any past date.

**Chat** — ask questions about your own history directly from the terminal. Sarthak answers using your actual captured data.

Press `?` at any time to see keyboard shortcuts.

---

## Analytics commands

For quick stats without opening the TUI:

```bash
sarthak resume          # most recent Space session summary
sarthak summarize       # generate AI summary for today
sarthak summarize --date 2026-03-15   # summary for a specific date
```
