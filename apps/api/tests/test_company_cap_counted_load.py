"""The runner's per-job cap check reads only the statuses a cap counts, so it
must reach the same hold as a check over the whole job table."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from app.db.store import session_scope, upsert_entity
from app.services.application_assistant import company_cap
from app.services.application_assistant.persistence import (
    ENTITY_AUTOPILOT_JOB,
    list_autopilot_jobs,
    list_company_cap_counted_jobs,
)

_COMPANY = "CountedLoadCo"


def _seed(db, status: str, submitted: datetime) -> str:
    job = upsert_entity(
        db,
        ENTITY_AUTOPILOT_JOB,
        {
            "company": _COMPANY,
            "title": "Engineer",
            "status": status,
            "submittedAt": submitted.isoformat(),
            "applicationUrl": f"https://example.com/{status}/{submitted.timestamp()}",
        },
    )
    return job["id"]


def test_counted_load_reaches_the_same_hold_as_a_full_load() -> None:
    now = datetime.now(timezone.utc)
    with session_scope() as db:
        for i in range(company_cap.COMPANY_CAP_TIERS[0][1]):
            _seed(db, ("SUBMITTED", "REJECTED", "SUBMISSION_UNKNOWN")[i % 3], now - timedelta(hours=i + 1))
        for status in ("NEEDS_REVIEW", "MANUAL_REVIEW", "FAILED", "QUEUED", "SKIPPED"):
            _seed(db, status, now - timedelta(minutes=30))

        full = list_autopilot_jobs(db)
        counted = list_company_cap_counted_jobs(db)

    assert {j["status"] for j in counted} <= company_cap.COUNTED_STATUSES
    assert company_cap.build_submission_index(counted, now=now) == company_cap.build_submission_index(
        full, now=now
    )

    full_hold = company_cap.company_hold(full, _COMPANY, now=now)
    assert full_hold is not None and full_hold.tier == "day"
    assert company_cap.company_hold(counted, _COMPANY, now=now) == full_hold
