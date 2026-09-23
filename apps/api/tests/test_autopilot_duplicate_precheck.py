"""The per-job "already submitted" pre-check in the autopilot runner.

Before each attempt the runner refuses a job whose posting was already
submitted, matching by URL *or* by (company, title) - see
`find_duplicate_submission`. It used to read the SUBMITTED rows out of
`all_db_jobs`, a full job-table load that only happened inside the
company-cap branch. Clicking Apply skips that branch, so for exactly the jobs
the user asked for the variable was never assigned and the check crashed.
"""

from __future__ import annotations

import asyncio

import pytest

from app.db.store import session_scope
from app.services.application_assistant import autopilot_runner as module
from app.services.application_assistant.domain import AutopilotJobStatus
from app.services.application_assistant.persistence import (
    delete_autopilot_job,
    get_autopilot_job,
    save_autopilot_job,
)

PRIOR = {
    "id": "apjob_precheck_prior",
    "status": AutopilotJobStatus.SUBMITTED.value,
    "company": "Precheck Corp",
    "title": "Backend Engineer",
    # A different URL: only the company+title arm of the check can catch it,
    # and the strict any-status check (which requires the URL) cannot.
    "applicationUrl": "https://jobs.example.com/precheck/old-listing",
    "submittedAt": "2026-09-01T12:00:00+00:00",
}


def _candidate(job_id: str) -> dict:
    return {
        "id": job_id,
        "status": AutopilotJobStatus.QUEUED.value,
        "company": "Precheck Corp",
        "title": "Backend Engineer",
        "applicationUrl": "https://jobs.example.com/precheck/relisted",
    }


@pytest.fixture
def prior_submission():
    with session_scope() as db:
        save_autopilot_job(db, dict(PRIOR))
    yield PRIOR
    with session_scope() as db:
        delete_autopilot_job(db, PRIOR["id"])


@pytest.fixture
def no_attempt(monkeypatch):
    """Fail loudly if the runner gets past the duplicate checks."""

    def _tripwire(*_args, **_kwargs):
        raise AssertionError("runner went on to attempt a posting it had already submitted")

    monkeypatch.setattr(module, "application_identity", _tripwire)


@pytest.mark.parametrize("clicked_apply", [False, True], ids=["batch", "apply-clicked"])
def test_an_already_submitted_posting_is_not_attempted_again(
    prior_submission, no_attempt, clicked_apply
):
    job = _candidate(f"apjob_precheck_{'clicked' if clicked_apply else 'batch'}")
    with session_scope() as db:
        save_autopilot_job(db, dict(job))
    runner = module.AutopilotRunner()
    if clicked_apply:
        runner.manual_apply_job_ids = {job["id"]}
    try:
        asyncio.run(runner._process_single_job_with_retries("run_precheck", job))

        with session_scope() as db:
            stored = get_autopilot_job(db, job["id"])
        assert stored["status"] == AutopilotJobStatus.FAILED.value
        assert stored["ineligibilityReason"] == "DUPLICATE_APPLICATION"
        assert "Already applied to this posting" in stored["lastError"]
    finally:
        with session_scope() as db:
            delete_autopilot_job(db, job["id"])
