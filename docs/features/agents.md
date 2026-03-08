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

---

## Built-in agents

Sarthak includes four agents that run automatically from the moment you start:

| Agent | When | What it does |
|:---|:---|:---|
| Daily Digest | Every morning | Sends a summary of your active Spaces, streak, and suggested focus for the day |
| SRS Review Push | Every morning | Lists the concepts due for spaced repetition review today |
| Recommendations | Every hour | Updates the suggestions for what to study next based on your recent sessions |
| Weekly Digest | Every Sunday | A full week-in-review: focus time, concepts touched, test scores, and recommendations |

These can be paused but not deleted.

---

## Telegram notifications

Agents can deliver results to Telegram so you get updates on your phone without opening the app.

To set it up: go to **Config** in the sidebar, find the Telegram section, and add your bot token and chat ID. Enable Telegram there and it will be available as a delivery option when creating agents.

If you need to create a Telegram bot, search for **@BotFather** on Telegram and follow the instructions — it takes about two minutes.
