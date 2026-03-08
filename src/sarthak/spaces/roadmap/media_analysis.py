"""
Media Analysis — AI feedback on recorded audio/video.

Features powered by a single LLM call after Whisper transcription:
  1. analyze(note_id)         → AI feedback on the recording (clarity, correctness, gaps)
  2. teach_it_back(note_id)   → Feynman score: compares explanation vs concept RAG context
  3. transcript_search(query) → Full-text search across all VTT/transcript body_md
  4. media_to_flashcards()    → Extract SRS cards from transcript
  5. speaking_stats()         → WPM + filler word count from VTT (no LLM needed)
"""
from __future__ import annotations

import re
from pathlib import Path

from sarthak.features.ai.agents._base import run_llm, parse_json_response
from sarthak.core.logging import get_logger
from sarthak.spaces import rag as rag_mod

log = get_logger(__name__)

async def _llm_json(system: str, prompt: str, fallback: dict) -> dict:
    try:
        raw = await run_llm(system, prompt)
        return parse_json_response(raw)
    except Exception as exc:
        log.warning("media_analysis_failed", error=str(exc))
        return fallback


# ── 1. General AI feedback ────────────────────────────────────────────────────

_FEEDBACK_SYSTEM = """You are a precise learning coach. Given a transcript of a learner
explaining or discussing a concept, give structured feedback.
Output ONLY valid JSON:
{
  "score": 0-10,
  "clarity": "one sentence",
  "strengths": ["..."],
  "gaps": ["specific missing point or error"],
  "filler_ratio": 0.0-1.0,
  "summary": "2-sentence overall assessment",
  "next_step": "one concrete suggestion"
}"""

async def analyze_transcript(transcript: str, concept_title: str) -> dict:
    if not transcript.strip():
        return {"score": 0, "summary": "No speech detected.", "strengths": [], "gaps": [], "next_step": "Record again with audio."}
    prompt = f"Concept: {concept_title}\nTranscript:\n{transcript[:4000]}"
    return await _llm_json(_FEEDBACK_SYSTEM, prompt, {
        "score": 5, "clarity": "Could not analyze.", "strengths": [], "gaps": [],
        "filler_ratio": 0.0, "summary": "Analysis unavailable.", "next_step": "Try again.",
    })


# ── 2. Feynman / Teach-It-Back scoring ───────────────────────────────────────

_FEYNMAN_SYSTEM = """You are a Feynman Technique evaluator. Compare the learner's spoken
explanation against the reference material and score how well they understand it.
Output ONLY valid JSON:
{
  "feynman_score": 0-10,
  "covered": ["concepts correctly explained"],
  "missed": ["important concepts not mentioned"],
  "misconceptions": ["incorrect statements made"],
  "verdict": "one sentence: do they understand this concept?",
  "suggestion": "what to re-study"
}"""

async def teach_it_back(transcript: str, concept_title: str, space_dir: Path) -> dict:
    if not transcript.strip():
        return {"feynman_score": 0, "verdict": "No speech detected.", "covered": [], "missed": [], "misconceptions": []}
    results = await rag_mod.search_space_structured(space_dir, concept_title, top_k=3)
    reference = "\n---\n".join(r.text for r in results) if results else f"Concept: {concept_title}"
    prompt = (
        f"Concept: {concept_title}\n\n"
        f"Reference material:\n{reference[:2000]}\n\n"
        f"Learner's explanation (transcript):\n{transcript[:2000]}"
    )
    return await _llm_json(_FEYNMAN_SYSTEM, prompt, {
        "feynman_score": 5, "verdict": "Analysis unavailable.", "covered": [], "missed": [], "misconceptions": [],
    })


# ── 3. Transcript / VTT search ────────────────────────────────────────────────

def search_transcripts(notes: list[dict], query: str) -> list[dict]:
    """Simple substring search across body_md of media notes. No LLM needed."""
    q = query.lower()
    hits = []
    for note in notes:
        text = (note.get("body_md") or "").lower()
        if q in text:
            # Find snippet around first hit
            idx = text.find(q)
            snippet = note.get("body_md", "")[max(0, idx-60):idx+120].strip()
            hits.append({**note, "snippet": snippet})
    return hits


# ── 4. Transcript → flashcards ────────────────────────────────────────────────

_FLASHCARD_SYSTEM = """Extract 3-5 concise question/answer flashcards from this transcript.
Output ONLY valid JSON: {"cards": [{"q": "...", "a": "..."}]}"""

async def transcript_to_flashcards(transcript: str, concept_title: str) -> list[dict]:
    if not transcript.strip():
        return []
    prompt = f"Concept: {concept_title}\nTranscript:\n{transcript[:3000]}"
    result = await _llm_json(_FLASHCARD_SYSTEM, prompt, {"cards": []})
    return result.get("cards", [])


# ── 5. Speaking stats (no LLM) ───────────────────────────────────────────────

_FILLERS = {"um", "uh", "like", "you know", "basically", "actually", "literally", "right", "okay", "so"}

def vtt_to_plain(vtt: str) -> str:
    """Strip VTT timestamps and return plain text."""
    lines = []
    for line in vtt.splitlines():
        if "-->" in line or line.strip() == "WEBVTT" or not line.strip():
            continue
        lines.append(line.strip())
    return " ".join(lines)

def speaking_stats(vtt_or_text: str, duration_secs: float = 0) -> dict:
    plain = vtt_to_plain(vtt_or_text) if "WEBVTT" in vtt_or_text else vtt_or_text
    words = plain.split()
    word_count = len(words)

    # Duration from VTT if not provided
    if not duration_secs and "WEBVTT" in vtt_or_text:
        ts = re.findall(r"(\d+):(\d+):(\d+)\.(\d+)\s*-->", vtt_or_text)
        if ts:
            last = ts[-1]
            duration_secs = int(last[0]) * 3600 + int(last[1]) * 60 + int(last[2])

    wpm = round(word_count / (duration_secs / 60)) if duration_secs > 0 else 0
    text_lower = plain.lower()
    filler_count = sum(text_lower.count(f) for f in _FILLERS)
    filler_pct = round(filler_count / word_count * 100, 1) if word_count else 0

    return {
        "word_count": word_count,
        "wpm": wpm,
        "filler_count": filler_count,
        "filler_pct": filler_pct,
        "duration_secs": int(duration_secs),
    }
