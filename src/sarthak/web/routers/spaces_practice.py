"""
spaces_practice.py — Practice test generation and grading endpoints.

All routes: /api/spaces/{space_id}/practice/*
"""
from __future__ import annotations

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from sarthak.web.routers.helpers import resolve_space_dir

router = APIRouter()


class PracticeGenerateReq(BaseModel):
    directory: str = ""  # optional — resolved from space_id if omitted
    test_type: str = "concept"
    scope: str = ""
    source: str = "llm"
    source_prompt: str = ""
    seconds_per_question: int = 120
    n_questions: int | None = None


@router.post("/api/spaces/{space_id}/practice/generate")
async def practice_generate_api(space_id: str, body: PracticeGenerateReq) -> dict:
    from sarthak.spaces.orchestrator import SpacesOrchestrator
    ws = resolve_space_dir(space_id, body.directory)
    orch = SpacesOrchestrator(ws)
    profile = orch._load_or_init()
    ctx = orch._build_ctx(profile)
    test = await orch._practice.create_test(
        ctx,
        test_type=body.test_type,
        scope=body.scope,
        source=body.source,
        source_prompt=body.source_prompt,
        seconds_per_question=body.seconds_per_question,
        n_questions=body.n_questions,
    )
    return test.model_dump()


class PracticeGradeReq(BaseModel):
    directory: str = ""  # optional — resolved from space_id if omitted
    test_id: str
    answers: dict[str, str] = {}
    time_taken: dict[str, int] = {}


@router.post("/api/spaces/{space_id}/practice/grade")
async def practice_grade_api(space_id: str, body: PracticeGradeReq) -> dict:
    from sarthak.spaces.practice import PracticeEngine
    from sarthak.spaces.models import PracticeTest

    space_dir = resolve_space_dir(space_id, body.directory)
    tests_file = space_dir / ".spaces" / "tests.jsonl"
    if not tests_file.exists():
        raise HTTPException(404, "No tests found")

    test = None
    for line in tests_file.read_text().splitlines():
        try:
            t = PracticeTest.model_validate_json(line)
            if t.test_id == body.test_id:
                test = t
                break  # early-exit once found
        except Exception:
            pass
    if not test:
        raise HTTPException(404, f"Test {body.test_id!r} not found")

    engine = PracticeEngine()
    result = await engine.grade_test(test, body.answers, body.time_taken)

    try:
        from sarthak.storage.activity_store import write_activity
        await write_activity(
            activity_type="practice_test",
            space_dir=str(space_dir),
            concept_id=test.scope,
            concept_title=test.scope,
            content_text="\n".join(
                f"Q: {q.question}\nA: {body.answers.get(q.question_id, '')}"
                for q in test.questions
            )[:4096],
            metadata={
                "test_id": result.test_id,
                "percent": result.percent,
                "passed": result.passed,
                "weak": result.weak_concepts,
                "strong": result.strong_concepts,
                "time_taken": body.time_taken,
            },
        )
    except Exception:
        pass

    return result.model_dump()
