"""/autopilot/staged and /autopilot/stats carry only what the dashboard reads (#100).

/staged returned ~12 MB (posting text and archived evidence for ~700 jobs) and
/stats ~1.5 MB (every count map twice, once per tab key and once per raw status).
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


@pytest.fixture()
def staged_job():
    read_cache.invalidate(AUTOPILOT_JOBS_CACHE_KEY)
    read_cache.invalidate(AUTOPILOT_STATS_CACHE_KEY)
    with session_scope() as db:
        save_autopilot_job(db, {
            "id": "lean_staged",
            "status": "NEEDS_REVIEW",
            "title": "Senior AI Engineer",
            "company": "LeanCo",
            "applicationUrl": "https://jobs.lever.co/leanco/lean_staged",
            "description": "x" * 5000,
            "checkpointHistory": [{"step": "fill"}],
            "submissionEvidence": {
                "policyEvaluation": {"blockingIssues": [{"code": "SALARY"}], "warnings": ["w"], "reasons": ["r" * 500]},
                "domSnapshot": "y" * 5000,
            },
            "aiExplanation": "Staged for human review: salary",
            "answers": {"Salary": "160000"},
        })
    yield
    with session_scope() as db:
        delete_entity(db, "aa_autopilot_job", "lean_staged")
    read_cache.invalidate(AUTOPILOT_JOBS_CACHE_KEY)
    read_cache.invalidate(AUTOPILOT_STATS_CACHE_KEY)


def test_staged_rows_keep_what_review_renders_and_drop_the_bulk(staged_job) -> None:
    with TestClient(app) as client:
        body = client.get("/application-assistant/autopilot/staged").json()
    row = next(j for j in body["staged"] if j["id"] == "lean_staged")
    assert body["count"] == len(body["staged"])
    assert row["aiExplanation"] == "Staged for human review: salary"
    assert row["answers"] == {"Salary": "160000"}
    assert row["submissionEvidence"] == {"policyEvaluation": {"blockingIssues": [{"code": "SALARY"}], "warnings": ["w"]}}
    assert "description" not in row and "checkpointHistory" not in row


def test_stats_returns_tab_keys_only(staged_job) -> None:
    with TestClient(app) as client:
        stats = client.get("/application-assistant/autopilot/stats").json()
        listing = client.get(
            "/application-assistant/autopilot/jobs", params={"status": "NEEDS_REVIEW", "limit": 5}
        ).json()
    for key in ("companyCountsByStatus", "titleCountsByStatus"):
        assert stats[key]["review"]
        assert not [k for k in stats[key] if k.isupper()]
    # The jobs list still finds its raw-status counts in the shared cache.
    assert listing["companyCounts"].get("LeanCo") == 1
