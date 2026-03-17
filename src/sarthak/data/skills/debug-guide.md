---
name: "debug-guide"
description: "Systematic debugging methodology for any language or stack"
tags: [debugging, problem-solving, engineering]
---

## Debug Guide

**Step 1 — Reproduce** 
Isolate the smallest input that triggers the bug. If you can't reproduce it, you can't fix it.

**Step 2 — Hypothesise**
Form one testable hypothesis. State it explicitly: "I think X happens because Y."

**Step 3 — Observe**
Add logging or inspect state *before* changing anything. Evidence first.

**Step 4 — Change one thing**
Never change multiple variables at once. You need to know what fixed it.

**Step 5 — Verify**
Confirm the fix with the same repro case. Then check edge cases.

**Common traps to avoid:**
- Fixing symptoms instead of root cause.
- Assuming the bug is in someone else's code (check your assumptions first).
- Debugging by trial-and-error without a hypothesis.
