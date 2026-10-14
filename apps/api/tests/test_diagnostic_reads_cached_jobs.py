"""The diagnostic reports read the shared cached job list instead of
re-parsing every job row on each poll, and still reflect what was saved."""

from __future__ import annotations

from app.db.store import session_scope
from app.routers.diagnostic import get_metric_series, get_outcomes_report
from app.services.application_assistant.persistence import (
    AUTOPILOT_JOBS_CACHE_KEY,
    cached_autopilot_jobs,
    save_autopilot_job,
)
from app.services.read_cache import read_cache


def test_outcomes_and_series_see_saved_jobs_through_the_cache() -> None:
    read_cache.invalidate(AUTOPILOT_JOBS_CACHE_KEY)
    with session_scope() as db:
        save_autopilot_job(db, {
            "id": "apjob_diag_cache",
            "company": "DiagCacheCo",
            "title": "Engineer",
            "status": "SUBMITTED",
            "applicationUrl": "https://example.com/diag-cache",
        })
    read_cache.invalidate(AUTOPILOT_JOBS_CACHE_KEY)

    report = get_outcomes_report(period="12h")
    assert report["allTimeStatusCounts"].get("SUBMITTED", 0) >= 1
    assert "buckets" in get_metric_series(period="24h")

    assert cached_autopilot_jobs() is cached_autopilot_jobs()
