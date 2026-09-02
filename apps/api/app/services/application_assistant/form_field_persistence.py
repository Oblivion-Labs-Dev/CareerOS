"""Form Field Persistence — saves discovered fields, resolutions, and reports.

Every discovered field is persisted with full question text (no truncation).
Every resolved answer is persisted with provenance and confidence.
Pre-submit reports are persisted for debugging.
"""

from __future__ import annotations

import json
from typing import Any

from app.db.store import new_id, now_iso, session_scope, upsert_entity, list_entities
from app.services.application_assistant.profile_answer_resolver import AnswerResolution
from app.services.application_assistant.cross_field_validator import ValidationReport


ENTITY_FORM_FIELD = "aa_form_field"
ENTITY_ANSWER_RESOLUTION = "aa_answer_resolution"
ENTITY_PRE_SUBMIT_REPORT = "aa_pre_submit_report"


def persist_discovered_field(
    db: Any,
    *,
    application_id: str,
    job_id: str,
    ats: str,
    field_id: str,
    field_name: str,
    full_question_text: str,
    field_type: str,
    required: bool,
    options: list[dict[str, str]] | None = None,
    section: str = "",
    dom_selector: str = "",
    page_url: str = "",
) -> dict[str, Any]:
    """Persist a single discovered form field with complete metadata."""
    entity = {
        "id": f"{application_id}:{field_id}" if field_id else new_id(),
        "type": ENTITY_FORM_FIELD,
        "applicationId": application_id,
        "jobId": job_id,
        "ats": ats,
        "fieldId": field_id,
        "fieldName": field_name,
        "fullQuestionText": full_question_text,  # NEVER truncated
        "displayLabel": field_name[:80] if field_name else "",
        "fieldType": field_type,
        "required": required,
        "options": options or [],
        "section": section,
        "domSelector": dom_selector,
        "discoveredAt": now_iso(),
        "pageUrl": page_url,
    }
    upsert_entity(db, ENTITY_FORM_FIELD, entity)
    return entity


def persist_discovered_form(
    application_id: str,
    job_id: str,
    ats: str,
    fields: list[dict[str, Any]],
    page_url: str = "",
) -> int:
    """Persist all discovered form fields for an application."""
    count = 0
    with session_scope() as db:
        for f in fields:
            field_id = f.get("id") or f.get("fieldId") or f.get("name") or ""
            field_name = f.get("label") or f.get("name") or ""
            full_text = f.get("fullQuestionText") or f.get("label") or field_name
            options = []
            if f.get("options"):
                for opt in f["options"]:
                    if isinstance(opt, dict):
                        options.append(opt)
                    else:
                        options.append({"value": str(opt), "label": str(opt)})

            persist_discovered_field(
                db,
                application_id=application_id,
                job_id=job_id,
                ats=ats,
                field_id=field_id,
                field_name=field_name,
                full_question_text=full_text,
                field_type=f.get("type") or f.get("fieldType") or "text",
                required=bool(f.get("required", False)),
                options=options,
                section=f.get("section") or "",
                dom_selector=f.get("selectorHint") or f.get("domSelector") or "",
                page_url=page_url,
            )
            count += 1
    return count


def persist_answer_resolution(
    application_id: str,
    resolution: AnswerResolution,
) -> dict[str, Any]:
    """Persist a single answer resolution with full provenance."""
    entity = {
        "id": f"{application_id}:{resolution.field_id}" if resolution.field_id else new_id(),
        "type": ENTITY_ANSWER_RESOLUTION,
        "applicationId": application_id,
        **resolution.to_dict(),
    }
    with session_scope() as db:
        upsert_entity(db, ENTITY_ANSWER_RESOLUTION, entity)
    return entity


def persist_answer_resolutions(
    application_id: str,
    resolutions: list[AnswerResolution],
) -> int:
    """Persist all answer resolutions for an application."""
    count = 0
    with session_scope() as db:
        for res in resolutions:
            entity = {
                "id": f"{application_id}:{res.field_id}" if res.field_id else new_id(),
                "type": ENTITY_ANSWER_RESOLUTION,
                "applicationId": application_id,
                **res.to_dict(),
            }
            upsert_entity(db, ENTITY_ANSWER_RESOLUTION, entity)
            count += 1
    return count


def persist_pre_submit_report(
    application_id: str,
    report: ValidationReport,
    resolutions: list[AnswerResolution] | None = None,
) -> dict[str, Any]:
    """Persist the pre-submit validation report alongside field details."""
    entity = {
        "id": f"report:{application_id}",
        "type": ENTITY_PRE_SUBMIT_REPORT,
        "applicationId": application_id,
        **report.to_dict(),
    }
    if resolutions:
        entity["fields"] = [
            {
                "question": r.question,
                "answer": r.answer,
                "source": r.resolution_method,
                "confidence": r.confidence,
                "validation": report.field_statuses.get(r.field_id, "UNVALIDATED"),
            }
            for r in resolutions
        ]
    with session_scope() as db:
        upsert_entity(db, ENTITY_PRE_SUBMIT_REPORT, entity)
    return entity


def get_answer_resolutions(application_id: str) -> list[dict[str, Any]]:
    """Retrieve all answer resolutions for an application."""
    with session_scope() as db:
        all_resolutions = list_entities(db, ENTITY_ANSWER_RESOLUTION)
    return [r for r in all_resolutions if r.get("applicationId") == application_id]


def get_pre_submit_report(application_id: str) -> dict[str, Any] | None:
    """Retrieve the pre-submit report for an application."""
    with session_scope() as db:
        all_reports = list_entities(db, ENTITY_PRE_SUBMIT_REPORT)
    for r in all_reports:
        if r.get("applicationId") == application_id:
            return r
    return None
