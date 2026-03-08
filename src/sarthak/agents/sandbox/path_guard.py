"""
Sarthak Agent Sandbox — PathGuard.

Validates every filesystem path an agent attempts to access.
Resolves symlinks and rejects any path that escapes the declared roots.
Used by the file_read tool and shell CWD enforcement.
"""
from __future__ import annotations

from pathlib import Path

from sarthak.agents.sandbox.config import SandboxConfig
from sarthak.agents.sandbox.audit import emit


class PathViolation(PermissionError):
    """Raised when an agent attempts to access a path outside its sandbox."""


class PathGuard:
    """
    Validates read and write access against roots declared in SandboxConfig.

    All methods raise PathViolation on denial; they never silently return None.
    """

    def __init__(self, cfg: SandboxConfig) -> None:
        self._cfg = cfg
        self._write_roots = [p.resolve() for p in cfg.write_roots]
        self._read_roots  = [p.resolve() for p in cfg.read_roots]

    # ── Public API ────────────────────────────────────────────────────────────

    def check_read(self, path: str | Path) -> Path:
        """Return resolved path if readable, else raise PathViolation."""
        resolved = self._resolve(path)
        if self._under_any(resolved, self._write_roots):
            return resolved  # write roots are implicitly readable
        if self._under_any(resolved, self._read_roots):
            return resolved
        self._deny("read", resolved)

    def check_write(self, path: str | Path) -> Path:
        """Return resolved path if writable, else raise PathViolation."""
        resolved = self._resolve(path)
        if self._under_any(resolved, self._write_roots):
            return resolved
        self._deny("write", resolved)

    def safe_cwd(self, requested: str) -> str:
        """
        Return a safe working directory for subprocess execution.

        - Space agents: cwd = space_dir (if declared) or home
        - System agents: cwd = ~/.sarthak_ai
        """
        from sarthak.agents.models import AgentScope

        if requested:
            try:
                return str(self.check_write(requested))
            except PathViolation:
                pass

        if self._cfg.scope == AgentScope.SPACE and self._cfg.write_roots:
            # First write root for space agents is space_dir/.spaces
            candidate = self._cfg.write_roots[0].parent
            if candidate.exists():
                return str(candidate)

        fallback = Path.home() / ".sarthak_ai"
        fallback.mkdir(parents=True, exist_ok=True)
        return str(fallback)

    # ── Internals ─────────────────────────────────────────────────────────────

    @staticmethod
    def _resolve(path: str | Path) -> Path:
        p = Path(path)
        # resolve() follows symlinks; if path doesn't exist yet, resolve parent
        try:
            return p.resolve(strict=True)
        except (FileNotFoundError, RuntimeError):
            return p.resolve()

    @staticmethod
    def _under_any(path: Path, roots: list[Path]) -> bool:
        for root in roots:
            try:
                path.relative_to(root)
                return True
            except ValueError:
                continue
        return False

    def _deny(self, op: str, path: Path) -> None:
        emit(
            "agent_path_violation",
            agent_id=self._cfg.agent_id,
            operation=op,
            path=str(path),
            write_roots=[str(r) for r in self._write_roots],
            read_roots=[str(r) for r in self._read_roots],
        )
        raise PathViolation(
            f"Agent '{self._cfg.agent_id}' attempted {op} outside sandbox: {path}"
        )
