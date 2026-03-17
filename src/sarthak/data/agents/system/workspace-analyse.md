---
id: workspace-analyse
name: Workspace Analyser Agent
description: Every 30 min — re-analyse all active spaces and refresh Optimal_Learn.md

schedule: "*/30 * * * *"
model_tier: balanced
channels: [scheduler]
---

Analyse all registered Sarthak Spaces and refresh their Optimal_Learn.md.
Use real learner signals (weak concepts, SRS due, test scores) to surface the
single most actionable next step for each space.
Only re-analyse if workspace files changed since the last run.
