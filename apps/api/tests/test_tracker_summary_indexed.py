"""/tracker/summary and /application-assistant/progress read only submissions (#100).

They used to parse every autopilot job on each request (seconds on a real
database). The indexed reads must give the same answers as the full scan.
"""

from __future__ import annotations

from datetime import UTC, datetime

import pytest
from fastapi.testclient import TestClient

from app.db.store import delete_entity, get_kv, list_entities, session_scope
from app.main import app
from app.services.application_assistant.persistence import save_autopilot_job
from app.services.tracker.outcomes import dashboard_outcomes, summarize_outcomes

_JOBS = [
    ("idx_sub_a", "SUBMITTED"),
    ("idx_sub_b", "SUBMITTED"),
    ("idx_review", "NEEDS_REVIEW"),
    ("idx_staged", "STAGED"),
    ("idx_manual", "MANUAL_REVIEW"),
    ("idx_failed", "FAILED"),
    ("idx_queued", "QUEUED"),
]


@pytest.fixture()
def mixed_jobs():
    with session_scope() as db:
        for job_id, status in _JOBS:
            save_autopilot_job(db, {
                "id": job_id,
                "status": status,
                "title": "Engineer",
                "company": f"Co {job_id}",
                "applicationUrl": f"https://jobs.lever.co/co/{job_id}",
                "submittedAt": "2026-10-29T12:00:00Z" if status == "SUBMITTED" else None,
            })
    yield
    with session_scope() as db:
        for job_id, _ in _JOBS:
            delete_entity(db, "aa_autopilot_job", job_id)


def test_outcomes_match_the_full_scan(mixed_jobs) -> None:
    now = datetime.now(UTC)
    with session_scope() as db:
        full_scan = summarize_outcomes(
            list_entities(db, "aa_autopilot_job"),
            list_entities(db, "application"),
            get_kv(db, "autopilot_submission_receipts") or {},
            now,
        )
        indexed = dashboard_outcomes(db)
    full_scan.pop("events"), indexed.pop("events")
    for result in (full_scan, indexed):
        for row in result["attention"]:
            row.pop("href")
    assert indexed["totalSubmitted"] >= 2
    assert indexed["attention"][0]["count"] >= 3
    assert indexed == full_scan


def test_tracker_summary_counts_submissions(mixed_jobs) -> None:
    with session_scope() as db:
        expected = sum(1 for j in list_entities(db, "aa_autopilot_job") if j.get("status") == "SUBMITTED")
    with TestClient(app) as client:
        body = client.get("/tracker/summary").json()
    assert body["autopilotSubmittedCount"] == expected >= 2
    assert body["outcomes"]["totalSubmitted"] == expected
