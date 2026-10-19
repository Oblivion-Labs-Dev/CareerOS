"""Review-queue relevance sorting (#98 follow-up).

Review and manual-review buckets must surface the jobs closest to the
candidate's target Senior AI Engineer / Lead AI Engineer / AI PM family first.
Deterministic title-token scoring — no LLM, no network.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app.db.store import session_scope, upsert_entity
from app.main import app
from app.services.application_assistant.job_filter_ranker import (
    compute_target_role_relevance,
)


# ---------------------------------------------------------------------------
# Unit: deterministic relevance scoring
# ---------------------------------------------------------------------------


def _score(title: str) -> float:
    return compute_target_role_relevance({"title": title})


def test_relevance_orders_target_roles_first() -> None:
    lead_ai = _score("Lead AI Engineer")
    senior_ai = _score("Senior AI Engineer")
    staff_ml = _score("Staff Machine Learning Engineer")
    senior_backend = _score("Senior Backend Engineer")
    qa_analyst = _score("QA Analyst")
    assert lead_ai > senior_ai > staff_ml > senior_backend > qa_analyst >= 0


def test_relevance_seniority_markers() -> None:
    assert _score("Principal AI Engineer") > _score("Software Engineer")
    assert _score("Staff Engineer, AI Platform") > _score("Junior Engineer, Data")


def test_relevance_ai_pm_path_as_adjacent() -> None:
    pm = _score("Senior AI Product Manager")
    plain_pm = _score("Senior Product Manager")
    backend = _score("Senior Backend Engineer")
    assert pm > plain_pm >= backend  # AI wins; PM stays capped above generic BE


def test_relevance_missing_title_is_zero() -> None:
    assert compute_target_role_relevance({}) == 0.0


# ---------------------------------------------------------------------------
# Endpoint: review buckets default to relevance sort
# ---------------------------------------------------------------------------


def _seed_review_job(job_id: str, status: str, title: str, company: str = "Co") -> None:
    with session_scope() as db:
        upsert_entity(
            db,
            "aa_autopilot_job",
            {
                "id": job_id,
                "status": status,
                "title": title,
                "company": company,
                "applicationUrl": f"https://jobs.lever.co/{company.lower()}/{job_id}",
            },
        )


@pytest.fixture()
def review_queue():
    _seed_review_job("rel_test_ai", "NEEDS_REVIEW", "Senior AI Engineer", "NeuralWorks")
    _seed_review_job("rel_test_qa", "NEEDS_REVIEW", "QA Analyst Automation", "TestCo")
    _seed_review_job("rel_test_manual", "MANUAL_REVIEW", "Lead AI Engineer", "DeepCo")
    yield
    with session_scope() as db:
        from app.db.store import delete_entity

        for job_id in ("rel_test_ai", "rel_test_qa", "rel_test_manual"):
            delete_entity(db, "aa_autopilot_job", job_id)


def test_review_bucket_defaults_to_relevance_order(review_queue) -> None:
    with TestClient(app) as client:
        listing = client.get(
            "/application-assistant/autopilot/jobs",
            params={"status": "NEEDS_REVIEW", "limit": 10},
        )
        assert listing.status_code == 200
        titles = [j.get("title") or "" for j in listing.json()["jobs"]]
        assert titles.index("Senior AI Engineer") < titles.index("QA Analyst Automation")

        manual = client.get(
            "/application-assistant/autopilot/jobs",
            params={"status": "MANUAL_REVIEW", "limit": 10},
        )
        assert manual.status_code == 200
        manual_titles = [j.get("title") or "" for j in manual.json()["jobs"]]
        assert "Lead AI Engineer" in manual_titles


def test_explicit_relevance_sort_option(review_queue) -> None:
    with TestClient(app) as client:
        listing = client.get(
            "/application-assistant/autopilot/jobs",
            params={
                "status": "NEEDS_REVIEW",
                "sortBy": "relevance",
                "sortDir": "desc",
                "limit": 10,
            },
        )
        assert listing.status_code == 200
        jobs = listing.json()["jobs"]
        assert len(jobs) >= 2
