"""
Sarthak Spaces — Signal Optimizer (v2)

Uses LearnerContext as the primary input — real notes, test results,
quicktests, and self-report — instead of weak proxy signals.

Signal hierarchy:
  HIGH   — test results (concept scores, score trends)
           stuck_on (repeated across sessions)
           notes with low concept coverage or no recent notes on mastered concepts
           breakthroughs (positive signal → advance)
  MEDIUM — in-progress concepts with no recent activity
           quicktest pass/fail rates
           time-of-day pattern (from session evidence)
  LOW    — session depth score trend (kept but lowest weight)
           avg focus/active time

Every optimization maps a specific evidence observation → actionable recommendation.
No vague advice.

Public API:
    SignalOptimizer.analyze_from_context(space_dir, profile, lc) → list[SessionOptimization]
    SignalOptimizer.format_optimizations(opts)                   → str
"""
from __future__ import annotations

import statistics
from pathlib import Path
from typing import Any

import structlog

from sarthak.spaces.models import (
    SessionOptimization,
    SpaceProfile,
)
from sarthak.spaces.session_tracker import load_sessions

log = structlog.get_logger(__name__)

_MIN_SESSIONS = 3


class SignalOptimizer:
    """
    Stateless optimizer. Primary entry point: analyze_from_context().
    Legacy entry point: analyze() — builds LearnerContext internally.
    """

    # ── Primary: context-driven ────────────────────────────────────────────────

    def analyze_from_context(
        self,
        space_dir: Path,
        profile: SpaceProfile,
        lc: "LearnerContext",  # noqa: F821
    ) -> list[SessionOptimization]:
        """
        Generate ranked recommendations from a pre-built LearnerContext.
        This is the preferred entry point — call build_learner_context() first.
        """
        opts: list[SessionOptimization] = []

        # HIGH: concepts stuck across sessions or failed in tests
        opts += self._weak_concept_signal(lc)

        # HIGH: test score trends
        opts += self._test_trend_signal(lc)

        # HIGH: mastered concepts with no recent evidence (decay risk)
        opts += self._decay_risk_signal(lc, profile)

        # MEDIUM: in-progress concepts with no recent notes or activity
        opts += self._stalled_concepts_signal(lc)

        # MEDIUM: quicktest signal
        opts += self._quicktest_signal(lc)

        # MEDIUM: time-of-day productivity
        opts += self._time_pattern_signal(lc)

        # LOW: session depth proxy
        opts += self._depth_proxy_signal(space_dir)

        # POSITIVE: recent breakthroughs → advance
        opts += self._breakthrough_signal(lc)

        return self._rank_and_dedupe(opts)

    # analyze() removed — use analyze_from_context() with a pre-built LearnerContext.

    # ── Signal analyzers ───────────────────────────────────────────────────────

    def _weak_concept_signal(self, lc: Any) -> list[SessionOptimization]:
        opts = []
        if not lc.weak_concepts:
            return opts

        # Top 3 weakest by confidence
        ranked = sorted(
            lc.weak_concepts,
            key=lambda c: lc.concept_evidence.get(c).mastery_confidence
            if c in lc.concept_evidence else 0.0
        )[:3]

        # Build a specific observation per concept
        obs_parts = []
        for c in ranked:
            ev = lc.concept_evidence.get(c)
            if ev:
                details = []
                if ev.times_stuck >= 2:
                    details.append(f"stuck {ev.times_stuck}× in sessions")
                if ev.test_attempts > 0 and ev.test_percent < 50:
                    details.append(f"{ev.test_percent:.0f}% on tests")
                if ev.note_count == 0:
                    details.append("no notes written")
                obs_parts.append(f"**{c}** ({'; '.join(details) or 'low confidence'})")

        if not obs_parts:
            return opts

        recommendation = (
            f"Fix **{ranked[0]}** first. Write a 1-page concept note in your own words "
            f"(use `sarthak spaces note --concept \"{ranked[0]}\"`), then run a concept-scoped practice test."
        )
        if len(ranked) > 1:
            recommendation += f" Then address **{ranked[1]}** the same way."

        opts.append(SessionOptimization(
            signal_source="weak_concepts",
            observation=f"Evidence shows low mastery on: {', '.join(obs_parts)}.",
            recommendation=recommendation,
            priority="high",
            xp_bonus=20,
        ))
        return opts

    def _test_trend_signal(self, lc: Any) -> list[SessionOptimization]:
        opts = []
        if len(lc.recent_test_results) < 2:
            return opts

        scores = [t["percent"] for t in sorted(lc.recent_test_results, key=lambda x: x["date"])]
        trend = scores[-1] - scores[0]

        if trend < -10:
            opts.append(SessionOptimization(
                signal_source="test_score_trend",
                observation=f"Test scores are declining ({scores[0]:.0f}% → {scores[-1]:.0f}%). Concepts are getting harder faster than you're consolidating.",
                recommendation="Stop advancing. Spend 2 sessions consolidating weak concepts from recent tests with written notes before any new material.",
                priority="high",
                xp_bonus=10,
            ))
        elif trend > 10:
            opts.append(SessionOptimization(
                signal_source="test_score_trend",
                observation=f"Test scores are improving ({scores[0]:.0f}% → {scores[-1]:.0f}%) — consolidation is working.",
                recommendation="Score trend is excellent. You're ready to advance to the next topic.",
                priority="low",
                xp_bonus=5,
            ))
        return opts

    def _decay_risk_signal(self, lc: Any, profile: SpaceProfile) -> list[SessionOptimization]:
        """Mastered concepts with no recent evidence → decay risk."""
        opts = []
        at_risk = lc.srs_due_by_evidence[:3]
        if not at_risk:
            return opts

        obs_parts = []
        for c in at_risk:
            ev = lc.concept_evidence.get(c)
            if ev:
                if ev.note_count == 0:
                    obs_parts.append(f"**{c}** (no notes, no recent tests)")
                elif ev.test_percent < 50 and ev.test_attempts > 0:
                    obs_parts.append(f"**{c}** ({ev.test_percent:.0f}% on last test)")
                else:
                    obs_parts.append(f"**{c}** (no recent activity)")
            else:
                obs_parts.append(f"**{c}** (no recent activity)")

        opts.append(SessionOptimization(
            signal_source="decay_risk",
            observation=f"Mastered concepts showing decay signals: {', '.join(obs_parts)}.",
            recommendation=f"Review **{at_risk[0]}** — write a summary note from memory, then check it against your sources. This is spaced repetition grounded in your actual notes.",
            priority="high",
            xp_bonus=15,
        ))
        return opts

    def _stalled_concepts_signal(self, lc: Any) -> list[SessionOptimization]:
        """In-progress concepts with no recent notes or test activity."""
        opts = []
        stalled = []
        for c in lc.in_progress_concepts:
            ev = lc.concept_evidence.get(c)
            if ev and ev.note_count == 0 and ev.test_attempts == 0:
                stalled.append(c)

        if not stalled:
            return opts

        opts.append(SessionOptimization(
            signal_source="stalled_concepts",
            observation=f"In-progress concepts with no notes or tests yet: {', '.join(f'**{c}**' for c in stalled[:3])}.",
            recommendation=f"Pick **{stalled[0]}** and write even a short 5-line note on what you know so far. Notes are your primary learning signal.",
            priority="medium",
            xp_bonus=10,
        ))
        return opts

    def _quicktest_signal(self, lc: Any) -> list[SessionOptimization]:
        opts = []
        # Check quicktest pass rate across concepts
        low_qt_concepts = []
        for c, ev in lc.concept_evidence.items():
            if ev.quicktest_attempts >= 2:
                rate = ev.quicktest_passed / ev.quicktest_attempts
                if rate < 0.5:
                    low_qt_concepts.append((c, rate))

        if not low_qt_concepts:
            return opts

        low_qt_concepts.sort(key=lambda x: x[1])
        worst_c, worst_rate = low_qt_concepts[0]
        opts.append(SessionOptimization(
            signal_source="quicktest_rate",
            observation=f"Quicktest pass rate for **{worst_c}** is {worst_rate:.0%} — recurring micro-task failures signal a foundational gap.",
            recommendation=f"Don't do more quicktests on {worst_c} yet. Write a concept note first, then return to quicktests to verify your understanding.",
            priority="medium",
            xp_bonus=10,
        ))
        return opts

    def _time_pattern_signal(self, lc: Any) -> list[SessionOptimization]:
        opts = []
        if not lc.most_productive_time:
            return opts

        opts.append(SessionOptimization(
            signal_source="time_of_day",
            observation=f"Your deepest sessions consistently happen in the {lc.most_productive_time} (highest depth score in that window).",
            recommendation=f"Schedule your hardest new concepts in the {lc.most_productive_time}. Use other times for note review and quicktests only.",
            priority="medium",
            xp_bonus=0,
        ))
        return opts

    def _depth_proxy_signal(self, space_dir: Path) -> list[SessionOptimization]:
        """Low-weight: session depth trend as proxy signal."""
        opts = []
        sessions = load_sessions(space_dir, limit=10)
        if len(sessions) < _MIN_SESSIONS:
            return opts

        scores = [s.signals.depth_score for s in sessions]
        first_half = statistics.mean(scores[:len(scores) // 2])
        second_half = statistics.mean(scores[len(scores) // 2:])
        delta = second_half - first_half

        if delta < -0.20:
            opts.append(SessionOptimization(
                signal_source="session_depth_trend",
                observation=f"Session depth score has dropped ({first_half:.2f} → {second_half:.2f}) — engagement is declining.",
                recommendation="This is a secondary signal — check your notes and test results for the primary cause. Consider a QuickTest session to rebuild momentum.",
                priority="low",
                xp_bonus=5,
            ))
        return opts

    def _breakthrough_signal(self, lc: Any) -> list[SessionOptimization]:
        """Recent breakthroughs → positive signal, push learner to advance."""
        opts = []
        if not lc.recent_breakthroughs:
            return opts

        breakthrough = lc.recent_breakthroughs[0]
        opts.append(SessionOptimization(
            signal_source="breakthrough",
            observation=f"Recent breakthrough recorded: \"{breakthrough[:120]}\"",
            recommendation="A breakthrough means the concept has clicked. Capture it as a note now while fresh, then advance to the next concept. Momentum is high.",
            priority="low",
            xp_bonus=5,
        ))
        return opts

    # ── Utility ────────────────────────────────────────────────────────────────

    def _rank_and_dedupe(self, opts: list[SessionOptimization]) -> list[SessionOptimization]:
        seen: dict[str, SessionOptimization] = {}
        _priority = {"high": 0, "medium": 1, "low": 2}
        for o in opts:
            existing = seen.get(o.signal_source)
            if not existing or _priority[o.priority] < _priority[existing.priority]:
                seen[o.signal_source] = o
        ranked = sorted(seen.values(), key=lambda o: _priority[o.priority])
        log.info("optimizations_generated", count=len(ranked))
        return ranked[:8]

    def format_optimizations(self, opts: list[SessionOptimization]) -> str:
        """Render optimizations as Markdown for TUI / Telegram display."""
        if not opts:
            return "## Session Optimizations\n\nKeep learning — patterns will emerge after a few more sessions."

        priority_label = {"high": "[HIGH]", "medium": "[MED]", "low": "[LOW]"}
        lines = ["## Session Optimizations", ""]
        for o in opts:
            label = priority_label.get(o.priority, "")
            bonus = f" (+{o.xp_bonus} XP if you act on this)" if o.xp_bonus else ""
            lines += [
                f"### {label} {o.signal_source.replace('_', ' ').title()}{bonus}",
                f"**Observation**: {o.observation}",
                f"**Recommendation**: {o.recommendation}",
                "",
            ]
        return "\n".join(lines)
