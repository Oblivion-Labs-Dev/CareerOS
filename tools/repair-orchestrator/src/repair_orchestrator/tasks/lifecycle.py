from __future__ import annotations

from typing import Any

from sqlalchemy.orm import Session

from repair_orchestrator.config import settings
from repair_orchestrator.db import AuditRow, RepairTaskRow, dump_json, load_json
from repair_orchestrator.models import RepairTaskView, TaskStatus, utc_now_iso


ALLOWED_TRANSITIONS: dict[TaskStatus, set[TaskStatus]] = {
    TaskStatus.DETECTED: {TaskStatus.TRIAGED, TaskStatus.READY_FOR_AGENT, TaskStatus.CLOSED, TaskStatus.FAILED},
    TaskStatus.TRIAGED: {TaskStatus.READY_FOR_AGENT, TaskStatus.CLOSED, TaskStatus.FAILED},
    TaskStatus.READY_FOR_AGENT: {TaskStatus.IMPLEMENTING, TaskStatus.CLOSED, TaskStatus.FAILED},
    TaskStatus.IMPLEMENTING: {TaskStatus.VALIDATING, TaskStatus.FAILED, TaskStatus.REJECTED},
    TaskStatus.VALIDATING: {TaskStatus.REVIEW_REQUIRED, TaskStatus.FAILED, TaskStatus.REJECTED},
    TaskStatus.REVIEW_REQUIRED: {
        TaskStatus.APPROVED,
        TaskStatus.REJECTED,
        TaskStatus.READY_FOR_HUMAN,
        TaskStatus.FAILED,
    },
    TaskStatus.APPROVED: {TaskStatus.READY_FOR_HUMAN, TaskStatus.CLOSED},
    TaskStatus.REJECTED: {TaskStatus.READY_FOR_AGENT, TaskStatus.CLOSED, TaskStatus.FAILED},
    TaskStatus.READY_FOR_HUMAN: {TaskStatus.CLOSED, TaskStatus.REJECTED},
    TaskStatus.CLOSED: set(),
    TaskStatus.FAILED: {TaskStatus.REJECTED, TaskStatus.READY_FOR_AGENT, TaskStatus.CLOSED, TaskStatus.REVIEW_REQUIRED},
}


def _audit(session: Session, task_id: str, action: str, details: dict[str, Any]) -> None:
    session.add(
        AuditRow(
            entity_type="task",
            entity_id=task_id,
            action=action,
            details_json=dump_json(details),
        )
    )


def task_to_view(row: RepairTaskRow) -> RepairTaskView:
    payload = load_json(row.payload_json, {})
    audit_rows = (
        row.__dict__.get("_audit_history")
        if isinstance(row.__dict__.get("_audit_history"), list)
        else payload.get("auditHistory", [])
    )
    return RepairTaskView(
        taskId=row.task_id,
        incidentFingerprint=row.incident_fingerprint,
        title=row.title,
        status=TaskStatus(row.status),
        severity=row.severity,  # type: ignore[arg-type]
        component=row.component,
        exceptionMessage=payload.get("exceptionMessage", ""),
        stackTrace=payload.get("stackTrace", ""),
        relevantLogs=payload.get("relevantLogs", []),
        occurrenceCount=payload.get("occurrenceCount", 0),
        firstOccurrence=payload.get("firstOccurrence", ""),
        lastOccurrence=payload.get("lastOccurrence", ""),
        gitCommitSha=payload.get("gitCommitSha", ""),
        applicationVersion=payload.get("applicationVersion", ""),
        suspectedSourceFiles=payload.get("suspectedSourceFiles", []),
        reproduction=payload.get("reproduction", ""),
        validationCommands=payload.get("validationCommands", []),
        agentBranch=payload.get("agentBranch", ""),
        agentWorktree=payload.get("agentWorktree", ""),
        patchSummary=payload.get("patchSummary", ""),
        validation=payload.get("validation"),
        review=payload.get("review"),
        prTitle=payload.get("prTitle", ""),
        prBody=payload.get("prBody", ""),
        auditHistory=audit_rows,
    )


def list_tasks(session: Session) -> list[dict[str, Any]]:
    rows = session.query(RepairTaskRow).order_by(RepairTaskRow.updated_at.desc()).all()
    return [task_to_view(row).model_dump() for row in rows]


def get_task(session: Session, task_id: str) -> dict[str, Any] | None:
    row = session.get(RepairTaskRow, task_id)
    if not row:
        return None
    audit = (
        session.query(AuditRow)
        .filter(AuditRow.entity_type == "task", AuditRow.entity_id == task_id)
        .order_by(AuditRow.id.asc())
        .all()
    )
    payload = load_json(row.payload_json, {})
    payload["auditHistory"] = [
        {"action": item.action, "details": load_json(item.details_json, {}), "at": str(item.created_at)}
        for item in audit
    ]
    row.payload_json = dump_json(payload)
    return task_to_view(row).model_dump()


def transition_task(session: Session, task_id: str, new_status: TaskStatus, details: dict[str, Any] | None = None) -> dict[str, Any]:
    row = session.get(RepairTaskRow, task_id)
    if not row:
        raise ValueError(f"Task {task_id} not found")
    current = TaskStatus(row.status)
    if new_status not in ALLOWED_TRANSITIONS.get(current, set()):
        raise ValueError(f"Invalid transition {current.value} -> {new_status.value}")
    row.status = new_status.value
    row.updated_at = utc_now_iso()
    if details:
        payload = load_json(row.payload_json, {})
        payload.update(details)
        row.payload_json = dump_json(payload)
    _audit(session, task_id, f"status_{new_status.value}", details or {})
    session.flush()
    return get_task(session, task_id) or {}


def create_task_for_incident(session: Session, fingerprint: str) -> dict[str, Any]:
    from repair_orchestrator.db import IncidentRow
    from repair_orchestrator.incidents.grouping import active_task_exists, create_repair_task_for_incident

    incident = session.get(IncidentRow, fingerprint)
    if not incident:
        raise ValueError(f"Incident {fingerprint} not found")
    if active_task_exists(session, fingerprint):
        raise ValueError("Active repair task already exists for incident")
    task = create_repair_task_for_incident(session, incident)
    session.flush()
    return get_task(session, task.task_id) or {}
