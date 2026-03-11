from __future__ import annotations

from sarthak.spaces.agents._common import _call_llm_json
from sarthak.spaces.models import LearningTask, SkillLevel


class AssessmentAgent:
    """
    Evaluates submitted work. Honest, specific, never vague.
    Detects novel approaches — creative thinking must be recognized.
    """

    SYSTEM = """You are a precise, honest learning assessor for Sarthak Spaces.
Vague feedback ("good job") is useless. Be specific.

Check:
- Does it show UNDERSTANDING or just copying?
- Is the math correctly applied?
- Is there a novel or creative approach? (Recognize it explicitly)
- What specifically is missing or incorrect?

Output ONLY valid JSON:
{
  "mastered": true|false,
  "score": 0-100,
  "strengths": ["specific strength with line reference if code"],
  "gaps": ["specific gap with fix suggestion"],
  "concept_mastered": "concept name if truly mastered, else empty string",
  "concept_struggling": "concept name if clearly struggling, else empty",
  "novel_approach": true|false,
  "novel_approach_description": "what they did creatively (2-3 words if detected)",
  "feedback": "2-3 sentences: honest + constructive + actionable",
  "next_step": "one concrete action"
}"""

    async def evaluate(
        self, task: LearningTask, submission: str
    ) -> dict:
        prompt = (
            f"Task: {task.title}\n"
            f"Concept: {task.concept}\n"
            f"Expected: {task.expected_outcome}\n"
            f"Math foundation: {task.math_foundation}\n"
            f"Submission:\n{submission}\n"
            "Evaluate. Return JSON."
        )
        return await _call_llm_json(self.SYSTEM, prompt, {
            "mastered": False, "score": 0,
            "feedback": "Assessment failed.", "gaps": [], "strengths": [],
            "novel_approach": False, "concept_mastered": "", "concept_struggling": "",
        }, tag="assessment_agent")


class QuickTestAgent:
    """
    5-minute micro-tasks. Key insight: consistent daily micro-learning
    beats weekly cramming. Perfect for busy professionals.
    """

    SYSTEM = """You are a micro-learning designer for Sarthak Spaces.
Create a focused 5-minute challenge. Types:
- formula_recall: write a formula from memory + explain one term
- code_snippet: write 5-10 lines implementing one idea
- explain_like_5: explain a concept to a beginner
- spot_the_bug: find and fix a bug in provided code
- connect_concepts: describe how two concepts relate

Output ONLY valid JSON:
{
  "type": "formula_recall|code_snippet|explain_like_5|spot_the_bug|connect_concepts",
  "title": "QuickTest title",
  "challenge": "The 5-minute challenge (include code if spot_the_bug)",
  "success_criteria": "How you know you've succeeded",
  "xp_reward": 5
}"""

    async def generate(
        self,
        concept: str,
        level: SkillLevel,
        background: str = "",
        is_technical: bool = True,
        user_prompt: str = "",
        notes_context: str = "",
    ) -> dict:
        challenge_type = "code_snippet" if is_technical else "explain_like_5"
        prompt = (
            f"Concept: {concept}\n"
            f"Level: {level.value}\n"
            f"Background: {background or 'technical'}\n"
            f"Preferred type: {challenge_type}\n"
            f"User request: {user_prompt or 'none'}\n"
            "Generate 5-minute micro-task. Return JSON."
        )
        if notes_context:
            prompt += f"Notes context:\n{notes_context}\n"
        return await _call_llm_json(self.SYSTEM, prompt, {
            "type": challenge_type,
            "title": f"Quick: {concept}",
            "challenge": f"In 5 minutes, implement the core idea of **{concept}** in Python.",
            "success_criteria": "Code runs without errors and demonstrates the concept.",
            "xp_reward": 5,
        }, tag="quicktest_agent")
