from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any

from sqlalchemy.orm import Session

from repair_orchestrator.config import settings
from repair_orchestrator.db import (
    AuditRow,
    ErrorEventRow,
    IncidentRow,
    RepairTaskRow,
    dump_json,
    load_json,
)
from repair_orchestrator.incidents.fingerprint import compute_fingerprint
from repair_orchestrator.models import StructuredErrorEvent, TaskStatus, utc_now_iso
from repair_orchestrator.security.sanitization import sanitize_error_event


SEVERITY_RANK = {"debug": 0, "info": 1, "warning": 2, "error": 3, "critical": 4}


def _audit(session: Session, entity_type: str, entity_id: str, action: str, details: dict[str, Any]) -> None:
    session.add(
        AuditRow(
            entity_type=entity_type,
            entity_id=entity_id,
            action=action,
            details_json=dump_json(details),
        )
    )


def ingest_error_event(session: Session, raw_event: dict[str, Any]) -> dict[str, Any]:
    sanitized = sanitize_error_event(raw_event)
    event = StructuredErrorEvent.model_validate(sanitized)
    fingerprint = compute_fingerprint(sanitized)
    now = utc_now_iso()

    session.add(
        ErrorEventRow(
            id=str(uuid.uuid4()),
            fingerprint=fingerprint,
            payload_json=dump_json(event.model_dump()),
            received_at=now,
        )
    )

    incident = session.get(IncidentRow, fingerprint)
    if incident:
        incident.occurrence_count += 1
        incident.last_seen = now
        incident.latest_message = event.message
        incident.latest_stack = event.stackTrace
        metadata = load_json(incident.metadata_json, {})
        metadata["lastCorrelationId"] = event.correlationId
        incident.metadata_json = dump_json(metadata)
        if SEVERITY_RANK.get(event.severity, 0) > SEVERITY_RANK.get(incident.severity, 0):
            incident.severity = event.severity
    else:
        incident = IncidentRow(
            fingerprint=fingerprint,
            title=f"{event.errorType} in {event.service}",
            severity=event.severity,
            component=event.feature or event.service,
            occurrence_count=1,
            first_seen=now,
            last_seen=now,
            status="open",
            latest_message=event.message,
            latest_stack=event.stackTrace,
            metadata_json=dump_json({"feature": event.feature, "endpoint": event.endpoint}),
        )
        session.add(incident)

    _audit(
        session,
        "incident",
        fingerprint,
        "error_ingested",
        {"severity": event.severity, "occurrenceCount": incident.occurrence_count},
    )

    task_created = False
    task_id: str | None = None
    if _should_create_task(session, incident, event):
        task = _create_repair_task(session, incident, event)
        task_created = True
        task_id = task.task_id

    session.flush()
    return {
        "fingerprint": fingerprint,
        "occurrenceCount": incident.occurrence_count,
        "taskCreated": task_created,
        "taskId": task_id,
        "incidentStatus": incident.status,
    }


def active_task_exists(session: Session, fingerprint: str) -> bool:
    active_statuses = {
        TaskStatus.DETECTED.value,
        TaskStatus.TRIAGED.value,
        TaskStatus.READY_FOR_AGENT.value,
        TaskStatus.IMPLEMENTING.value,
        TaskStatus.VALIDATING.value,
        TaskStatus.REVIEW_REQUIRED.value,
        TaskStatus.APPROVED.value,
        TaskStatus.READY_FOR_HUMAN.value,
    }
    rows = (
        session.query(RepairTaskRow)
        .filter(RepairTaskRow.incident_fingerprint == fingerprint)
        .all()
    )
    return any(row.status in active_statuses for row in rows)


def _should_create_task(session: Session, incident: IncidentRow, event: StructuredErrorEvent) -> bool:
    if active_task_exists(session, incident.fingerprint):
        return False
    if incident.occurrence_count < settings.min_occurrences_for_task:
        return False
    if SEVERITY_RANK.get(event.severity, 0) < SEVERITY_RANK.get(settings.severity_threshold, 3):
        return False
    metadata = load_json(incident.metadata_json, {})
    last_task_at = metadata.get("lastTaskCreatedAt")
    if last_task_at:
        try:
            last_dt = datetime.fromisoformat(last_task_at)
            now_dt = datetime.now(timezone.utc)
            if (now_dt - last_dt).total_seconds() < settings.incident_cooldown_seconds:
                return False
        except ValueError:
            pass
    return True


def create_repair_task_for_incident(session: Session, incident: IncidentRow) -> RepairTaskRow:
    metadata = load_json(incident.metadata_json, {})
    event = StructuredErrorEvent(
        errorType=incident.title.split(" in ")[0] if " in " in incident.title else "UnknownError",
        message=incident.latest_message,
        stackTrace=incident.latest_stack,
        service="career-os-api",
        feature=incident.component,
        endpoint=str(metadata.get("endpoint") or ""),
        environment=settings.repair_environment,
    )
    return _create_repair_task(session, incident, event)


def _create_repair_task(session: Session, incident: IncidentRow, event: StructuredErrorEvent) -> RepairTaskRow:
    task_id = str(uuid.uuid4())
    now = utc_now_iso()
    validation_commands = [
        item.strip()
        for item in settings.validation_commands.split(",")
        if item.strip()
    ]
    payload = {
        "exceptionMessage": event.message,
        "stackTrace": event.stackTrace,
        "relevantLogs": [],
        "occurrenceCount": incident.occurrence_count,
        "firstOccurrence": incident.first_seen,
        "lastOccurrence": incident.last_seen,
        "gitCommitSha": event.gitCommitSha,
        "applicationVersion": event.applicationVersion,
        "suspectedSourceFiles": _suspect_source_files(event),
        "reproduction": f"Trigger endpoint {event.endpoint} or replay correlation {event.correlationId}",
        "validationCommands": validation_commands,
        "agentBranch": "",
        "agentWorktree": "",
        "patchSummary": "",
        "validation": None,
        "review": None,
        "prTitle": "",
        "prBody": "",
        "auditHistory": [],
    }
    task = RepairTaskRow(
        task_id=task_id,
        incident_fingerprint=incident.fingerprint,
        title=incident.title,
        status=TaskStatus.DETECTED.value,
        severity=incident.severity,
        component=incident.component,
        payload_json=dump_json(payload),
        created_at=now,
        updated_at=now,
    )
    session.add(task)
    incident.status = "task_created"
    metadata = load_json(incident.metadata_json, {})
    metadata["lastTaskCreatedAt"] = now
    incident.metadata_json = dump_json(metadata)
    _audit(session, "task", task_id, "task_created", {"fingerprint": incident.fingerprint})
    return task


def _suspect_source_files(event: StructuredErrorEvent) -> list[str]:
    hints: list[str] = []
    if event.sourceLocation:
        hints.append(event.sourceLocation)
    if event.feature == "scraper" or "scrape" in event.endpoint.lower():
        hints.extend(["apps/api/app/services/job_discover/", "apps/api/app/routers/api.py"])
    if event.service == "career-os-api":
        hints.append("apps/api/app/routers/api.py")
    return list(dict.fromkeys(hints))


def list_incidents(session: Session) -> list[dict[str, Any]]:
    rows = session.query(IncidentRow).order_by(IncidentRow.last_seen.desc()).all()
    return [_incident_to_dict(row) for row in rows]


def get_incident(session: Session, fingerprint: str) -> dict[str, Any] | None:
    row = session.get(IncidentRow, fingerprint)
    if not row:
        return None
    return _incident_to_dict(row)


def _incident_to_dict(row: IncidentRow) -> dict[str, Any]:
    return {
        "fingerprint": row.fingerprint,
        "title": row.title,
        "severity": row.severity,
        "component": row.component,
        "occurrenceCount": row.occurrence_count,
        "firstSeen": row.first_seen,
        "lastSeen": row.last_seen,
        "status": row.status,
        "latestMessage": row.latest_message,
        "metadata": load_json(row.metadata_json, {}),
    }
