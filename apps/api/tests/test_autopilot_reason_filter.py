"""Filtering a status tab by why its jobs are there, e.g. every reCAPTCHA-blocked Manual Review job."""

from __future__ import annotations

import pytest

from app.db.store import session_scope
from app.routers.application_assistant.autopilot import get_autopilot_jobs_list
from app.services.diagnostic_outcomes import OTHER_REASON, reason_category
from app.services.application_assistant.persistence import (
    AUTOPILOT_JOBS_CACHE_KEY,
    delete_autopilot_job,
    save_autopilot_job,
)
from app.services.read_cache import read_cache


@pytest.mark.parametrize(
    ("job", "expected"),
    [
        # The classified ineligibility reason wins over any text.
        ({"ineligibilityReason": "POSTING_EXPIRED", "lastError": "reCAPTCHA challenge"}, "POSTING_EXPIRED"),
        # Otherwise the Diagnostic page's patterns, in their order.
        ({"lastError": "Okta uses reCAPTCHA on its careers site"}, "Okta reCAPTCHA (known bot-protected)"),
        ({"lastError": "Blocked by a reCAPTCHA challenge"}, "Blocked by reCAPTCHA"),
        ({"skipReason": "DOM Verification mismatch: Required field 'Start date' is blank"}, "Required field left blank in the browser DOM"),
        # Unrecognised text is not a usable filter key.
        ({"lastError": "Something nobody has seen before at step 7"}, OTHER_REASON),
        ({}, "No reason recorded"),
    ],
)
def test_reason_category(job, expected):
    assert reason_category(job) == expected


JOBS = [
    {"id": "apjob_rsn_captcha_1", "status": "MANUAL_REVIEW", "company": "Acme", "title": "Senior SWE",
     "lastError": "Blocked by a reCAPTCHA challenge", "applicationUrl": "https://acme.example/jobs/1"},
    {"id": "apjob_rsn_captcha_2", "status": "MANUAL_REVIEW", "company": "Beta", "title": "Senior SWE",
     "lastError": "reCAPTCHA shown before submit", "applicationUrl": "https://beta.example/jobs/2"},
    {"id": "apjob_rsn_odd", "status": "MANUAL_REVIEW", "company": "Gamma", "title": "Senior SWE",
     "lastError": "An unrecognised failure", "applicationUrl": "https://gamma.example/jobs/3"},
    {"id": "apjob_rsn_expired", "status": "FAILED", "company": "Delta", "title": "Senior SWE",
     "ineligibilityReason": "POSTING_EXPIRED", "lastError": "Posting removed",
     "applicationUrl": "https://delta.example/jobs/4"},
]


@pytest.fixture
def seeded_jobs():
    with session_scope() as db:
        for job in JOBS:
            save_autopilot_job(db, dict(job))
    # A save only marks the cached job list stale, so a warm cache from an
    # earlier test would still be served; drop it on the way in and out.
    read_cache.invalidate(AUTOPILOT_JOBS_CACHE_KEY)
    yield
    with session_scope() as db:
        for job in JOBS:
            delete_autopilot_job(db, job["id"])
    read_cache.invalidate(AUTOPILOT_JOBS_CACHE_KEY)


def _ids(result):
    return {job["id"] for job in result["jobs"] if job["id"].startswith("apjob_rsn_")}


def test_reason_counts_cover_the_status_selection(seeded_jobs):
    result = get_autopilot_jobs_list(status="MANUAL_REVIEW", limit=1000, offset=0)

    assert result["reasonCounts"]["Blocked by reCAPTCHA"] >= 2
    assert result["reasonCounts"][OTHER_REASON] >= 1
    # The FAILED job is outside this tab, so it is neither listed nor counted.
    assert "apjob_rsn_expired" not in _ids(result)
    assert sum(result["reasonCounts"].values()) == result["total"]


def test_reason_filter_returns_only_that_reason_within_the_status(seeded_jobs):
    result = get_autopilot_jobs_list(status="MANUAL_REVIEW", reason="Blocked by reCAPTCHA", limit=1000, offset=0)

    assert _ids(result) == {"apjob_rsn_captcha_1", "apjob_rsn_captcha_2"}


def test_reason_filter_matches_classified_ineligibility(seeded_jobs):
    result = get_autopilot_jobs_list(status="FAILED", reason="POSTING_EXPIRED", limit=1000, offset=0)

    assert _ids(result) == {"apjob_rsn_expired"}


def test_other_collects_unrecognised_reasons(seeded_jobs):
    result = get_autopilot_jobs_list(status="MANUAL_REVIEW", reason=OTHER_REASON, limit=1000, offset=0)

    assert _ids(result) == {"apjob_rsn_odd"}


def test_no_reason_filter_leaves_the_list_unchanged(seeded_jobs):
    result = get_autopilot_jobs_list(status="MANUAL_REVIEW", reason=None, limit=1000, offset=0)

    assert {"apjob_rsn_captcha_1", "apjob_rsn_captcha_2", "apjob_rsn_odd"} <= _ids(result)


def test_diagnostic_report_still_keeps_unrecognised_text_as_its_own_bucket():
    # The Diagnostic page shows a new failure mode as a new row; only the
    # filter collapses it into "Other".
    from app.services.diagnostic_outcomes import _categorize

    assert _categorize("An unrecognised failure") == "An unrecognised failure"
    assert _categorize("x" * 80) == "x" * 70 + "…"
    assert _categorize("Blocked by a reCAPTCHA challenge") == "Blocked by reCAPTCHA"
