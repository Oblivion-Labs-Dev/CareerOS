"""Assisted fill and the batch must never work the same posting at once.

Regression: assisted fill opened a visible, submittable form on any status and
never took the posting claim, so a batch attempt at the same posting could run
alongside it and both could reach the employer.
"""

from __future__ import annotations

import asyncio

import pytest

from app.db.store import session_scope
from app.routers.application_assistant import autopilot as routes
from app.services.application_assistant.persistence import (
    application_identity,
    application_identity_holder,
    claim_application_identity,
    delete_autopilot_job,
    release_application_identity,
    save_autopilot_job,
)

URL = "https://boards.greenhouse.io/acme/jobs/7788990"


@pytest.fixture
def two_records():
    """Two records for one posting, as re-scrapes routinely produce."""
    with session_scope() as db:
        a = save_autopilot_job(db, {"id": "apjob_assist_a", "status": "NEEDS_REVIEW",
                                    "company": "Acme", "title": "SWE", "applicationUrl": URL})
        b = save_autopilot_job(db, {"id": "apjob_assist_b", "status": "QUEUED",
                                    "company": "Acme", "title": "SWE", "applicationUrl": URL})
    yield a, b
    with session_scope() as db:
        for job in (a, b):
            release_application_identity(db, application_identity(job), job["id"])
            delete_autopilot_job(db, job["id"])


def _fake_run(started: list):
    async def run(job_id, *args, **kwargs):
        started.append(job_id)
    return run


def test_assisted_fill_refuses_while_the_batch_holds_the_posting(two_records, monkeypatch):
    a, b = two_records
    started: list = []
    monkeypatch.setattr(routes, "_run_assisted_fill", _fake_run(started))
    with session_scope() as db:
        assert claim_application_identity(db, application_identity(b), b["id"])

    response = asyncio.run(routes.assisted_fill(a["id"]))

    assert response["success"] is False
    assert started == []


def test_assisted_fill_holds_the_posting_then_releases_it(two_records, monkeypatch):
    a, b = two_records
    started: list = []
    monkeypatch.setattr(routes, "_run_assisted_fill", _fake_run(started))
    identity = application_identity(a)

    async def scenario():
        response = await routes.assisted_fill(a["id"])
        with session_scope() as db:
            held_by = application_identity_holder(db, identity)
            batch_could_claim = claim_application_identity(db, identity, b["id"])
        await routes._ASSISTED_RUNS[a["id"]]
        await asyncio.sleep(0)  # let the done-callback run
        return response, held_by, batch_could_claim

    response, held_by, batch_could_claim = asyncio.run(scenario())

    assert response["success"] is True
    assert started == [a["id"]]
    assert held_by == a["id"]
    assert batch_could_claim is False
    with session_scope() as db:
        assert application_identity_holder(db, identity) is None
