"""Promotion Manager — promotes validated patches into main working tree and handles automated rollback."""

from __future__ import annotations

import subprocess
from dataclasses import dataclass
from pathlib import Path

from app.services.application_assistant.persistence import get_kv, set_kv, session_scope
from app.services.application_assistant.worktree_manager import RepairWorktree, WorktreeManager


@dataclass
class PromotionResult:
    promoted: bool
    commit: str
    known_good_commit: str
    message: str


class PromotionManager:
    def __init__(self, repo_root: str | Path | None = None) -> None:
        self.wt_manager = WorktreeManager(repo_root)

    def get_known_good_commit(self) -> str:
        return self.get_known_good_commit_sync()

    def get_known_good_commit_sync(self) -> str:
        with session_scope() as db:
            kv = get_kv(db, "known_good_commit")
            if kv:
                return str(kv)
        return self.wt_manager.get_head_commit()

    def set_known_good_commit_sync(self, commit: str) -> None:
        with session_scope() as db:
            set_kv(db, "known_good_commit", commit)

    def promote_worktree_repair(self, worktree: RepairWorktree, expected_base_commit: str) -> PromotionResult:
        """Promote repair commit from worktree to main repository."""
        current_head = self.wt_manager.get_head_commit()
        if current_head != expected_base_commit:
            return PromotionResult(
                promoted=False,
                commit="",
                known_good_commit=self.get_known_good_commit_sync(),
                message=f"Base commit mismatch: HEAD is {current_head}, repair started at {expected_base_commit}",
            )

        try:
            # Create a commit inside the worktree if uncommitted changes exist
            subprocess.run(
                ["git", "commit", "-am", f"fix(automation): repair failure {worktree.failure_id}"],
                cwd=worktree.path,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
            )
            repair_commit = self.wt_manager._run_git(["rev-parse", "HEAD"], cwd=worktree.path)

            # Cherry-pick into main working tree
            self.wt_manager._run_git(["cherry-pick", repair_commit])
            new_head = self.wt_manager.get_head_commit()
            self.set_known_good_commit_sync(new_head)

            return PromotionResult(
                promoted=True,
                commit=new_head,
                known_good_commit=new_head,
                message=f"Repair patch successfully promoted into main at {new_head[:7]}",
            )
        except Exception as exc:
            self.rollback_to_known_good()
            return PromotionResult(
                promoted=False,
                commit="",
                known_good_commit=self.get_known_good_commit_sync(),
                message=f"Promotion failed and rolled back: {exc}",
            )

    def rollback_to_known_good(self) -> str:
        """Roll back main working tree to knownGoodCommit."""
        known_good = self.get_known_good_commit_sync()
        try:
            self.wt_manager._run_git(["reset", "--hard", known_good])
            return known_good
        except Exception:
            return known_good
