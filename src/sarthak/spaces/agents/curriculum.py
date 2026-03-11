from __future__ import annotations

import json

from sarthak.spaces.models import SpaceContext

from sarthak.spaces.agents._common import _call_llm_json


class OnboardingAgent:
    """
    On first session, detects learner background from free-form text,
    sets is_technical flag, infers goal, recommends starting level.
    Critical for non-technical users (doctors, teachers) who need
    completely different framing.
    """

    SYSTEM = """You are a learning diagnostic expert.
From a learner's self-description, infer their profile.
Output ONLY valid JSON:
{
  "background_category": "doctor|teacher|engineer|student|manager|researcher|other",
  "is_technical": true|false,
  "inferred_goal": "specific goal from their description",
  "recommended_start_level": "novice|beginner|intermediate|advanced",
  "first_concept": "exact concept name to start with",
  "learning_style_hint": "visual|textual|hands-on|problem-first",
  "motivating_hook": "one compelling sentence that will excite THIS person about the domain",
  "welcome_message": "warm 2-3 sentence personalized welcome (use their background for analogy)"
}"""

    async def analyze(self, background: str, goal: str, domain: str) -> dict:
        prompt = (
            f"Domain they want to learn: {domain}\n"
            f"Their background: {background}\n"
            f"Their stated goal: {goal or 'not specified'}\n"
            "Analyze and return JSON."
        )
        return await _call_llm_json(self.SYSTEM, prompt, {
            "background_category": "other",
            "is_technical": False,
            "inferred_goal": goal or "mastery",
            "recommended_start_level": "novice",
            "first_concept": "basics",
            "learning_style_hint": "visual",
            "motivating_hook": f"You're about to unlock {domain}.",
            "welcome_message": f"Welcome! Let's start your {domain} journey.",
        }, tag="onboarding_agent")


class CurriculumAgent:
    """
    Selects the optimal next concept using Zone of Proximal Development.
    Priority: struggling concepts > review due > new concepts.
    Adapts path to learner goal (exam prep vs projects vs mastery).
    """

    SYSTEM = """You are a world-class adaptive curriculum designer for Sarthak Spaces.
Select the SINGLE BEST next concept using Zone of Proximal Development.

Priority rules:
1. Struggling concepts → fix the gap before moving forward
2. Spaced repetition reviews → weave them in naturally
3. just beyond current mastery, building on what they know
4. If learner goal is exam prep → bias toward high-frequency exam topics
5. If learner goal is projects → bias toward immediately applicable concepts
6. If activity context shows low focus/high distraction → recommend QuickTest or review session
7. If activity context shows long learning session → advance to harder concept

Output ONLY valid JSON:
{
  "next_concept": "exact concept name from available list",
  "why_now": "one sentence: why this concept at this moment for this learner",
  "review_concept": "concept to review (or empty string)",
  "estimated_mastery_time": "e.g. 2 sessions",
  "learning_path": ["next_after_this", "then_this", "then_this"],
  "session_type": "new_concept|review|struggle_fix|project_step|quicktest",
  "suggest_project": true|false
}"""

    async def plan(
        self,
        ctx: SpaceContext,
        available: list[str],
        review_due: list[str],
        activity_context: str = "",
    ) -> dict:
        p = ctx.profile.learner
        prompt = (
            f"Domain: {ctx.profile.domain}\n"
            f"Background: {p.background or 'not specified'}\n"
            f"Goal: {p.goal or 'mastery'}\n"
            f"Level: {p.skill_level.value}\n"
            f"Style: {p.preferred_style}\n"
            f"Mastered (last 6): {json.dumps(p.mastered_concepts[-6:])}\n"
            f"Struggling: {json.dumps(p.struggling_concepts)}\n"
            f"Available new: {json.dumps(available)}\n"
            f"Review due: {json.dumps(review_due)}\n"
            f"Total sessions: {p.total_sessions}\n"
        )
        if activity_context:
            prompt += f"\n{activity_context}\n"
        prompt += "Return JSON."
        return await _call_llm_json(self.SYSTEM, prompt, {
            "next_concept": available[0] if available else "review basics",
            "why_now": "Continuing your learning path.",
            "review_concept": review_due[0] if review_due else "",
            "session_type": "new_concept",
            "suggest_project": False,
        }, tag="curriculum_agent")
