"""Pipeline/Kanban aggregation, Ghosted-status derivation, and CSV import/export for the
job-search funnel (Applied -> Ghosted -> Interviewing -> Rejected -> Offer).

Reads the same `application` entities already used by the tracker summary and the "All
Applications" view — no new storage model, just a different projection of the same data.
"""

from __future__ import annotations

import csv
import io
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy.orm import Session

from app.db.store import list_entities, upsert_entity

GHOST_THRESHOLD_DAYS = 21

APPLIED_STATUSES = {"applied", "submitted"}
INTERVIEW_STATUSES = {"interviewing", "interview"}
REJECTED_STATUSES = {"rejected", "declined"}
OFFER_STATUSES = {"offer", "offered"}
EXCLUDED_STATUSES = {"saved", "draft", "autofilled", "applying"}  # not yet applied — not part of the post-apply funnel

PIPELINE_COLUMNS = [
    {"key": "applied", "label": "Applied"},
    {"key": "ghosted", "label": "Ghosted"},
    {"key": "interviewing", "label": "Interviewing"},
    {"key": "rejected", "label": "Rejected"},
    {"key": "offer", "label": "Offer"},
]


def _parse_dt(value: str | None) -> datetime | None:
    if not value or not isinstance(value, str):
        return None
    try:
        cleaned = value.replace("Z", "+00:00")
        dt = datetime.fromisoformat(cleaned)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=UTC)
        return dt
    except ValueError:
        return None


def last_activity(app: dict[str, Any]) -> datetime | None:
    """Best available signal for 'last activity' — falls back through submittedAt/updatedAt/
    createdAt since inbound replies aren't yet linked back onto the application record."""
    for key in ("lastActivityAt", "submittedAt", "updatedAt", "createdAt"):
        dt = _parse_dt(app.get(key))
        if dt:
            return dt
    return None


def pipeline_column(app: dict[str, Any]) -> str | None:
    """Which Kanban column an application belongs to, or None if it's out of scope
    (e.g. still just 'saved', never actually applied)."""
    status = str(app.get("status") or "").strip().lower()
    if status in EXCLUDED_STATUSES:
        return None
    if status in OFFER_STATUSES:
        return "offer"
    if status in REJECTED_STATUSES:
        return "rejected"
    if status in INTERVIEW_STATUSES:
        return "interviewing"
    if status in APPLIED_STATUSES:
        activity = last_activity(app)
        if activity and (datetime.now(UTC) - activity) > timedelta(days=GHOST_THRESHOLD_DAYS):
            return "ghosted"
        return "applied"
    return None


def build_pipeline(db: Session) -> dict[str, Any]:
    applications = list_entities(db, "application")
    buckets: dict[str, list[dict[str, Any]]] = {c["key"]: [] for c in PIPELINE_COLUMNS}
    for app in applications:
        column = pipeline_column(app)
        if not column:
            continue
        activity = last_activity(app)
        days_in_stage = (datetime.now(UTC) - activity).days if activity else None
        buckets[column].append(
            {
                "id": app.get("id"),
                "companyName": app.get("companyName") or "Unknown",
                "roleTitle": app.get("roleTitle") or "Unknown role",
                "status": app.get("status"),
                "daysInStage": max(0, (datetime.now(UTC) - entered).days) if (entered := _parse_dt(app.get("stageEnteredAt"))) else None,
                "daysSinceActivity": max(0, days_in_stage) if days_in_stage is not None else None,
                "followUpOverdue": bool((due := _parse_dt(app.get("followUpAt"))) and due < datetime.now(UTC) and column in {"applied", "ghosted", "interviewing"}),
                "url": app.get("url"),
                "updatedAt": app.get("updatedAt"),
            }
        )
    for items in buckets.values():
        items.sort(key=lambda item: item.get("updatedAt") or "", reverse=True)
    funnel = [{"key": c["key"], "label": c["label"], "count": len(buckets[c["key"]])} for c in PIPELINE_COLUMNS]
    return {
        "columns": [{"key": c["key"], "label": c["label"], "items": buckets[c["key"]]} for c in PIPELINE_COLUMNS],
        "funnel": funnel,
        "total": sum(len(v) for v in buckets.values()),
        "ghostThresholdDays": GHOST_THRESHOLD_DAYS,
    }


CSV_FIELDS = ["companyName", "roleTitle", "status", "submittedAt", "lastActivity", "url", "location"]


def export_applications_csv(db: Session) -> str:
    applications = list_entities(db, "application")
    buffer = io.StringIO()
    writer = csv.DictWriter(buffer, fieldnames=CSV_FIELDS)
    writer.writeheader()
    for app in applications:
        activity = last_activity(app)
        writer.writerow(
            {
                "companyName": app.get("companyName") or "",
                "roleTitle": app.get("roleTitle") or "",
                "status": app.get("status") or "",
                "submittedAt": app.get("submittedAt") or "",
                "lastActivity": activity.isoformat() if activity else "",
                "url": app.get("url") or "",
                "location": app.get("location") or "",
            }
        )
    return buffer.getvalue()


COLUMN_ALIASES = {
    "company": "companyName",
    "companyname": "companyName",
    "company name": "companyName",
    "role": "roleTitle",
    "roletitle": "roleTitle",
    "title": "roleTitle",
    "role title": "roleTitle",
    "job title": "roleTitle",
    "status": "status",
    "appliedat": "submittedAt",
    "applied at": "submittedAt",
    "submittedat": "submittedAt",
    "date applied": "submittedAt",
    "url": "url",
    "link": "url",
    "job url": "url",
    "location": "location",
}


def import_applications_csv(db: Session, content: str) -> dict[str, Any]:
    reader = csv.DictReader(io.StringIO(content))
    created = 0
    updated = 0
    skipped = 0
    existing = list_entities(db, "application")
    existing_by_key = {
        (str(a.get("companyName") or "").strip().lower(), str(a.get("roleTitle") or "").strip().lower()): a
        for a in existing
    }
    for raw_row in reader:
        row: dict[str, str] = {}
        for key, value in raw_row.items():
            if key is None:
                continue
            normalized_key = COLUMN_ALIASES.get(key.strip().lower())
            if normalized_key:
                row[normalized_key] = (value or "").strip()
        company = row.get("companyName", "").strip()
        role = row.get("roleTitle", "").strip()
        if not company and not role:
            skipped += 1
            continue
        existing_app = existing_by_key.get((company.lower(), role.lower()))
        payload: dict[str, Any] = {
            "companyName": company or "Unknown",
            "roleTitle": role or "Unknown role",
            "status": row.get("status") or (existing_app or {}).get("status") or "applied",
            "url": row.get("url") or (existing_app or {}).get("url") or "",
            "location": row.get("location") or (existing_app or {}).get("location") or "",
            "submittedAt": row.get("submittedAt") or (existing_app or {}).get("submittedAt"),
        }
        if existing_app:
            payload["id"] = existing_app["id"]
            updated += 1
        else:
            created += 1
        upsert_entity(db, "application", payload)
    return {"created": created, "updated": updated, "skipped": skipped}
