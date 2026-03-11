"""
Sarthak Spaces — Practice Engine

Generates and grades timed tests at three scopes:
  concept   — one concept, 5–10 questions
  topic     — one topic/level, 10–20 questions
  full_space — entire domain curriculum, 20–40 questions

Question sources (user chooses):
  llm    — generated fresh by LLM from concept/domain knowledge
  rag    — extracted from files the learner stored in the space folder
  prompt — learner provides a custom prompt / instructions

Per-question timers:
  - Default: 120 s/question (configurable globally or per test)
  - Learner can override seconds_per_question at test creation time
  - timeout is enforced by the CLI/TUI runner; engine just stores the limit

After grading:
  - Weak concepts → fed back into SpacedRepetitionAgent
  - Strong concepts → mastery strength boosted
  - XP awarded proportional to score
  - TestResult persisted to .spaces/test_results.jsonl
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone
from pathlib import Path

import structlog

from sarthak.features.ai.agents._base import parse_json_response, run_llm
from sarthak.spaces.models import (
    PracticeTest,
    QuestionResult,
    SkillLevel,
    SpaceContext,
    SpaceProfile,
    TestQuestion,
    TestResult,
)

log = structlog.get_logger(__name__)

_RESULTS_FILE = ".spaces/test_results.jsonl"


# ── Prompts ───────────────────────────────────────────────────────────────────

_QUESTION_SYSTEM = """You are an expert test designer for Sarthak Spaces.
Generate exam-quality questions that test GENUINE understanding, not trivia.

Rules:
- Mix question types: MCQ (60%), short_answer (30%), code (10% if technical)
- MCQ: 4 options, exactly one correct, all plausible distractors
- Short answer: 1-3 sentence answers expected
- Code: small, runnable Python/pseudocode snippets
- Include the correct_answer and a clear explanation
- Distribute difficulty: 40% at level, 30% slightly below, 30% slightly above
- Every question must state which concept it tests

Output ONLY valid JSON — a list of question objects:
[
  {
    "question": "...",
    "question_type": "mcq|short_answer|code|true_false",
    "options": ["A) ...", "B) ...", "C) ...", "D) ..."],
    "correct_answer": "A) ...",
    "explanation": "why this is correct + common mistakes",
    "concept": "concept name",
    "difficulty": "novice|beginner|intermediate|advanced|expert",
    "points": 10
  }
]"""

_GRADE_SYSTEM = """You are a precise, honest learning assessor.
Grade the student's answer against the correct answer and explanation.

Output ONLY valid JSON:
{
  "correct": true|false,
  "score": 0-10,
  "feedback": "one sentence: what was right/wrong and why"
}

For short_answer: partial credit is fine. For MCQ/true_false: binary.
Be strict but fair. Never give full marks for a vague answer."""


# ── Question generation ───────────────────────────────────────────────────────

async def _generate_from_llm(
    scope: str,
    n_questions: int,
    level: SkillLevel,
    domain: str,
    background: str,
    concepts: list[str],
    custom_prompt: str = "",
) -> list[dict]:
    if custom_prompt:
        # User's custom prompt takes priority — only use system for output format
        system = (
            "You are an expert test designer. Generate exam-quality questions.\n"
            "Output ONLY valid JSON — a list of question objects with fields: "
            "question, question_type (mcq/short_answer/code/true_false), options (for mcq), "
            "correct_answer, explanation, concept, difficulty, points.\n"
            "IMPORTANT: Follow the user's custom instructions above all else."
        )
        prompt = (
            f"User instructions (HIGHEST PRIORITY): {custom_prompt}\n\n"
            f"Domain: {domain} | Level: {level.value}\n"
            f"Concepts available: {', '.join(concepts)}\n"
            f"Generate exactly {n_questions} questions matching the user's instructions. Return JSON list."
        )
    else:
        system = _QUESTION_SYSTEM
        prompt = (
            f"Domain: {domain}\n"
            f"Scope: {scope}\n"
            f"Learner level: {level.value}\n"
            f"Background: {background or 'technical'}\n"
            f"Concepts to cover: {', '.join(concepts[:20])}\n"
            f"Generate exactly {n_questions} questions. Return JSON list."
        )
    raw = await run_llm(system, prompt)
    data = parse_json_response(raw)
    return data if isinstance(data, list) else data.get("questions", [])


async def _generate_from_rag(
    space_dir: Path,
    scope: str,
    n_questions: int,
    level: SkillLevel,
    domain: str,
    concepts: list[str],
) -> list[dict]:
    """Extract questions from the learner's own files via RAG search."""
    from sarthak.spaces.rag import search_space

    # Gather context chunks for each concept
    context_parts: list[str] = []
    for concept in concepts[:10]:
        chunk = await search_space(space_dir, concept, top_k=3)
        if chunk and "not indexed" not in chunk.lower():
            context_parts.append(f"[{concept}]\n{chunk}")

    if not context_parts:
        return await _generate_from_llm(scope, n_questions, level, domain, "", concepts)

    context = "\n\n---\n\n".join(context_parts[:6])[:4000]
    prompt = (
        f"Domain: {domain} | Level: {level.value}\n"
        f"Scope: {scope}\n"
        f"Generate {n_questions} questions based ONLY on the following material "
        f"from the learner's workspace files:\n\n{context}\n\n"
        "Return JSON list of question objects."
    )
    raw = await run_llm(_QUESTION_SYSTEM, prompt)
    data = parse_json_response(raw)
    result = data if isinstance(data, list) else data.get("questions", [])
    # Tag source
    for q in result:
        q["source"] = "rag:workspace"
    return result


def _build_questions(raw_list: list[dict], time_per_q: int, level: SkillLevel) -> list[TestQuestion]:
    questions: list[TestQuestion] = []
    for i, d in enumerate(raw_list):
        qtype = d.get("question_type", "short_answer")
        if qtype not in ("mcq", "short_answer", "code", "true_false"):
            qtype = "short_answer"
        try:
            diff = SkillLevel(d.get("difficulty", level.value))
        except ValueError:
            diff = level
        questions.append(TestQuestion(
            question_id=str(uuid.uuid4())[:8],
            question=d.get("question", ""),
            question_type=qtype,
            options=d.get("options", []),
            correct_answer=d.get("correct_answer", ""),
            explanation=d.get("explanation", ""),
            concept=d.get("concept", ""),
            difficulty=diff,
            points=int(d.get("points", 10)),
            time_limit_seconds=time_per_q,
            source=d.get("source", "llm"),
        ))
    return questions


# ── PracticeEngine ────────────────────────────────────────────────────────────

class PracticeEngine:
    """
    Stateless engine — call create_test() then grade_test().
    State (tests, results) is persisted to .spaces/ files.
    """

    # ── Create ────────────────────────────────────────────────────────────────

    async def create_test(
        self,
        ctx: SpaceContext,
        test_type: str = "concept",           # "concept" | "topic" | "full_space"
        scope: str = "",                       # concept name, topic name, or "" for full
        source: str = "llm",                  # "llm" | "rag" | "prompt"
        source_prompt: str = "",               # used when source=="prompt"
        seconds_per_question: int = 120,       # per-question timer
        n_questions: int | None = None,        # override auto count
    ) -> PracticeTest:
        profile = ctx.profile
        learner = profile.learner
        space_dir = Path(ctx.workspace_dir)
        domain = profile.domain

        # Determine concepts to cover
        concepts = self._scope_to_concepts(profile, test_type, scope)

        # Auto question count
        count = n_questions or {
            "concept":    8,
            "topic":     15,
            "full_space": 25,
        }.get(test_type, 10)

        log.info("practice_test_creating",
                 type=test_type, scope=scope or "full",
                 source=source, n=count)

        # Generate questions
        if source == "rag":
            raw = await _generate_from_rag(
                space_dir, scope or domain, count,
                learner.skill_level, domain, concepts,
            )
        elif source == "prompt":
            raw = await _generate_from_llm(
                scope or domain, count,
                learner.skill_level, domain,
                learner.background, concepts,
                custom_prompt=source_prompt,
            )
        else:
            raw = await _generate_from_llm(
                scope or domain, count,
                learner.skill_level, domain,
                learner.background, concepts,
            )

        questions = _build_questions(raw, seconds_per_question, learner.skill_level)
        total_time = sum(q.time_limit_seconds for q in questions)

        test = PracticeTest(
            test_id=str(uuid.uuid4())[:10],
            test_type=test_type,
            scope=scope or domain,
            source=source,
            source_prompt=source_prompt,
            questions=questions,
            total_time_seconds=total_time,
            space_dir=str(space_dir),
            domain=domain,
            level=learner.skill_level,
        )
        _save_test(space_dir, test)
        return test

    # ── Grade ─────────────────────────────────────────────────────────────────

    async def grade_test(
        self,
        test: PracticeTest,
        answers: dict[str, str],        # {question_id: user_answer}
        time_taken: dict[str, int],     # {question_id: seconds_taken}
    ) -> TestResult:
        """
        Grade all answers. MCQ/true_false graded locally.
        short_answer / code graded by LLM.
        """
        question_results: list[QuestionResult] = []
        total = 0
        max_score = 0

        for q in test.questions:
            max_score += q.points
            answer = answers.get(q.question_id, "")
            secs   = time_taken.get(q.question_id, q.time_limit_seconds)
            timed_out = secs >= q.time_limit_seconds and not answer.strip()

            if timed_out:
                qr = QuestionResult(
                    question_id=q.question_id,
                    user_answer="",
                    correct=False,
                    score=0,
                    time_taken_seconds=secs,
                    timed_out=True,
                    llm_feedback=f"Time limit reached ({q.time_limit_seconds}s). Correct: {q.correct_answer}",
                )
            elif q.question_type in ("mcq", "true_false"):
                correct = _check_exact(answer, q.correct_answer)
                qr = QuestionResult(
                    question_id=q.question_id,
                    user_answer=answer,
                    correct=correct,
                    score=q.points if correct else 0,
                    time_taken_seconds=secs,
                    llm_feedback=q.explanation if not correct else "✓ Correct.",
                )
            else:
                # LLM grading for open answers
                fb = await self._llm_grade(q, answer)
                score = min(q.points, int(fb.get("score", 0) / 10 * q.points))
                qr = QuestionResult(
                    question_id=q.question_id,
                    user_answer=answer,
                    correct=fb.get("correct", False),
                    score=score,
                    time_taken_seconds=secs,
                    llm_feedback=fb.get("feedback", ""),
                )

            total += qr.score
            question_results.append(qr)

        percent   = round(total / max_score * 100, 1) if max_score else 0
        passed    = percent >= 60
        xp_earned = int(total * 0.5)

        # Identify weak / strong concepts
        concept_scores: dict[str, list[int]] = {}
        concept_max: dict[str, int] = {}
        for q, r in zip(test.questions, question_results):
            c = q.concept or test.scope
            concept_scores.setdefault(c, []).append(r.score)
            concept_max[c] = concept_max.get(c, 0) + q.points

        weak, strong = [], []
        for c, scores in concept_scores.items():
            pct = sum(scores) / concept_max[c] * 100
            if pct < 50:
                weak.append(c)
            elif pct >= 80:
                strong.append(c)

        result = TestResult(
            test_id=test.test_id,
            session_id=str(uuid.uuid4())[:8],
            finished_at=datetime.now(timezone.utc).isoformat(),
            question_results=question_results,
            total_score=total,
            max_score=max_score,
            percent=percent,
            passed=passed,
            weak_concepts=weak,
            strong_concepts=strong,
            xp_earned=xp_earned,
        )
        _save_result(Path(test.space_dir), result)
        return result

    # ── Helpers ───────────────────────────────────────────────────────────────

    def _scope_to_concepts(
        self,
        profile: SpaceProfile,
        test_type: str,
        scope: str,
    ) -> list[str]:
        """Return the concept list for the given test type + scope."""
        from sarthak.spaces.domains import get_domain
        domain = get_domain(profile.space_type)
        tree: dict = domain.get("concept_tree", {})
        all_concepts: list[str] = []
        for level_concepts in tree.values():
            all_concepts.extend(level_concepts)

        if test_type == "concept":
            return [scope] if scope else [profile.learner.mastered_concepts[-1]] if profile.learner.mastered_concepts else all_concepts[:3]

        if test_type == "topic":
            # Find concepts whose SkillLevel key title matches the scope string
            for level, concepts in tree.items():
                if level.value == scope:
                    return concepts
            # scope is a topic title — match by prefix/substring across all concepts
            scope_lower = scope.lower()
            matched = [c for c in all_concepts if scope_lower in c.lower()]
            if matched:
                return matched[:15]
            # Fall back: concepts close to current level
            return [c for c in all_concepts if c in profile.learner.mastered_concepts][:10] or all_concepts[:10]

        # full_space: all mastered + current level concepts
        mastered = set(profile.learner.mastered_concepts)
        return [c for c in all_concepts if c in mastered][:30] or all_concepts[:15]

    async def _llm_grade(self, q: TestQuestion, answer: str) -> dict:
        prompt = (
            f"Question: {q.question}\n"
            f"Correct answer: {q.correct_answer}\n"
            f"Explanation: {q.explanation}\n"
            f"Student answer: {answer}\n"
            "Grade. Return JSON."
        )
        raw = await run_llm(_GRADE_SYSTEM, prompt)
        return parse_json_response(raw)

    def format_test_result(self, test: PracticeTest, result: TestResult) -> str:
        """Render a human-readable Markdown result card."""
        status_word = "PASS" if result.passed else "FAIL"
        lines = [
            f"# Test Result [{status_word}] — {test.scope}",
            f"**Score**: {result.total_score}/{result.max_score} ({result.percent}%)",
            f"**Status**: {'Passed' if result.passed else 'Needs more work'}",
            f"**XP earned**: +{result.xp_earned}",
            "",
        ]
        if result.strong_concepts:
            lines.append(f"**Strong**: {', '.join(result.strong_concepts)}")
        if result.weak_concepts:
            lines.append(f"**Needs review**: {', '.join(result.weak_concepts)}")
        lines += ["", "---", "## Per-question breakdown"]
        for i, (q, r) in enumerate(zip(test.questions, result.question_results), 1):
            mark = "ok" if r.correct else ("timeout" if r.timed_out else "wrong")
            lines.append(
                f"{i}. [{mark}] **{q.concept}** — {r.score}/{q.points}pts "
                f"({r.time_taken_seconds}s)"
            )
            if not r.correct and r.llm_feedback:
                lines.append(f"   > {r.llm_feedback}")
        return "\n".join(lines)


# ── Persistence ───────────────────────────────────────────────────────────────

def _save_test(space_dir: Path, test: PracticeTest) -> None:
    out = space_dir / ".spaces" / "tests.jsonl"
    out.parent.mkdir(parents=True, exist_ok=True)
    with out.open("a", encoding="utf-8") as f:
        f.write(test.model_dump_json() + "\n")


def _save_result(space_dir: Path, result: TestResult) -> None:
    out = space_dir / ".spaces" / "test_results.jsonl"
    out.parent.mkdir(parents=True, exist_ok=True)
    with out.open("a", encoding="utf-8") as f:
        f.write(result.model_dump_json() + "\n")


def load_test_results(space_dir: Path, limit: int = 20) -> list[TestResult]:
    path = space_dir / ".spaces" / "test_results.jsonl"
    if not path.exists():
        return []
    lines = path.read_text(encoding="utf-8").splitlines()
    results = []
    for line in lines[-limit:]:
        try:
            results.append(TestResult.model_validate_json(line))
        except Exception:
            pass
    return results


# ── Internal helpers ──────────────────────────────────────────────────────────

def _check_exact(user: str, correct: str) -> bool:
    """Case-insensitive exact match; also checks if user answer starts with correct letter."""
    u = user.strip().lower()
    c = correct.strip().lower()
    if u == c:
        return True
    # MCQ: user might just answer "A" for "A) ..."
    if c.startswith(u + ")") or c.startswith(u + "."):
        return True
    return False
