"""/autopilot/jobs must answer every sort (#100).

A function-local `from app.db.store import get_kv, session_scope` inside the
resume-sort branch made both names local to the whole handler, so every other
sort crashed with UnboundLocalError at the SUBMITTED-receipt lookup. That
emptied the Queue, Review and Failed tabs. A page holding a SUBMITTED job is
what reaches that lookup.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app.db.store import delete_entity, session_scope
from app.main import app
from app.services.application_assistant.persistence import (
    AUTOPILOT_JOBS_CACHE_KEY,
    AUTOPILOT_STATS_CACHE_KEY,
    save_autopilot_job,
)
from app.services.read_cache import read_cache

_JOB_IDS = ("sortlist_submitted", "sortlist_queued")


@pytest.fixture()
def jobs_with_a_submission():
    with session_scope() as db:
        save_autopilot_job(db, {
            "id": "sortlist_submitted",
            "status": "SUBMITTED",
            "title": "Senior AI Engineer",
            "company": "SortCo",
            "applicationUrl": "https://jobs.lever.co/sortco/sortlist_submitted",
            "submittedAt": "2026-10-30T10:00:00Z",
            "matchScore": 80,
        })
        save_autopilot_job(db, {
            "id": "sortlist_queued",
            "status": "QUEUED",
            "title": "Backend Engineer",
            "company": "SortCo",
            "applicationUrl": "https://jobs.lever.co/sortco/sortlist_queued",
            "matchScore": 60,
        })
    yield
    with session_scope() as db:
        for job_id in _JOB_IDS:
            delete_entity(db, "aa_autopilot_job", job_id)
    # The job list is cached process-wide; leave no copy of these rows behind
    # for the next test module.
    read_cache.invalidate(AUTOPILOT_JOBS_CACHE_KEY)
    read_cache.invalidate(AUTOPILOT_STATS_CACHE_KEY)


@pytest.mark.parametrize(
    "sort_by",
    ["", "submittedAt", "updatedAt", "relevance", "matchScore", "priority", "recent", "taste", "ai_prioritized"],
)
def test_jobs_list_answers_every_sort_with_a_submitted_job(jobs_with_a_submission, sort_by: str) -> None:
    with TestClient(app) as client:
        response = client.get(
            "/application-assistant/autopilot/jobs",
            params={"status": "SUBMITTED,QUEUED", "sortBy": sort_by, "sortDir": "desc", "limit": 100},
        )
    assert response.status_code == 200, response.text
    by_id = {job["id"]: job for job in response.json()["jobs"]}
    assert "sortlist_submitted" in by_id
    assert "submissionConfirmed" in by_id["sortlist_submitted"]
