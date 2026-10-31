"""/autopilot/jobs/insight-rows: the dashboard's Insights and Search Intelligence
panels count over every job; they paged /autopilot/jobs at limit=1000 and pulled
every full row. This route returns only the counted fields.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app.db.store import delete_entity, session_scope
from app.main import app
from app.services.application_assistant.persistence import AUTOPILOT_JOBS_CACHE_KEY, save_autopilot_job
from app.services.read_cache import read_cache

IDS = ("insight_queued", "insight_review")


@pytest.fixture()
def jobs():
    read_cache.invalidate(AUTOPILOT_JOBS_CACHE_KEY)
    with session_scope() as db:
        save_autopilot_job(db, {
            "id": "insight_queued", "status": "QUEUED", "company": "InsightCo", "title": "Senior AI Engineer",
            "location": "Seattle, WA", "matchScore": 86, "queuedAt": "2026-10-01T00:00:00Z",
            "resumeFileUsed": "C:/resumes/ai.pdf", "description": "x" * 5000,
        })
        save_autopilot_job(db, {
            "id": "insight_review", "status": "NEEDS_REVIEW", "company": "InsightCo", "title": "Staff Engineer",
            "pendingQuestions": [{"label": "Salary"}, {"label": "Visa"}], "description": "y" * 5000,
        })
    yield
    with session_scope() as db:
        for job_id in IDS:
            delete_entity(db, "aa_autopilot_job", job_id)
    read_cache.invalidate(AUTOPILOT_JOBS_CACHE_KEY)


def _rows(client, **params):
    body = client.get("/application-assistant/autopilot/jobs/insight-rows", params=params).json()
    assert body["success"] is True and body["total"] == len(body["jobs"])
    return {row["id"]: row for row in body["jobs"] if row["id"] in IDS}


def test_rows_carry_only_counted_fields(jobs) -> None:
    with TestClient(app) as client:
        rows = _rows(client)
    assert rows["insight_queued"] == {
        "id": "insight_queued", "status": "QUEUED", "company": "InsightCo", "title": "Senior AI Engineer",
        "location": "Seattle, WA", "matchScore": 86, "ineligibilityReason": None,
        "queuedAt": "2026-10-01T00:00:00Z", "pendingQuestionCount": 0, "hasResumeFile": True,
    }
    assert rows["insight_review"]["pendingQuestionCount"] == 2
    assert rows["insight_review"]["hasResumeFile"] is False


def test_status_filter(jobs) -> None:
    with TestClient(app) as client:
        assert set(_rows(client, status="queued,APPLYING")) == {"insight_queued"}
