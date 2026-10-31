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


def test_staged_count_only_call_skips_rows_but_keeps_total(staged_job) -> None:
    # The sidebar badge polled the full ~4 MB review list every 30 s just to
    # read its length; limit=0 answers with the count alone.
    with TestClient(app) as client:
        full = client.get("/application-assistant/autopilot/staged").json()
        counted = client.get("/application-assistant/autopilot/staged", params={"limit": 0}).json()
        one = client.get("/application-assistant/autopilot/staged", params={"limit": 1}).json()
    assert counted == {"staged": [], "count": full["count"]}
    assert full["count"] >= 1
    assert len(one["staged"]) == 1 and one["count"] == full["count"]


def test_stats_without_facets_keeps_counts_and_drops_filter_maps(staged_job) -> None:
    # The overview only reads statusCounts and submitted totals; the ~1 MB of
    # company/title facets are for the filter dropdowns.
    with TestClient(app) as client:
        full = client.get("/application-assistant/autopilot/stats").json()
        lean = client.get("/application-assistant/autopilot/stats", params={"facets": "false"}).json()
    assert "companyCountsByStatus" not in lean and "titleCountsByStatus" not in lean
    assert lean["statusCounts"] == full["statusCounts"]
    assert lean["submittedToday"] == full["submittedToday"]


def test_jobs_page_drops_posting_text_and_facets_on_request(staged_job) -> None:
    # A 20-row page was ~600 KB: the posting text on every row plus ~500 KB of
    # title/company facets resent on every scroll page.
    params = {"status": "NEEDS_REVIEW", "limit": 20}
    with TestClient(app) as client:
        first = client.get("/application-assistant/autopilot/jobs", params=params).json()
        more = client.get("/application-assistant/autopilot/jobs", params={**params, "facets": "false"}).json()
    row = next(j for j in first["jobs"] if j["id"] == "lean_staged")
    assert "description" not in row
    assert first["companyCounts"].get("LeanCo") == 1 and first["titleCounts"]
    assert more["companyCounts"] == {} and more["titleCounts"] == {}
    assert [j["id"] for j in more["jobs"]] == [j["id"] for j in first["jobs"]]
    assert more["total"] == first["total"] and more["statusCounts"] == first["statusCounts"]
