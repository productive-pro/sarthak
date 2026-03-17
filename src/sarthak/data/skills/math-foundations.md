---
name: "math-foundations"
description: "How to explain mathematical concepts for maximum understanding at any level"
tags: [math, teaching, derivation, intuition]
---

## Math Foundations Teaching Guide

When explaining a mathematical concept, follow this sequence:

**1. Intuition before notation**
State what the formula *does* in one plain-English sentence before showing any symbols.
Example: "Gradient descent is just sliding downhill — always stepping in the direction that reduces your error the most."

**2. Domain analogy**
Pick an analogy from the learner's field:
- Data scientist → "Think of loss as elevation on a landscape. You're always stepping toward lower ground."
- Doctor → "Think of it like titrating a drug dose — small adjustments toward the therapeutic window."
- Teacher → "Think of it like adjusting difficulty in real-time based on student error rate."

**3. Minimal formula first**
Show the simplest possible form first. Add complexity only after the core is understood.

**4. Connect to code immediately**
Every formula gets a numpy/Python equivalent. If the learner can compute it, they understand it.

**5. Surface 2 misconceptions**
Always name the two mistakes learners commonly make. Forewarned is forearmed.

**LaTeX conventions**: `$...$` inline, `$$...$$` display block. Always use them.
