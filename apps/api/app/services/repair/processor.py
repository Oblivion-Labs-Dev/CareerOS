from __future__ import annotations

import subprocess
import threading
import uuid
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from app.config import settings
from app.services.repair.agent import get_agent_adapter
from app.services.repair.fingerprint import compute_fingerprint
from app.services.repair.log_source import log_inventory, log_source
from app.services.repair.sanitize import sanitize_log_entry
from app.services.repair.store import repair_task_store
from app.services.repair.types import AgentWorkspace, ReadLogOptions, RepairTask
from app.services.structured_errors import get_git_commit_sha

_run_lock = threading.Lock()
_active_run = False

REPO_ROOT = Path(__file__).resolve().parents[4]
DEFAULT_VALIDATION_COMMANDS = [
    "python -m pytest tests/test_health.py tests/test_repair_pipeline.py -q",
]


def _suspected_source_files(entry: dict[str, Any]) -> list[str]:
    hints: list[str] = []
    endpoint = str(entry.get("endpoint") or entry.get("signature") or "")
    if "scrape" in endpoint.lower() or "scraper" in str(entry.get("message", "")).lower():
        hints.extend(["apps/api/app/routers/repair_demo.py", "apps/api/app/services/job_discover/"])
    if endpoint.startswith(("GET ", "POST ", "PUT ", "PATCH ", "DELETE ")):
        hints.append("apps/api/app/routers/api.py")
    stack = str(entry.get("stack_trace") or "")
    for line in stack.splitlines():
        if "apps/api" in line:
            hints.append(line.strip())
            break
    return list(dict.fromkeys(hints))


NOISE_ERROR_SIGNATURES = frozenset(
    {
        "GET /favicon.ico",
        "GET /robots.txt",
    }
)

NOISE_SIGNATURE_PREFIXES = (
    "POST /dev/repair/",
    "GET /dev/demo/",
    "POST /dev/demo/",
)


def _is_actionable_error(entry: dict[str, Any]) -> bool:
    signature = str(entry.get("signature") or "")
    endpoint = str(entry.get("endpoint") or "")
    if signature in NOISE_ERROR_SIGNATURES or endpoint in NOISE_ERROR_SIGNATURES:
        return False
    if "favicon.ico" in signature or "favicon.ico" in endpoint:
        return False
    if any(signature.startswith(prefix) or endpoint.startswith(prefix) for prefix in NOISE_SIGNATURE_PREFIXES):
        return False
    return True


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def process_logs_and_errors() -> dict[str, Any]:
    global _active_run
    if not settings.career_os_dev_mode:
        raise PermissionError("Manual repair processing is only available in development mode")

    with _run_lock:
        if _active_run:
            raise RuntimeError("A repair run is already in progress")
        _active_run = True

    run_report: dict[str, Any] = {
        "state": "reading_logs",
        "startedAt": utc_now_iso(),
        "logEntriesScanned": 0,
        "errorsDiscovered": 0,
        "duplicateGroups": 0,
        "skipped": [],
        "task": None,
        "agentRun": None,
        "validation": None,
        "failure": None,
    }

    try:
        entries = log_source.read_recent_logs(ReadLogOptions(limit=500))
        inventory = log_inventory()
        run_report["logEntriesScanned"] = len(entries)
        run_report["logInventory"] = inventory
        run_report["oldestEntry"] = entries[0].timestamp if entries else None
        run_report["newestEntry"] = entries[-1].timestamp if entries else None
        run_report["state"] = "creating_task"

        sanitized_entries: list[dict[str, Any]] = []
        for entry in entries:
            raw = {
                "id": entry.id,
                "level": entry.level,
                "source": entry.source,
                "message": entry.message,
                "timestamp": entry.timestamp,
                "signature": entry.signature,
                "endpoint": entry.endpoint,
                "stack_trace": entry.stack_trace,
                "status_code": entry.status_code,
                "metadata": entry.metadata,
            }
            sanitized_entries.append(sanitize_log_entry(raw))

        actionable = [item for item in sanitized_entries if item.get("level") in {"error", "critical"}]
        actionable = [item for item in actionable if _is_actionable_error(item)]
        run_report["errorsDiscovered"] = len(actionable)
        if not actionable:
            run_report["state"] = "completed"
            run_report["completedAt"] = utc_now_iso()
            run_report["skipped"].append({"reason": "no_actionable_errors"})
            run_report["message"] = (
                "No actionable backend errors were found. "
                "Click “Trigger demo backend error” on this page, then run again."
            )
            repair_task_store.save_latest_run(run_report)
            return run_report

        groups: dict[str, list[dict[str, Any]]] = defaultdict(list)
        for item in actionable:
            fingerprint = compute_fingerprint(
                error_type=str(item.get("metadata", {}).get("errorType") or item.get("signature") or "BackendError"),
                service="career-os-api",
                signature=str(item.get("signature") or ""),
                endpoint=str(item.get("endpoint") or ""),
                stack_trace=str(item.get("stack_trace") or ""),
            )
            groups[fingerprint].append(item)

        run_report["duplicateGroups"] = len(groups)

        selected_fingerprint = max(
            groups.keys(),
            key=lambda fp: (len(groups[fp]), groups[fp][-1].get("timestamp") or ""),
        )
        grouped = groups[selected_fingerprint]
        primary = grouped[-1]

        existing = repair_task_store.get_task_by_fingerprint(selected_fingerprint)
        if existing and existing.get("status") in {"processing", "agent_working", "validating"}:
            run_report["state"] = "failed"
            run_report["failure"] = "Duplicate active repair task already exists for this unresolved error"
            run_report["skipped"].append(
                {"fingerprint": selected_fingerprint, "reason": "duplicate_active_task", "taskId": existing.get("taskId")}
            )
            repair_task_store.save_latest_run(run_report)
            return run_report

        task_id = existing.get("taskId") if existing else str(uuid.uuid4())
        relevant_logs = [
            f"[{item.get('level')}] {item.get('source')}: {item.get('message')} ({item.get('timestamp')})"
            for item in grouped[-6:]
        ]

        task = RepairTask(
            task_id=task_id,
            fingerprint=selected_fingerprint,
            title=f"Backend error: {primary.get('signature') or primary.get('endpoint') or 'unknown'}",
            status="processing",
            severity="error",
            component=str(primary.get("source") or "api-backend"),
            exception_message=str(primary.get("message") or ""),
            stack_trace=str(primary.get("stack_trace") or ""),
            relevant_logs=relevant_logs,
            occurrence_count=len(grouped),
            first_occurrence=str(grouped[0].get("timestamp") or utc_now_iso()),
            last_occurrence=str(primary.get("timestamp") or utc_now_iso()),
            endpoint=str(primary.get("endpoint") or primary.get("signature") or ""),
            git_commit_sha=get_git_commit_sha(),
            suspected_source_files=_suspected_source_files(primary),
            reproduction=f"Replay endpoint {primary.get('endpoint') or primary.get('signature') or 'n/a'}",
            validation_commands=DEFAULT_VALIDATION_COMMANDS,
        )

        for fp, items in groups.items():
            if fp != selected_fingerprint:
                run_report["skipped"].append(
                    {"fingerprint": fp, "reason": "lower_priority_group", "occurrences": len(items)}
                )

        run_report["task"] = repair_task_store.upsert_task(task)
        run_report["state"] = "sending_to_agent"

        adapter = get_agent_adapter()
        workspace = AgentWorkspace(
            repo_root=str(REPO_ROOT),
            worktrees_dir=str(REPO_ROOT / ".repair-worktrees"),
        )

        run_report["state"] = "agent_working"
        agent_run = adapter.start(task, workspace)
        task.agent_branch = agent_run.branch
        task.agent_worktree = agent_run.worktree_path
        task.patch_summary = agent_run.diff_summary
        task.agent_run = adapter.get_status(agent_run.run_id)
        task.status = "validating" if agent_run.status == "completed" else "failed"
        repair_task_store.upsert_task(task)
        run_report["agentRun"] = task.agent_run

        if agent_run.status != "completed":
            run_report["state"] = "failed"
            run_report["failure"] = agent_run.output or "Agent run failed"
            repair_task_store.save_latest_run(run_report)
            return run_report

        run_report["state"] = "validating"
        validation = _run_validation(task.validation_commands)
        task.validation = validation
        task.status = "completed" if validation.get("passed") else "failed"
        repair_task_store.upsert_task(task)
        run_report["validation"] = validation
        run_report["task"] = repair_task_store.upsert_task(task)

        run_report["state"] = "completed" if validation.get("passed") else "failed"
        if not validation.get("passed"):
            run_report["failure"] = "Validation failed"
        run_report["completedAt"] = utc_now_iso()
        repair_task_store.save_latest_run(run_report)
        return run_report
    except Exception as exc:
        run_report["state"] = "failed"
        run_report["failure"] = str(exc)
        run_report["completedAt"] = utc_now_iso()
        repair_task_store.save_latest_run(run_report)
        return run_report
    finally:
        with _run_lock:
            _active_run = False


def latest_manual_run() -> dict[str, Any] | None:
    return repair_task_store.latest_run()


def _run_validation(commands: list[str]) -> dict[str, Any]:
    results: list[dict[str, Any]] = []
    all_passed = True
    api_root = Path(__file__).resolve().parents[2]
    for command in commands:
        completed = subprocess.run(
            command,
            shell=True,
            cwd=str(api_root),
            capture_output=True,
            text=True,
            timeout=180,
        )
        passed = completed.returncode == 0
        all_passed = all_passed and passed
        results.append(
            {
                "command": command,
                "passed": passed,
                "exitCode": completed.returncode,
                "stdout": completed.stdout[-3000:],
                "stderr": completed.stderr[-3000:],
            }
        )
    return {"passed": all_passed, "commands": results, "completedAt": utc_now_iso()}
