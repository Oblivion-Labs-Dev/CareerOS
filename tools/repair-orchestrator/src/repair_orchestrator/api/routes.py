from __future__ import annotations

from pathlib import Path
from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from repair_orchestrator.agents.adapter import AgentWorkspace
from repair_orchestrator.agents.mock_adapter import get_adapter
from repair_orchestrator.config import settings
from repair_orchestrator.db import AgentRunRow, dump_json, load_json, session_scope
from repair_orchestrator.incidents.grouping import get_incident, ingest_error_event, list_incidents
from repair_orchestrator.models import StructuredErrorEvent, TaskStatus, utc_now_iso
from repair_orchestrator.review.reviewer import review_patch
from repair_orchestrator.tasks.lifecycle import create_task_for_incident, get_task, list_tasks, transition_task
from repair_orchestrator.validation.runner import run_validation

router = APIRouter()


class TransitionRequest(BaseModel):
    status: TaskStatus
    details: dict[str, Any] = Field(default_factory=dict)


@router.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok", "service": "repair-orchestrator"}


@router.get("/ready")
def ready() -> dict[str, Any]:
    return {"ready": settings.repair_enabled, "environment": settings.repair_environment}


@router.post("/events")
def receive_event(event: StructuredErrorEvent) -> dict[str, Any]:
    with session_scope() as session:
        result = ingest_error_event(session, event.model_dump())
    return {"success": True, **result}


@router.get("/incidents")
def incidents() -> dict[str, Any]:
    with session_scope() as session:
        items = list_incidents(session)
    return {"incidents": items}


@router.get("/incidents/{fingerprint}")
def incident_detail(fingerprint: str) -> dict[str, Any]:
    with session_scope() as session:
        item = get_incident(session, fingerprint)
    if not item:
        raise HTTPException(status_code=404, detail="Incident not found")
    return item


@router.get("/tasks")
def tasks() -> dict[str, Any]:
    with session_scope() as session:
        items = list_tasks(session)
    return {"tasks": items}


@router.get("/tasks/{task_id}")
def task_detail(task_id: str) -> dict[str, Any]:
    with session_scope() as session:
        item = get_task(session, task_id)
    if not item:
        raise HTTPException(status_code=404, detail="Task not found")
    return item


@router.post("/incidents/{fingerprint}/tasks")
def manual_create_task(fingerprint: str) -> dict[str, Any]:
    with session_scope() as session:
        try:
            task = create_task_for_incident(session, fingerprint)
        except ValueError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
    return {"success": True, "task": task}


@router.post("/tasks/{task_id}/transition")
def task_transition(task_id: str, payload: TransitionRequest) -> dict[str, Any]:
    with session_scope() as session:
        try:
            task = transition_task(session, task_id, payload.status, payload.details)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {"success": True, "task": task}


@router.post("/tasks/{task_id}/approve-agent")
async def approve_agent(task_id: str) -> dict[str, Any]:
    with session_scope() as session:
        task = get_task(session, task_id)
        if not task:
            raise HTTPException(status_code=404, detail="Task not found")
        current = TaskStatus(task["status"])
        if current == TaskStatus.DETECTED:
            transition_task(session, task_id, TaskStatus.READY_FOR_AGENT)
        transition_task(session, task_id, TaskStatus.IMPLEMENTING)
        adapter = get_adapter()
        workspace = AgentWorkspace(
            repo_root=settings.repair_repo_root,
            worktrees_dir=str(Path(settings.repair_repo_root) / ".repair-worktrees"),
        )
        run = await adapter.start(task, workspace)
        session.add(
            AgentRunRow(
                run_id=run.run_id,
                task_id=task_id,
                adapter=settings.agent_adapter,
                status=run.status,
                payload_json=dump_json(await adapter.get_status(run.run_id)),
                created_at=utc_now_iso(),
            )
        )
        transition_task(
            session,
            task_id,
            TaskStatus.VALIDATING,
            {
                "agentBranch": run.branch,
                "agentWorktree": run.worktree_path,
                "patchSummary": run.diff_summary,
                "changedFiles": run.changed_files,
            },
        )
    return {"success": True, "run": await adapter.get_status(run.run_id)}


@router.post("/tasks/{task_id}/validate")
def validate_task(task_id: str) -> dict[str, Any]:
    with session_scope() as session:
        task = get_task(session, task_id)
        if not task:
            raise HTTPException(status_code=404, detail="Task not found")
        validation = run_validation(task.get("validationCommands"))
        validation_dict = validation.model_dump()
        next_status = TaskStatus.REVIEW_REQUIRED if validation.passed else TaskStatus.FAILED
        updated = transition_task(session, task_id, next_status, {"validation": validation_dict})
    return {"success": True, "validation": validation_dict, "task": updated}


@router.post("/tasks/{task_id}/review")
def review_task(task_id: str) -> dict[str, Any]:
    with session_scope() as session:
        task = get_task(session, task_id)
        if not task:
            raise HTTPException(status_code=404, detail="Task not found")
        review = review_patch(task, task.get("validation"))
        review_dict = review.model_dump()
        if review.decision == "approve":
            next_status = TaskStatus.APPROVED
        elif review.decision == "human_review":
            next_status = TaskStatus.READY_FOR_HUMAN
        elif review.decision == "reject":
            next_status = TaskStatus.REJECTED
        else:
            next_status = TaskStatus.REVIEW_REQUIRED
        pr_title = f"fix({task.get('component')}): {task.get('title')}"
        pr_body = _build_pr_body(task, review_dict, task.get("validation"))
        updated = transition_task(
            session,
            task_id,
            next_status,
            {"review": review_dict, "prTitle": pr_title, "prBody": pr_body},
        )
    return {"success": True, "review": review_dict, "task": updated}


@router.post("/tasks/{task_id}/close")
def close_task(task_id: str) -> dict[str, Any]:
    with session_scope() as session:
        updated = transition_task(session, task_id, TaskStatus.CLOSED)
    return {"success": True, "task": updated}


def _build_pr_body(task: dict[str, Any], review: dict[str, Any], validation: dict[str, Any] | None) -> str:
    validation = validation or {}
    lines = [
        "## Summary",
        task.get("patchSummary") or "Automated repair patch.",
        "",
        "## Incident",
        f"- Fingerprint: `{task.get('incidentFingerprint')}`",
        f"- Occurrences: {task.get('occurrenceCount')}",
        f"- Component: {task.get('component')}",
        "",
        "## Root cause",
        task.get("exceptionMessage") or "See incident stack trace.",
        "",
        "## Validation",
        f"- Passed: {validation.get('passed')}",
        "",
        "## Review",
        f"- Decision: {review.get('decision')}",
        f"- Risk: {review.get('riskLevel')}",
        f"- Summary: {review.get('summary')}",
        "",
        "## Rollback",
        "Revert the repair branch/worktree; no automatic deployment in MVP.",
    ]
    return "\n".join(lines)
