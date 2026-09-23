"""Regression: a stale skipReason from a past attempt must not survive a re-claim.

Found live during the #59/#60 overnight batch: a Snowflake job's first attempt (days
earlier) was skipped as OUTSIDE_UNITED_STATES. On a later attempt it hit a genuine
reCAPTCHA block instead - a live posting, MANUAL_REVIEW territory - but the never-cleared
`skipReason` text still matched OUTSIDE_UNITED_STATES in classify_ineligibility's haystack
before the real reCAPTCHA text in `lastError` was even considered, so the job was filed
INELIGIBLE (a dead end nobody reviews) instead.
"""

import asyncio
from contextlib import contextmanager

import pytest

from app.services.application_assistant import autopilot_runner as module
from app.services.application_assistant import company_cap, persistence


def test_stale_diagnostic_fields_are_cleared_before_a_new_attempt(monkeypatch):
    saved = []

    @contextmanager
    def session():
        yield None

    monkeypatch.setattr(module, "session_scope", session)
    monkeypatch.setattr(module, "save_autopilot_job", lambda db, job: saved.append(dict(job)))
    monkeypatch.setattr(module, "claim_application_identity", lambda *a, **k: True)
    monkeypatch.setattr(persistence, "is_strict_duplicate_processed", lambda *a, **k: (False, None, None))
    monkeypatch.setattr(persistence, "list_submitted_duplicate_candidates", lambda *a, **k: [])
    monkeypatch.setattr(persistence, "list_autopilot_jobs", lambda *a, **k: [])
    monkeypatch.setattr(company_cap, "company_hold", lambda *a, **k: None)

    seen_at_pipeline: dict = {}

    async def fake_pipeline(run_id, job_item, worker_state=None):
        seen_at_pipeline.update(job_item)
        # Return normally: this attempt's own outcome is out of scope for this
        # test, which only checks the claim-time reset.

    runner = module.AutopilotRunner()
    monkeypatch.setattr(runner, "_execute_application_pipeline", fake_pipeline)

    job = {
        "id": "apjob_stale",
        "company": "Snowflake",
        "title": "Senior Software Engineer - Capacity",
        "applicationUrl": "https://jobs.ashbyhq.com/snowflake/abc123",
        "status": "QUEUED",
        "attemptCount": 1,
        # Left over from a rejection on a previous attempt, days earlier.
        "skipReason": "Location 'US-WA-Bellevue' is outside the United States",
        "lastError": "Location 'US-WA-Bellevue' is outside the United States",
        "aiExplanation": "Location 'US-WA-Bellevue' is outside the United States",
        "lastErrorType": "VALIDATION_ERROR",
        "ineligibilityReason": "OUTSIDE_UNITED_STATES",
        "ineligibilityDetail": "Location 'US-WA-Bellevue' is outside the United States",
    }

    asyncio.run(runner._process_single_job_with_retries("run", job))

    for stale_field in (
        "skipReason", "lastError", "aiExplanation", "lastErrorType",
        "ineligibilityReason", "ineligibilityDetail",
    ):
        assert stale_field not in seen_at_pipeline, (
            f"{stale_field} leaked into the new attempt: {seen_at_pipeline.get(stale_field)!r}"
        )
    assert seen_at_pipeline["attemptCount"] == 2
