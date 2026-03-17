---
id: srs-push
name: SRS Push Agent
description: Spaced Repetition review reminder — sent to Telegram

schedule: "0 9 * * *"
channels: [scheduler]
---

Check all Sarthak Spaces for due SRS cards and send a reminder via Telegram.
List the concept name and due count. Keep it brief — one line per space.
