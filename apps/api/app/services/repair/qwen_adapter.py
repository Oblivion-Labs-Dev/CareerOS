from __future__ import annotations

import json
import logging
import re
import subprocess
import uuid
from pathlib import Path
from typing import Any

from app.config import settings
from app.services.application_assistant.llm_client import LLMClient
from app.services.repair.self_healing_prompt import SELF_HEALING_SYSTEM_PROMPT
from app.services.repair.types import AgentRun, AgentWorkspace, CodingAgentAdapter, RepairTask

logger = logging.getLogger(__name__)


class QwenCodingAgentAdapter:
    """Real LLM-powered repair adapter using Qwen/Ollama with strict deterministic guardrails."""

    def __init__(self, llm_client: LLMClient | None = None) -> None:
        self._runs: dict[str, AgentRun] = {}
        self._client = llm_client or LLMClient(
            base_url=getattr(settings, "application_assistant_llm_base_url", "http://localhost:11434/v1"),
            model=getattr(settings, "application_assistant_llm_model", "qwen3:8b") or "qwen3:8b",
            api_key=getattr(settings, "application_assistant_llm_api_key", ""),
            timeout=120,
        )

    def start(self, task: RepairTask, workspace: AgentWorkspace) -> AgentRun:
        import asyncio

        return asyncio.run(self.start_async(task, workspace))

    async def start_async(self, task: RepairTask, workspace: AgentWorkspace) -> AgentRun:
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

        if not _git_available(repo):
            run.status = "failed"
            run.output = "Git repository not available for creating isolated worktree."
            return run

        # 1. Create worktree
        _create_worktree(repo, branch, Path(worktree_path), run)
        if run.status == "failed":
            return run

        # 2. Gather source context from suspected files
        source_context = self._read_source_context(Path(worktree_path), task.suspected_source_files)

        # 3. Build user prompt
        user_prompt = self._build_user_prompt(task, source_context)

        # 4. Call Qwen
        response = await self._client.complete(
            user_prompt,
            system=SELF_HEALING_SYSTEM_PROMPT,
            response_schema={
                "type": "object",
                "properties": {
                    "status": {"type": "string"},
                    "root_cause": {"type": "string"},
                    "hypothesis": {"type": "string"},
                    "changes": {"type": "array"},
                    "verification": {"type": "string"},
                    "files_changed": {"type": "array"},
                    "remaining_risk": {"type": "string"},
                },
            },
        )

        if not response.get("success"):
            run.status = "failed"
            run.output = f"LLM error: {response.get('error')}"
            return run

        data = response.get("data")
        if not isinstance(data, dict):
            run.status = "failed"
            run.output = "Invalid structured output received from repair agent."
            return run

        run.hypothesis = data.get("hypothesis", "")
        run.root_cause = data.get("root_cause", "")
        run.remaining_risk = data.get("remaining_risk", "")
        changes = data.get("changes", [])

        # 5. Apply changes deterministically
        applied_files: list[str] = []
        for change in changes:
            if not isinstance(change, dict):
                continue
            rel_file = change.get("file", "").replace("\\", "/").lstrip("/")
            search_str = change.get("search", "")
            replace_str = change.get("replace", "")

            if not rel_file or not search_str:
                continue

            target_path = Path(worktree_path) / rel_file
            if not target_path.is_file():
                continue

            content = target_path.read_text(encoding="utf-8")
            if search_str in content:
                new_content = content.replace(search_str, replace_str, 1)
                target_path.write_text(new_content, encoding="utf-8")
                applied_files.append(rel_file)

        run.changed_files = applied_files
        run.diff_summary = f"Root cause: {run.root_cause}. Hypothesis: {run.hypothesis}"
        run.output = json.dumps(data, indent=2)

        # Check protected files guardrail
        if _touches_protected(run.changed_files):
            run.status = "failed"
            run.output += "\nBlocked: protected file modification attempted."
            return run

        if not run.changed_files:
            run.status = "failed"
            run.output += "\nNo valid changes could be applied to repository files."
            return run

        run.status = "completed"
        return run

    def _read_source_context(self, worktree: Path, suspected_files: list[str]) -> str:
        snippets = []
        for rel in suspected_files[:4]:
            p = worktree / rel.replace("\\", "/").lstrip("/")
            if p.is_file():
                try:
                    text = p.read_text(encoding="utf-8")[:4000]
                    snippets.append(f"--- File: {rel} ---\n{text}\n")
                except Exception:
                    pass
        return "\n".join(snippets)

    def _build_user_prompt(self, task: RepairTask, source_context: str) -> str:
        prompt_parts = [
            f"Diagnose and provide the minimal fix for this failure.",
            f"Title: {task.title}",
            f"Component: {task.component}",
            f"Endpoint: {task.endpoint}",
            f"Exception Message: {task.exception_message}",
            f"Stack Trace:\n{task.stack_trace}\n",
            f"Relevant Logs:\n" + "\n".join(task.relevant_logs),
        ]
        if task.attempt_history:
            prompt_parts.append("\nPREVIOUS FAILED ATTEMPTS (Do NOT repeat the same hypothesis or failed fix):")
            for idx, att in enumerate(task.attempt_history, 1):
                prompt_parts.append(
                    f"Attempt {idx}:\n- Hypothesis: {att.get('hypothesis')}\n- Root cause tried: {att.get('rootCause')}\n- Failure reason / Error: {att.get('failure')}"
                )

        if source_context:
            prompt_parts.append(f"\nSOURCE CODE CONTEXT:\n{source_context}")

        prompt_parts.append("\nReturn your analysis and exact code replacements in the requested JSON structure.")
        return "\n".join(prompt_parts)

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
            "hypothesis": run.hypothesis,
            "rootCause": run.root_cause,
            "remainingRisk": run.remaining_risk,
        }

    def cancel(self, run_id: str) -> None:
        run = self._runs.get(run_id)
        if run:
            run.status = "cancelled"


def _touches_protected(files: list[str]) -> bool:
    protected_prefixes = (".env", ".github/", "apps/extension/manifest.json", "data/career_os.db")
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
