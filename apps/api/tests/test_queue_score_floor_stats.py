"""/autopilot/stats reports how many queued jobs clear each match-score floor.

The console's floor dropdown needs "how many queued jobs would pass at 70?"
without pulling every row. Unscored rows (no score, or the "unscored"
placeholder stored as 0.0) are counted as unscored, never as a score of 0.
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

FLOORS = ("40", "50", "60", "70", "80", "90")

ROWS = [
    # id, status, matchScore, matchMethod
    ("qsf_95", "QUEUED", 95.0, "role-shape"),
    ("qsf_80", "QUEUED", 80.0, "role-shape"),
    ("qsf_65", "QUEUED", 65.5, "role-shape"),
    ("qsf_45", "QUEUED", 45.0, "role-shape"),
    ("qsf_10", "QUEUED", 10.0, "role-shape"),
    ("qsf_placeholder", "QUEUED", 0.0, "unscored"),
    ("qsf_missing", "QUEUED", None, None),
    # Not waiting in the queue: never counted, whatever the score.
    ("qsf_submitted", "SUBMITTED", 99.0, "role-shape"),
    ("qsf_review", "NEEDS_REVIEW", 85.0, "role-shape"),
]


def _stats(client: TestClient, **params) -> dict:
    read_cache.invalidate(AUTOPILOT_STATS_CACHE_KEY)
    return client.get("/application-assistant/autopilot/stats", params=params).json()


@pytest.fixture()
def baseline():
    with TestClient(app) as client:
        before = _stats(client, facets="false")
    with session_scope() as db:
        for job_id, status, score, method in ROWS:
            row = {
                "id": job_id,
                "status": status,
                "title": "Backend Engineer",
                "company": "FloorCo",
                "applicationUrl": f"https://jobs.lever.co/floorco/{job_id}",
            }
            if score is not None:
                row["matchScore"] = score
            if method is not None:
                row["matchMethod"] = method
            save_autopilot_job(db, row)
    read_cache.invalidate(AUTOPILOT_JOBS_CACHE_KEY)
    yield before
    with session_scope() as db:
        for job_id, *_ in ROWS:
            delete_entity(db, "aa_autopilot_job", job_id)
    read_cache.invalidate(AUTOPILOT_JOBS_CACHE_KEY)
    read_cache.invalidate(AUTOPILOT_STATS_CACHE_KEY)


@pytest.mark.parametrize("facets", ["true", "false"])
def test_stats_count_queued_jobs_per_score_floor(baseline, facets) -> None:
    with TestClient(app) as client:
        after = _stats(client, facets=facets)

    assert sorted(after["queueScoreFloors"]) == sorted(FLOORS)
    delta = {k: after["queueScoreFloors"][k] - baseline["queueScoreFloors"][k] for k in FLOORS}
    assert delta == {"40": 4, "50": 3, "60": 3, "70": 2, "80": 2, "90": 1}
    assert after["queueScored"] - baseline["queueScored"] == 5
    # The 0.0 placeholder and the row with no score are unscored, not "below 40".
    assert after["queueUnscored"] - baseline["queueUnscored"] == 2
