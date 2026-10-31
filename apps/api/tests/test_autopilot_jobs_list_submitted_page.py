"""The Autopilot jobs list must load when the page holds a SUBMITTED job.

Regression: a function-local ``from app.db.store import get_kv, session_scope``
inside the resume-match sort branch made both names local to the whole route,
so every request that did not take that branch and returned a SUBMITTED job
raised UnboundLocalError (HTTP 500) — the default Autopilot list included.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app.db.store import session_scope
from app.main import app
from app.services.application_assistant.persistence import (
    AUTOPILOT_JOBS_CACHE_KEY,
    delete_autopilot_job,
    save_autopilot_job,
)
from app.services.read_cache import read_cache

JOB_ID = "apjob_list_submitted_regression"


@pytest.fixture
def submitted_job():
    with session_scope() as db:
        save_autopilot_job(db, {
            "id": JOB_ID,
            "status": "SUBMITTED",
            "company": "Acme",
            "title": "Senior Software Engineer",
            "applicationUrl": "https://boards.greenhouse.io/acme/jobs/1234567",
            "matchScore": 99,
        })
    # The list is served stale-while-revalidate; a list cached by an earlier
    # test would not hold this job on its first read.
    read_cache.invalidate(AUTOPILOT_JOBS_CACHE_KEY)
    yield JOB_ID
    with session_scope() as db:
        delete_autopilot_job(db, JOB_ID)


@pytest.mark.parametrize("sort_by", ["", "matchScore", "company", "updatedAt"])
def test_list_with_a_submitted_job_does_not_500(submitted_job, sort_by):
    client = TestClient(app)
    response = client.get(
        "/application-assistant/autopilot/jobs",
        params={"status": "SUBMITTED", "sortBy": sort_by, "limit": 50},
    )

    assert response.status_code == 200, response.text
    ids = [job["id"] for job in response.json()["jobs"]]
    assert submitted_job in ids
