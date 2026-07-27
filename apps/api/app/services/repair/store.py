from __future__ import annotations

import json
import threading
from pathlib import Path
from typing import Any

from app.services.repair.types import RepairTask

STORE_FILE = Path(__file__).resolve().parents[3] / "data" / "logs" / "repair-tasks.json"
ACTIVE_STATUSES = {"open", "processing", "agent_working", "validating"}


class RepairTaskStore:
    def __init__(self) -> None:
        self._lock = threading.Lock()

    def _read(self) -> dict[str, Any]:
        if not STORE_FILE.is_file():
            return {"tasks": {}, "latestRun": None}
        return json.loads(STORE_FILE.read_text(encoding="utf-8"))

    def _write(self, payload: dict[str, Any]) -> None:
        STORE_FILE.parent.mkdir(parents=True, exist_ok=True)
        STORE_FILE.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")

    def get_task_by_fingerprint(self, fingerprint: str) -> dict[str, Any] | None:
        with self._lock:
            data = self._read()
            for task in data.get("tasks", {}).values():
                if task.get("fingerprint") == fingerprint and task.get("status") in ACTIVE_STATUSES:
                    return task
            return None

    def upsert_task(self, task: RepairTask) -> dict[str, Any]:
        with self._lock:
            data = self._read()
            tasks = data.setdefault("tasks", {})
            record = {
                "taskId": task.task_id,
                "fingerprint": task.fingerprint,
                "title": task.title,
                "status": task.status,
                "severity": task.severity,
                "component": task.component,
                "exceptionMessage": task.exception_message,
                "stackTrace": task.stack_trace,
                "relevantLogs": task.relevant_logs,
                "occurrenceCount": task.occurrence_count,
                "firstOccurrence": task.first_occurrence,
                "lastOccurrence": task.last_occurrence,
                "endpoint": task.endpoint,
                "service": task.service,
                "applicationVersion": task.application_version,
                "gitCommitSha": task.git_commit_sha,
                "suspectedSourceFiles": task.suspected_source_files,
                "reproduction": task.reproduction,
                "validationCommands": task.validation_commands,
                "agentBranch": task.agent_branch,
                "agentWorktree": task.agent_worktree,
                "patchSummary": task.patch_summary,
                "validation": task.validation,
                "agentRun": task.agent_run,
            }
            tasks[task.task_id] = record
            self._write(data)
            return record

    def save_latest_run(self, run: dict[str, Any]) -> None:
        with self._lock:
            data = self._read()
            data["latestRun"] = run
            self._write(data)

    def latest_run(self) -> dict[str, Any] | None:
        with self._lock:
            return self._read().get("latestRun")


repair_task_store = RepairTaskStore()
