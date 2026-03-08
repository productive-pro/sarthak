from __future__ import annotations

from pathlib import Path
from typing import Any

from sarthak.core.logging import get_logger
from sarthak.spaces import rag as rag_mod
from sarthak.spaces.models import SkillLevel, SpaceProfile
from sarthak.spaces.store import load_profile
from sarthak.spaces.sub_agents import QuickTestAgent

from .db import RoadmapDB
from .models import QuickTestRow, Roadmap

log = get_logger(__name__)


async def create_quicktest(
    space_dir: Path,
    input_mode: str = "random",
    prompt: str = "",
    chapter_id: str = "",
    topic_id: str = "",
    concept_id: str = "",
    concept_label: str = "",
    level: SkillLevel | None = None,
    background: str = "",
    is_technical: bool = True,
    return_micro: bool = False,
) -> tuple[QuickTestRow, dict[str, Any]] | QuickTestRow:
    db = RoadmapDB(space_dir)
    await db.init()

    roadmap = await db.load_roadmap()
    concept_desc, resolved_label = _resolve_concept_context(
        roadmap, concept_id, concept_label
    )

    profile = _resolve_profile(space_dir, level, background, is_technical)
    log.info("quicktest_generate", space=str(space_dir), concept=resolved_label, mode=input_mode)
    response_md, micro = await _generate_quicktest_md(
        space_dir,
        input_mode,
        prompt,
        concept_desc,
        resolved_label,
        profile,
    )

    qt = QuickTestRow(
        chapter_id=chapter_id,
        topic_id=topic_id,
        concept_id=concept_id,
        prompt=prompt,
        response_md=response_md,
        input_mode=input_mode,
    )
    qt = await db.create_quicktest(qt)

    if roadmap and concept_id:
        cn = roadmap.get_concept(concept_id)
        if cn and qt.id not in cn.quicktests:
            cn.quicktests.append(qt.id)
            await db.save_roadmap(roadmap)

    if return_micro:
        return qt, micro
    return qt


def _resolve_profile(
    space_dir: Path,
    level: SkillLevel | None,
    background: str,
    is_technical: bool,
) -> SpaceProfile:
    profile = load_profile(space_dir)
    if profile:
        return profile
    from sarthak.spaces.models import LearnerProfile, SpaceProfile, SpaceType

    return SpaceProfile(
        space_type=SpaceType.CUSTOM,
        learner=LearnerProfile(
            background=background,
            skill_level=level or SkillLevel.BEGINNER,
            is_technical=is_technical,
        ),
    )


def _resolve_concept_context(
    roadmap: Roadmap | None,
    concept_id: str,
    concept_label: str,
) -> tuple[str, str]:
    concept_desc = ""
    label = concept_label or concept_id or "General"
    if roadmap and concept_id:
        cn = roadmap.get_concept(concept_id)
        if cn:
            concept_desc = cn.description
            if cn.title:
                label = cn.title
    return concept_desc, label


async def _build_learner_context_snippet(space_dir: Path, concept_label: str) -> str:
    """Build a compact context string from LearnerContext signals for quicktest personalization."""
    try:
        from sarthak.spaces.learner_context import build_learner_context
        profile = load_profile(space_dir)
        if not profile:
            return ""
        lc = await build_learner_context(space_dir, profile, days=14)
        parts: list[str] = []

        # Aggregate weak/strong concept signals
        if lc.weak_concepts:
            parts.append(f"Struggling with: {', '.join(lc.weak_concepts[:4])}")
        if lc.strong_concepts:
            parts.append(f"Strong on: {', '.join(lc.strong_concepts[-4:])}")

        # Per-concept evidence: find best matching key (case-insensitive, partial)
        ev = lc.concept_evidence.get(concept_label.lower())
        if ev is None:
            needle = concept_label.lower()
            for key, val in lc.concept_evidence.items():
                if needle in key or key in needle:
                    ev = val
                    break

        if ev:
            if ev.note_count:
                parts.append(f"Notes written on this concept: {ev.note_count} ({ev.note_chars} chars)")
            if ev.test_attempts:
                parts.append(f"Practice test avg: {ev.test_percent:.0f}% over {ev.test_attempts} attempt(s)")
            if ev.times_stuck:
                parts.append(f"Reported stuck {ev.times_stuck} time(s) on this topic")
            if ev.breakthroughs:
                parts.append(f"Breakthrough noted: {ev.breakthroughs[-1][:120]}")

        # Inject recent note snippets for richer context
        if lc.recent_notes:
            matched = [
                n for n in lc.recent_notes
                if concept_label.lower() in (n.get("concept", "") or "").lower()
            ][:2]
            if matched:
                snippets = [n.get("snippet", "")[:200] for n in matched if n.get("snippet")]
                if snippets:
                    parts.append("Recent learner notes:\n" + "\n---\n".join(snippets))

        return "\n".join(parts)
    except Exception as exc:
        log.debug("quicktest_lc_failed", error=str(exc))
        return ""


async def _generate_quicktest_md(
    space_dir: Path,
    input_mode: str,
    prompt: str,
    concept_desc: str,
    concept_label: str,
    profile: SpaceProfile,
) -> tuple[str, dict[str, Any]]:
    agent = QuickTestAgent()
    level = profile.learner.skill_level
    background = profile.learner.background
    is_technical = profile.learner.is_technical

    # Always pull LearnerContext signals to personalize the challenge
    lc_snippet = await _build_learner_context_snippet(space_dir, concept_label)

    if input_mode == "user":
        user_prompt = prompt or "Give me a 5-minute hands-on challenge."
        micro = await agent.generate(
            concept_label,
            level,
            background=background,
            is_technical=is_technical,
            user_prompt=user_prompt,
            notes_context=lc_snippet,
        )
        return _format_quicktest_md(micro, concept_label), micro

    if input_mode == "random":
        micro = await agent.generate(
            concept_label,
            level,
            background=background,
            is_technical=is_technical,
            user_prompt="",
            notes_context=lc_snippet,
        )
        return _format_quicktest_md(micro, concept_label), micro

    # input_mode == "notes" — also pull RAG results and merge with LearnerContext
    results = await rag_mod.search_space_structured(space_dir, concept_desc or concept_label, top_k=3)
    rag_context = "\n---\n".join(r.text for r in results) if results else concept_desc
    context = "\n".join(filter(None, [lc_snippet, rag_context]))
    micro = await agent.generate(
        concept_label,
        level,
        background=background,
        is_technical=is_technical,
        user_prompt="",
        notes_context=context,
    )
    return _format_quicktest_md(micro, concept_label), micro


def _format_quicktest_md(micro: dict[str, Any], concept: str) -> str:
    title = micro.get("title") or f"Quick: {concept}"
    challenge = micro.get("challenge", "")
    success = micro.get("success_criteria", "")
    xp = micro.get("xp_reward", 5)
    return (
        f"# QuickTest — {title}\n\n"
        f"*5 minutes. One concept. Real progress.*\n\n"
        f"## Challenge\n{challenge}\n\n"
        f"## You've succeeded when\n{success}\n\n"
        f"---\n*+{xp} XP*"
    )
