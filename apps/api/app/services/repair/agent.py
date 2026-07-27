from __future__ import annotations

import re
import subprocess
import uuid
from pathlib import Path
from typing import Any

from app.config import settings
from app.services.repair.types import AgentRun, AgentWorkspace, CodingAgentAdapter, RepairTask


class MockCodingAgentAdapter:
    """Default POC adapter — isolated worktree, no push/merge/deploy."""

    def __init__(self) -> None:
        self._runs: dict[str, AgentRun] = {}

    def start(self, task: RepairTask, workspace: AgentWorkspace) -> AgentRun:
        run_id = str(uuid.uuid4())
        slug = re.sub(r"[^a-z0-9]+", "-", task.title.lower())[:28].strip("-") or "fix"
        branch = f"repair/{task.task_id[:8]}-{slug}"
        worktree_path = str(Path(workspace.worktrees_dir) / run_id[:8])
        run = AgentRun(
            run_id=run_id,
            task_id=task.task_id,
            branch=branch,
            worktree_path=worktree_path,
            status="running",
        )
        self._runs[run_id] = run

        repo = Path(workspace.repo_root)
        worktrees_root = Path(workspace.worktrees_dir)
        worktrees_root.mkdir(parents=True, exist_ok=True)

        if _git_available(repo):
            _create_worktree(repo, branch, Path(worktree_path), run)
            patch_file = Path(worktree_path) / "tools" / "repair-orchestrator" / "demo-patch.txt"
            patch_file.parent.mkdir(parents=True, exist_ok=True)
            patch_file.write_text(
                f"# Mock repair patch for {task.task_id}\n# Fingerprint: {task.fingerprint}\n",
                encoding="utf-8",
            )
            run.changed_files = [str(patch_file.relative_to(worktree_path)).replace("\\", "/")]
            run.diff_summary = f"Added regression patch placeholder for {task.title}"
            run.commands_run.append(f"git worktree add {worktree_path} -b {branch}")
            run.output = "Mock agent completed minimal patch in isolated worktree."
            run.status = "completed"
        else:
            run.changed_files = ["tools/repair-orchestrator/demo-patch.txt"]
            run.diff_summary = "Simulated patch (git unavailable)"
            run.output = "Mock agent recorded patch metadata without git worktree."
            run.status = "completed"

        if _touches_protected(run.changed_files):
            run.status = "failed"
            run.output += "\nBlocked: protected file modification attempted."

        return run

    def get_status(self, run_id: str) -> dict[str, Any]:
        run = self._runs.get(run_id)
        if not run:
            return {"runId": run_id, "status": "unknown"}
        return {
            "runId": run.run_id,
            "taskId": run.task_id,
            "status": run.status,
            "branch": run.branch,
            "worktreePath": run.worktree_path,
            "changedFiles": run.changed_files,
            "diffSummary": run.diff_summary,
            "commandsRun": run.commands_run,
            "output": run.output,
        }

    def cancel(self, run_id: str) -> None:
        run = self._runs.get(run_id)
        if run:
            run.status = "cancelled"


def _touches_protected(files: list[str]) -> bool:
    protected_prefixes = (".env", ".github/", "apps/extension/manifest.json")
    for file_path in files:
        normalized = file_path.replace("\\", "/")
        if any(normalized == prefix.rstrip("/") or normalized.startswith(prefix) for prefix in protected_prefixes):
            return True
    return False


def _git_available(repo: Path) -> bool:
    if not (repo / ".git").exists():
        return False
    try:
        subprocess.run(
            ["git", "-C", str(repo), "rev-parse", "--is-inside-work-tree"],
            check=True,
            capture_output=True,
            text=True,
        )
        return True
    except (subprocess.CalledProcessError, FileNotFoundError):
        return False


def _create_worktree(repo: Path, branch: str, worktree_path: Path, run: AgentRun) -> None:
    if worktree_path.exists():
        return
    try:
        subprocess.run(
            ["git", "-C", str(repo), "worktree", "add", "-B", branch, str(worktree_path)],
            check=True,
            capture_output=True,
            text=True,
            timeout=120,
        )
    except subprocess.CalledProcessError as exc:
        run.status = "failed"
        run.output = exc.stderr or str(exc)


def get_agent_adapter(name: str | None = None) -> CodingAgentAdapter:
    selected = (name or settings.career_os_repair_agent_adapter).lower()
    if selected == "mock":
        return MockCodingAgentAdapter()
    raise ValueError(f"Unsupported repair agent adapter: {selected}")
