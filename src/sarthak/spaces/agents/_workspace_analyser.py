"""
WorkspaceAnalyserAgent — rewired to be the single source of truth for
what the space recommends to the orchestrator each session.

Key improvements over the old version:
  - Calls recommend_with_reasons() so recommendations carry EVIDENCE-BACKED reasons.
  - Injects full LearnerContext summary (weak/strong/in-progress, SRS due, test trends).
  - Surfaces the top SessionOptimization (the single most actionable thing).
  - Uses structured Optimal_Learn sections the orchestrator can parse predictably.
  - Never calls LLM for things that are already known from data (tool list, SRS due, etc.).
    LLM is only used to write the prose narrative.
"""
from __future__ import annotations

import asyncio
import json
import shutil
from pathlib import Path

from sarthak.core.logging import get_logger
from sarthak.features.ai.agents._base import run_llm
from sarthak.spaces.agents._common import _call_llm_json, detect_platform
from sarthak.spaces.models import SpaceContext

log = get_logger(__name__)


class WorkspaceAnalyserAgent:
    """
    Reads the workspace + all learner signals to produce Optimal_Learn.md.

    Optimal_Learn.md is given to the orchestrator at the start of every session.
    It encodes ALL recommendations — what the space wants to tell us — so the
    orchestrator can personalize the session without re-reading 15 separate files.

    What's new:
    - Recommendations now include evidence-backed reasons (from recommend_with_reasons).
    - LearnerContext (weak/strong/SRS due/test scores) is embedded directly.
    - Top SessionOptimization is surfaced as a single actionable call-to-action.
    - Workspace signals (tools, files) are kept but are no longer the whole story.
    """

    @property
    def SYSTEM(self) -> str:  # noqa: N802
        """Loaded from data/agents/spaces/workspace-analyser.md at first access."""
        from sarthak.spaces.agents._common import _load_system
        return _load_system("workspace-analyser")

    # ── Workspace snapshot ─────────────────────────────────────────────────────

    def _sample_workspace(self, workspace_dir: Path) -> dict:
        """Sample workspace without reading file contents."""
        ws = workspace_dir
        if not ws.exists():
            return {"top_dirs": [], "hidden_dirs": [], "sampled_files": [],
                    "config_files": [], "agents_md": [], "total_file_count_estimate": 0,
                    "space_memory": ""}

        top_dirs    = [p for p in ws.iterdir() if p.is_dir() and not p.name.startswith(".")]
        hidden_dirs = [p for p in ws.iterdir() if p.is_dir() and p.name.startswith(".")]

        all_files: list[Path] = []
        for p in ws.rglob("*"):
            rel = p.relative_to(ws)
            if p.is_file() and not any(part.startswith(".") for part in rel.parts):
                if len(rel.parts) <= 4:
                    all_files.append(p)
                if len(all_files) >= 200:
                    break

        sampled_paths = [str(p.relative_to(ws)) for p in all_files[:40]]

        found_configs: list[str] = []
        for name in ["pyproject.toml", "requirements.txt", "environment.yml",
                     "Makefile", "docker-compose.yml", "Dockerfile"]:
            if (ws / name).exists():
                found_configs.append(name)
        if (ws / ".vscode").exists():
            found_configs.append(".vscode/")

        agents_md_content: list[str] = []
        for p in list(ws.rglob("AGENTS.md"))[:3]:
            try:
                text = p.read_text(encoding="utf-8")[:600]
                agents_md_content.append(f"[{p.relative_to(ws)}]\n{text}")
            except Exception:
                pass

        space_memory_block = ""
        try:
            from sarthak.spaces.memory import read_context_block
            space_memory_block = read_context_block(ws, max_chars=2400)
        except Exception:
            pass

        return {
            "top_dirs":                 [d.name for d in top_dirs],
            "hidden_dirs":              [d.name for d in hidden_dirs],
            "sampled_files":            sampled_paths,
            "config_files":             found_configs,
            "agents_md":                agents_md_content,
            "total_file_count_estimate": len(all_files),
            "space_memory":             space_memory_block,
        }

    # ── Recommendation block ───────────────────────────────────────────────────

    def _build_recommendation_block(self, ctx: SpaceContext) -> str:
        """
        Build a data-driven recommendation block using recommend_with_reasons().
        Called via asyncio.to_thread() so a fresh event loop is always safe here.
        """
        try:
            from sarthak.spaces.roadmap.db import RoadmapDB
            from sarthak.spaces.roadmap.recommend import recommend_with_reasons
            import asyncio

            async def _load():
                db = RoadmapDB(Path(ctx.workspace_dir))
                await db.init()
                return await db.load_roadmap()

            # We are always called from asyncio.to_thread(), so asyncio.run() is safe.
            roadmap = asyncio.run(_load())

            if not roadmap:
                return ""

            lp = ctx.profile.learner
            recs = recommend_with_reasons(
                roadmap,
                top_k=5,
                mastered=lp.mastered_concepts,
                struggling=lp.struggling_concepts,
                review_due=[],   # will be overridden by LearnerContext below
            )
            if not recs:
                return ""

            lines = []
            for i, (concept, reason) in enumerate(recs, 1):
                lines.append(f"{i}. **{concept.title}** — {reason}")
            return "\n".join(lines)
        except Exception as exc:
            log.debug("recommendation_block_failed", error=str(exc))
            return ""

    # ── LearnerContext block ───────────────────────────────────────────────────

    async def _build_learner_signals_block(self, ctx: SpaceContext) -> tuple[str, str]:
        """
        Returns (learner_signals_md, srs_due_csv) from LearnerContext.
        This replaces vague proxy signals with real evidence.
        """
        try:
            from sarthak.spaces.learner_context import build_learner_context, learner_context_for_prompt
            lc = await build_learner_context(Path(ctx.workspace_dir), ctx.profile, days=14)
            return learner_context_for_prompt(lc), ", ".join(lc.srs_due_by_evidence[:4])
        except Exception as exc:
            log.debug("learner_context_block_failed", error=str(exc))
            return "", ""

    # ── Top optimization ───────────────────────────────────────────────────────

    async def _top_optimization(self, ctx: SpaceContext) -> str:
        """Return the single most actionable optimization or empty string."""
        try:
            from sarthak.spaces.learner_context import build_learner_context
            from sarthak.spaces.optimizer import SignalOptimizer
            lc = await build_learner_context(Path(ctx.workspace_dir), ctx.profile, days=14)
            opts = SignalOptimizer().analyze_from_context(Path(ctx.workspace_dir), ctx.profile, lc)
            if opts:
                top = opts[0]
                return f"**[{top.priority.upper()}]** {top.recommendation}"
            return ""
        except Exception as exc:
            log.debug("top_optimization_failed", error=str(exc))
            return ""

    # ── Main entrypoint ────────────────────────────────────────────────────────

    async def analyse(self, ctx: SpaceContext) -> str:
        """Produce Optimal_Learn.md content as a string."""
        workspace_dir = Path(ctx.workspace_dir)

        # Run all data collection in parallel
        fresh_memory_task   = self._get_fresh_memory(workspace_dir)
        signals_task        = self._build_learner_signals_block(ctx)
        optimization_task   = self._top_optimization(ctx)
        snapshot_task       = asyncio.to_thread(self._sample_workspace, workspace_dir)

        fresh_memory, (learner_signals, srs_due), top_opt, snapshot = await asyncio.gather(
            fresh_memory_task, signals_task, optimization_task, snapshot_task
        )
        if fresh_memory:
            snapshot["space_memory"] = fresh_memory

        # Synchronous recommendation block (uses roadmap DB via sync shim)
        rec_block = await asyncio.to_thread(self._build_recommendation_block, ctx)

        p = ctx.profile.learner
        prompt = (
            f"Domain: {ctx.profile.domain}\n"
            f"Learner level: {p.skill_level.value}\n"
            f"Goal: {p.goal or 'mastery'}\n"
            f"Background: {p.background or 'not specified'}\n"
            f"Mastered concepts (last 5): {json.dumps(p.mastered_concepts[-5:])}\n"
            f"Struggling: {json.dumps(p.struggling_concepts)}\n"
            f"SRS due: {srs_due or 'none'}\n"
            f"Sessions done: {p.total_sessions}\n\n"
            f"## Workspace snapshot\n"
            f"Top-level dirs: {snapshot['top_dirs']}\n"
            f"Config files found: {snapshot['config_files']}\n"
            f"Sampled file paths (first 40): {snapshot['sampled_files']}\n"
            f"Total files estimate: {snapshot['total_file_count_estimate']}\n"
        )
        if snapshot["agents_md"]:
            prompt += f"\n## AGENTS.md content\n{'---'.join(snapshot['agents_md'])}\n"
        if snapshot.get("space_memory"):
            prompt += f"\n## Sarthak Space Memory\n{snapshot['space_memory']}\n"
        if learner_signals:
            prompt += f"\n## Learner Signals (from real data)\n{learner_signals}\n"
        if rec_block:
            prompt += f"\n## Evidence-backed Recommendations\n{rec_block}\n"
        if top_opt:
            prompt += f"\n## Top Session Optimization\n{top_opt}\n"

        try:
            return await run_llm(self.SYSTEM, prompt, tier="balanced")
        except Exception as exc:
            log.warning("workspace_analyser_failed", error=str(exc))
            return self._fallback(ctx, snapshot, rec_block, top_opt)

    async def _get_fresh_memory(self, workspace_dir: Path) -> str:
        try:
            from sarthak.spaces.memory import read_context_block_async
            return await read_context_block_async(workspace_dir, max_chars=2400)
        except Exception:
            return ""

    def _fallback(self, ctx: SpaceContext, snapshot: dict, rec_block: str, top_opt: str) -> str:
        """Minimal Optimal_Learn when LLM is unavailable — still useful."""
        p = ctx.profile.learner
        lines = [
            "# Optimal_Learn",
            "",
            "## Workspace State",
            f"Workspace at `{ctx.workspace_dir}`. "
            f"Dirs: {', '.join(snapshot['top_dirs'][:8])}. "
            f"Last mastered: {p.mastered_concepts[-1] if p.mastered_concepts else 'none'}.",
            "",
        ]
        if p.struggling_concepts:
            lines += [
                "## Learner Signals",
                f"Struggling: {', '.join(p.struggling_concepts[:5])}.",
                "",
            ]
        if rec_block:
            lines += ["## Recommendations (with reasons)", rec_block, ""]
        if top_opt:
            lines += ["## Session Focus", top_opt, ""]
        lines += [
            "## Environment",
            f"Configs: {', '.join(snapshot['config_files']) or 'none'}",
        ]
        return "\n".join(lines)

    def write_optimal_learn(self, workspace_dir: Path, content: str) -> Path:
        """Write Optimal_Learn.md to .spaces/ directory."""
        out_dir = workspace_dir / ".spaces"
        out_dir.mkdir(parents=True, exist_ok=True)
        path = out_dir / "Optimal_Learn.md"
        path.write_text(content, encoding="utf-8")
        return path
