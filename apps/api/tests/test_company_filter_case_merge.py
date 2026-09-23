"""One company filter entry per employer, whatever casing each source stored."""

from __future__ import annotations

import pytest

from app.db.store import session_scope
from app.services.application_assistant.persistence import (
    delete_autopilot_job,
    get_autopilot_status_company_stats,
    save_autopilot_job,
)

JOBS = [
    {"id": "apjob_case_1", "status": "MANUAL_REVIEW", "company": "Casecorp", "title": "Senior SWE"},
    {"id": "apjob_case_2", "status": "MANUAL_REVIEW", "company": "Casecorp", "title": "senior swe"},
    {"id": "apjob_case_3", "status": "MANUAL_REVIEW", "company": "casecorp", "title": "Senior SWE"},
]


@pytest.fixture
def seeded():
    with session_scope() as db:
        for job in JOBS:
            save_autopilot_job(db, dict(job))
    yield
    with session_scope() as db:
        for job in JOBS:
            delete_autopilot_job(db, job["id"])


def test_company_spellings_that_differ_only_by_case_share_one_entry(seeded):
    with session_scope() as db:
        stats = get_autopilot_status_company_stats(db)

    manual = stats["companyCountsByStatus"]["manual"]
    assert manual.get("Casecorp") == 3
    assert "casecorp" not in manual
    titles = stats["titleCountsByStatus"]["manual"]
    assert titles.get("Senior SWE") == 3
    assert "senior swe" not in titles
