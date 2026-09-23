"""The 2026-09-23 bucket model: FAILED = dead end never retried, retryable work
lives in review, INELIGIBLE = candidate barred only."""

from __future__ import annotations

import pytest

from app.db.store import get_kv, session_scope, set_kv
from app.services.application_assistant.bucket_migration import (
    KV_BUCKET_MODEL,
    migrate_bucket_model,
)
from app.services.application_assistant.domain import IneligibilityReason
from app.services.application_assistant.ineligibility import apply_ineligibility
from app.services.application_assistant.persistence import (
    delete_autopilot_job,
    get_autopilot_job,
    save_autopilot_job,
)
from app.services.application_assistant.submission_outcome import (
    classify_unproven_outcome,
    is_retryable_technical_failure,
)


# ── new outcomes ────────────────────────────────────────────────────────────

def test_a_proven_unsent_failure_is_retryable_review_not_failed():
    job = {"id": "j", "status": "APPLYING", "lastError": "Timeout 60000ms exceeded"}
    status, _ = classify_unproven_outcome(job)
    job["status"] = status
    assert status == "NEEDS_REVIEW"
    assert is_retryable_technical_failure(job)


def test_an_unproven_outcome_is_still_submission_unknown_and_never_retryable():
    job = {"id": "j", "status": "APPLYING", "submitAttemptedAt": "2026-09-23T00:00:00Z"}
    status, error = classify_unproven_outcome(job)
    job["status"] = status
    assert status == "SUBMISSION_UNKNOWN"
    assert error == "SUBMISSION_UNCERTAIN"
    assert not is_retryable_technical_failure(job)


@pytest.mark.parametrize(
    ("reason", "bucket"),
    [
        (IneligibilityReason.POSTING_EXPIRED, "FAILED"),
        (IneligibilityReason.NOT_A_REAL_POSTING, "FAILED"),
        (IneligibilityReason.DUPLICATE_APPLICATION, "FAILED"),
        (IneligibilityReason.REQUIRES_US_CITIZENSHIP, "INELIGIBLE"),
        (IneligibilityReason.NO_VISA_SPONSORSHIP, "INELIGIBLE"),
        (IneligibilityReason.OUTSIDE_UNITED_STATES, "INELIGIBLE"),
        (IneligibilityReason.COMPANY_BLACKLISTED, "INELIGIBLE"),
        (IneligibilityReason.BOT_PROTECTED_BOARD, "MANUAL_REVIEW"),
        (IneligibilityReason.REQUIRES_UNAVAILABLE_INFORMATION, "NEEDS_REVIEW"),
    ],
)
def test_each_reason_lands_in_its_bucket(reason, bucket):
    job = apply_ineligibility({"id": "j", "status": "APPLYING"}, reason, "detail")
    assert job["status"] == bucket
    assert job["ineligibilityReason"] == reason.value


def test_a_dead_end_is_never_a_retryable_failure():
    job = apply_ineligibility({"id": "j", "technicalFailure": True}, IneligibilityReason.POSTING_EXPIRED, "gone")
    assert job["status"] == "FAILED"
    assert not is_retryable_technical_failure(job)


# ── retry paths ─────────────────────────────────────────────────────────────

RETRY_JOBS = [
    {"id": "apjob_bm_dead", "status": "FAILED", "company": "Deadco", "title": "SWE",
     "ineligibilityReason": "POSTING_EXPIRED", "applicationUrl": "https://example.com/dead"},
    {"id": "apjob_bm_broke", "status": "NEEDS_REVIEW", "company": "Brokeco", "title": "SWE",
     "technicalFailure": True, "applicationUrl": "https://example.com/broke"},
    {"id": "apjob_bm_question", "status": "NEEDS_REVIEW", "company": "Askco", "title": "SWE",
     "pendingQuestions": [{"question": "Why us?"}], "applicationUrl": "https://example.com/ask"},
]


@pytest.fixture
def retry_jobs():
    with session_scope() as db:
        for job in RETRY_JOBS:
            save_autopilot_job(db, dict(job))
    yield
    with session_scope() as db:
        for job in RETRY_JOBS:
            delete_autopilot_job(db, job["id"])


def _status(job_id):
    with session_scope() as db:
        return get_autopilot_job(db, job_id)["status"]


def test_retry_failed_requeues_technical_failures_but_never_a_dead_end(retry_jobs):
    from app.routers.application_assistant.autopilot import _requeue_autopilot_jobs_by_status

    _requeue_autopilot_jobs_by_status(("ERROR", "VALIDATION_FAILED"), retryable_failures=True)

    assert _status("apjob_bm_broke") == "QUEUED"
    assert _status("apjob_bm_dead") == "FAILED"
    assert _status("apjob_bm_question") == "NEEDS_REVIEW"


# ── migration of existing rows ──────────────────────────────────────────────

MIGRATION_JOBS = [
    {"id": "apjob_mig_old_failed", "status": "FAILED", "company": "A", "title": "Senior Software Engineer",
     "lastError": "Timed out", "applicationUrl": "https://boards.greenhouse.io/a/jobs/1"},
    {"id": "apjob_mig_clicked", "status": "FAILED", "company": "B", "title": "Senior Software Engineer",
     "submitAttemptedAt": "2026-09-10T00:00:00Z", "applicationUrl": "https://boards.greenhouse.io/b/jobs/1"},
    {"id": "apjob_mig_expired", "status": "INELIGIBLE", "company": "C", "title": "Senior Software Engineer",
     "ineligibilityReason": "POSTING_EXPIRED", "applicationUrl": "https://boards.greenhouse.io/c/jobs/1"},
    {"id": "apjob_mig_us", "status": "INELIGIBLE", "company": "Snowflake", "title": "Senior Software Engineer",
     "location": "US-WA-Bellevue", "ineligibilityReason": "OUTSIDE_UNITED_STATES",
     "applicationUrl": "https://careers.snowflake.com/us/en/job/1"},
    {"id": "apjob_mig_citizen", "status": "INELIGIBLE", "company": "D", "title": "Senior Software Engineer",
     "ineligibilityReason": "REQUIRES_US_CITIZENSHIP", "applicationUrl": "https://boards.greenhouse.io/d/jobs/1"},
]


@pytest.fixture
def migration_jobs():
    with session_scope() as db:
        previous = get_kv(db, KV_BUCKET_MODEL)
        set_kv(db, KV_BUCKET_MODEL, {})
        for job in MIGRATION_JOBS:
            save_autopilot_job(db, dict(job))
    yield
    with session_scope() as db:
        for job in MIGRATION_JOBS:
            delete_autopilot_job(db, job["id"])
        set_kv(db, KV_BUCKET_MODEL, previous or {})


def test_existing_rows_move_onto_the_new_model_once(migration_jobs):
    with session_scope() as db:
        first = migrate_bucket_model(db)

    assert _status("apjob_mig_old_failed") == "NEEDS_REVIEW"
    with session_scope() as db:
        assert get_autopilot_job(db, "apjob_mig_old_failed")["technicalFailure"] is True
    # A submit may already have reached the employer: never made retryable.
    assert _status("apjob_mig_clicked") == "FAILED"
    assert _status("apjob_mig_expired") == "FAILED"
    # Wrongly labelled "outside the US" by the old location check.
    assert _status("apjob_mig_us") == "QUEUED"
    assert _status("apjob_mig_citizen") == "INELIGIBLE"
    assert first["counts"]["failed_to_needs_review"] >= 1

    with session_scope() as db:
        second = migrate_bucket_model(db)
    assert second.get("skipped") is True
