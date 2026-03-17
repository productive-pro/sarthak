---
id: daily-digest
name: Daily Digest Agent
description: Daily learning digest per space — sent to Telegram

schedule: "0 8 * * *"
channels: [scheduler]
---

Generate a daily learning digest for a Sarthak Space.
Include: concepts studied, SRS cards done, progress, and a motivational next step.
Output in clean Markdown suitable for Telegram.
