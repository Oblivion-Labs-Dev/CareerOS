from __future__ import annotations

import re
import subprocess
import uuid
from pathlib import Path
from typing import Any

from repair_orchestrator.agents.adapter import AgentRun, AgentWorkspace, CodingAgentAdapter
from repair_orchestrator.config import settings
from repair_orchestrator.security.guardrails import validate_patch_files


class MockCodingAgentAdapter(CodingAgentAdapter):
    """Local adapter that creates an isolated worktree and records a simulated patch."""

    def __init__(self) -> None:
        self._runs: dict[str, AgentRun] = {}

    async def start(self, task: dict[str, Any], workspace: AgentWorkspace) -> AgentRun:
        run_id = str(uuid.uuid4())
        short = re.sub(r"[^a-z0-9]+", "-", task.get("title", "repair").lower())[:32].strip("-")
        branch = f"repair/{task['taskId'][:8]}-{short or 'fix'}"
        worktree_path = str(Path(workspace.worktrees_dir) / run_id[:8])
        run = AgentRun(
            run_id=run_id,
            task_id=task["taskId"],
            branch=branch,
            worktree_path=worktree_path,
            status="running",
            commands_run=[],
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
                f"# Mock repair patch for {task['taskId']}\n# Incident: {task.get('incidentFingerprint')}\n",
                encoding="utf-8",
            )
            run.changed_files = [str(patch_file.relative_to(worktree_path)).replace("\\", "/")]
            run.diff_summary = f"Added demo patch file for task {task['taskId']}"
            run.commands_run.append(f"git worktree add {worktree_path} -b {branch}")
            run.output = "Mock agent completed minimal patch in isolated worktree."
        else:
            run.output = "Git unavailable; recorded simulated patch metadata only."
            run.changed_files = ["tools/repair-orchestrator/demo-patch.txt"]
            run.diff_summary = "Simulated patch (no git worktree)"

        ok, violations = validate_patch_files(run.changed_files, len(run.diff_summary.encode("utf-8")))
        if not ok:
            run.status = "failed"
            run.output += "\nGuardrail violations: " + "; ".join(violations)
        else:
            run.status = "completed"
        return run

    async def get_status(self, run_id: str) -> dict[str, Any]:
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

    async def cancel(self, run_id: str) -> None:
        run = self._runs.get(run_id)
        if run:
            run.status = "cancelled"


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
            timeout=settings.max_execution_seconds,
        )
    except subprocess.CalledProcessError as exc:
        run.status = "failed"
        run.output = exc.stderr or str(exc)


def get_adapter(name: str | None = None) -> CodingAgentAdapter:
    selected = (name or settings.agent_adapter).lower()
    if selected == "mock":
        return MockCodingAgentAdapter()
    raise ValueError(f"Unsupported agent adapter: {selected}")
