"""Git Worktree Manager — creates and cleans up isolated repair worktrees for Level 3 code repair."""

from __future__ import annotations

import os
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path


@dataclass
class RepairWorktree:
    failure_id: str
    path: str
    branch: str
    base_commit: str


class WorktreeManager:
    def __init__(self, repo_root: str | Path | None = None) -> None:
        if repo_root is None:
            # Default: apps/api -> parent repo root
            self.repo_root = Path(__file__).resolve().parent.parent.parent.parent.parent
        else:
            self.repo_root = Path(repo_root).resolve()

        self.repairs_dir = self.repo_root.parent / "career-os-repairs"
        self.repairs_dir.mkdir(parents=True, exist_ok=True)

    def _run_git(self, args: list[str], cwd: Path | str | None = None) -> str:
        target_cwd = str(cwd or self.repo_root)
        result = subprocess.run(
            ["git"] + args,
            cwd=target_cwd,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            check=True,
        )
        return result.stdout.strip()

    def get_current_commit(self) -> str:
        return self.get_head_commit()

    def get_head_commit(self) -> str:
        try:
            return self._run_git(["rev-parse", "HEAD"])
        except Exception:
            return "main"

    def create_repair_worktree(self, failure_id: str, base_commit: str | None = None) -> RepairWorktree:
        """Create isolated Git worktree in ../career-os-repairs/repair-<failure_id> starting from base_commit."""
        commit = base_commit or self.head_commit
        worktree_path = self.repairs_dir / f"repair-{failure_id}"
        branch_name = f"repair/{failure_id}"

        # Clean existing worktree directory if stale
        if worktree_path.exists():
            self.remove_worktree_path(worktree_path, branch_name)

        self._run_git(["worktree", "add", str(worktree_path), "-b", branch_name, commit])

        return RepairWorktree(
            failure_id=failure_id,
            path=str(worktree_path),
            branch=branch_name,
            base_commit=commit,
        )

    def remove(self, worktree: RepairWorktree) -> None:
        """Cleanly remove worktree and delete its local repair branch."""
        self.remove_worktree_path(Path(worktree.path), worktree.branch)

    def remove_worktree_path(self, worktree_path: Path, branch_name: str) -> None:
        try:
            self._run_git(["worktree", "remove", str(worktree_path), "--force"])
        except Exception:
            if worktree_path.exists():
                shutil.rmtree(worktree_path, ignore_errors=True)

        try:
            self._run_git(["branch", "-D", branch_name])
        except Exception:
            pass

    @property
    def head_commit(self) -> str:
        return self.get_head_commit()
