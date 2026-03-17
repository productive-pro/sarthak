---
id: recommendations
name: Recommendations Agent
description: Hourly next-concept refresh for all spaces

schedule: "0 * * * *"
channels: [scheduler]
---

Refresh the recommended next concept for all active Sarthak Spaces.
Use ZPD logic: next concept should be just beyond current mastery.
Update the space's recommendation silently — no user notification needed.
