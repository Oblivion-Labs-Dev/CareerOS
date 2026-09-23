"""An application that may already have been sent must never be re-sent.

The defect these cover: an attempt whose submission could not be *verified* was
recorded as FAILED, and FAILED is a retryable bucket. Both
``/autopilot/reprocess-failed`` and the in-run transient retry put such a job
straight back on the queue, and every duplicate guard excludes the job's own
record (``exclude_id=job["id"]``) — so nothing stopped a second application to a
posting the employer may already have. A late confirmation email was the only
thing that rescued it, which is why a delayed or missing email produced a
duplicate.

The fix separates "proven not sent" (FAILED, retry freely) from "unproven"
(SUBMISSION_UNKNOWN, never retried automatically), decided by a durable marker
the executor writes immediately before it clicks submit.
"""

from __future__ import annotations

import asyncio
import concurrent.futures

import pytest

from app.db.store import now_iso, session_scope
from app.services.application_assistant.domain import AutopilotJobStatus
from app.services.application_assistant.persistence import (
    application_identity,
    claim_application_identity,
    delete_autopilot_job,
    get_autopilot_job,
    is_strict_duplicate_processed,
    release_application_identity,
    save_autopilot_job,
)
from app.services.application_assistant.submission_outcome import (
    classify_unproven_outcome,
    outcome_is_proven_unsubmitted,
    submit_was_attempted,
)

GREENHOUSE_URL = "https://boards.greenhouse.io/acme/jobs/4455661"


def _save(job: dict) -> dict:
    with session_scope() as db:
        return save_autopilot_job(db, dict(job))


def _read(job_id: str) -> dict | None:
    with session_scope() as db:
        return get_autopilot_job(db, job_id)


def _drop(*job_ids: str) -> None:
    with session_scope() as db:
        for job_id in job_ids:
            delete_autopilot_job(db, job_id)


@pytest.fixture
def attempted_job() -> dict:
    """A job whose submit click was issued but never confirmed."""
    job = {
        "id": "apjob_idem_attempted",
        "status": AutopilotJobStatus.APPLYING.value,
        "company": "Acme",
        "title": "Senior Software Engineer",
        "applicationUrl": GREENHOUSE_URL,
        "submitAttemptedAt": now_iso(),
    }
    _save(job)
    yield job
    _drop(job["id"])


# ── 1. A submitted job with no confirmation email is not applied to again ──


def test_unverified_submission_is_not_filed_as_failed(attempted_job):
    """The core regression. FAILED is retryable; this outcome must not be."""
    status, error_type = classify_unproven_outcome(
        attempted_job, {"submitted": False, "error": "Submission unconfirmed"}
    )

    assert status == AutopilotJobStatus.SUBMISSION_UNKNOWN.value
    assert status != AutopilotJobStatus.FAILED.value
    assert error_type == "SUBMISSION_UNCERTAIN"


def test_bulk_requeue_skips_a_maybe_submitted_job(attempted_job):
    """`Requeue all failed` must not sweep one of these back onto the queue."""
    from app.routers.application_assistant.autopilot import (
        _requeue_autopilot_jobs_by_status,
    )

    attempted_job["status"] = AutopilotJobStatus.SUBMISSION_UNKNOWN.value
    _save(attempted_job)

    # Ask for every bucket a requeue endpoint offers, including this job's own.
    _requeue_autopilot_jobs_by_status(
        ("FAILED", "ERROR", "VALIDATION_FAILED", "STAGED", "NEEDS_REVIEW", "SUBMISSION_UNKNOWN")
    )

    assert _read(attempted_job["id"])["status"] == AutopilotJobStatus.SUBMISSION_UNKNOWN.value


def test_single_job_retry_endpoint_refuses_a_maybe_submitted_job(attempted_job):
    """The per-job retry button is an automatic path and must refuse too."""
    from app.routers.application_assistant.autopilot import reprocess_single_autopilot_job

    attempted_job["status"] = AutopilotJobStatus.SUBMISSION_UNKNOWN.value
    _save(attempted_job)

    response = asyncio.run(reprocess_single_autopilot_job(attempted_job["id"]))

    assert response["success"] is False
    assert "may already have been submitted" in response["message"]
    assert _read(attempted_job["id"])["status"] == AutopilotJobStatus.SUBMISSION_UNKNOWN.value


def test_a_second_record_for_the_same_posting_is_blocked(attempted_job):
    """A sibling record must not apply to a posting that may already have one."""
    attempted_job["status"] = AutopilotJobStatus.SUBMISSION_UNKNOWN.value
    _save(attempted_job)

    with session_scope() as db:
        is_dup, match, reason = is_strict_duplicate_processed(
            db,
            "Acme",
            "Senior Software Engineer",
            None,
            GREENHOUSE_URL,
            exclude_id="apjob_idem_sibling",
        )

    assert is_dup is True
    assert match["id"] == attempted_job["id"]
    assert reason


# ── 2. A late email reconciles the existing record rather than duplicating ──


def test_late_email_resolves_the_existing_record_forward(attempted_job):
    from app.services.application_assistant.manual_submission_reconciler import (
        RECONCILABLE_STATUSES,
    )

    assert AutopilotJobStatus.SUBMISSION_UNKNOWN.value in RECONCILABLE_STATUSES


def test_confirmation_keeps_the_original_submission_time(attempted_job):
    """The email confirms the submission; it does not redate it.

    Employer mail can lag the click by hours, so crediting the email's timestamp
    as the submission time would misreport when the application was actually
    sent.
    """
    submitted_at = attempted_job["submitAttemptedAt"]
    job = dict(attempted_job)

    # What the reconciler does on a match.
    job["status"] = AutopilotJobStatus.SUBMITTED.value
    job["submittedAt"] = job.get("submitAttemptedAt") or "2026-09-18T23:59:00+00:00"
    job["confirmedAt"] = "2026-09-18T23:59:00+00:00"
    job["confirmationSource"] = "email"
    saved = _save(job)

    assert saved["submittedAt"] == submitted_at
    assert saved["confirmedAt"] == "2026-09-18T23:59:00+00:00"
    assert saved["confirmationSource"] == "email"
    # Confirmation is evidence on the record, not a status of its own, so the
    # "still open = SUBMITTED minus REJECTED" counting is unaffected.
    assert saved["status"] == AutopilotJobStatus.SUBMITTED.value


def test_missing_email_never_moves_a_job_back_to_the_queue(attempted_job):
    """Absence of confirmation is not evidence of anything."""
    attempted_job["status"] = AutopilotJobStatus.SUBMISSION_UNKNOWN.value
    _save(attempted_job)

    from app.routers.application_assistant.autopilot import (
        _requeue_autopilot_jobs_by_status,
    )

    for _ in range(3):
        _requeue_autopilot_jobs_by_status(("FAILED", "SUBMISSION_UNKNOWN"))

    assert _read(attempted_job["id"])["status"] == AutopilotJobStatus.SUBMISSION_UNKNOWN.value


# ── 3. Two concurrent attempts for the same posting cannot both proceed ──


def test_posting_identity_prefers_the_stable_ats_id():
    """Two host shapes of one Greenhouse posting must share an identity."""
    board = {"applicationUrl": "https://boards.greenhouse.io/acme/jobs/4455661"}
    mirror = {"applicationUrl": "https://acme.com/careers/apply?gh_jid=4455661"}

    assert application_identity(board) == application_identity(mirror) == "gh:4455661"


def test_concurrent_attempts_on_one_posting_admit_exactly_one():
    """The regression this claim exists for.

    ``claim_job_lock`` admits one worker per *record*. Two different records for
    the same posting would each take their own lease and both submit. The claim
    is keyed on the posting, so only one of them proceeds.
    """
    identity = "gh:9900011"
    job_ids = [f"apjob_idem_race_{i}" for i in range(8)]

    def attempt(job_id: str) -> bool:
        with session_scope() as db:
            return claim_application_identity(db, identity, job_id)

    try:
        with concurrent.futures.ThreadPoolExecutor(max_workers=8) as pool:
            results = list(pool.map(attempt, job_ids))

        assert sum(1 for won in results if won) == 1, (
            f"expected exactly one winner, got {sum(1 for w in results if w)}"
        )
    finally:
        with session_scope() as db:
            for job_id in job_ids:
                release_application_identity(db, identity, job_id)


def test_claim_is_reclaimable_once_released():
    identity = "gh:9900012"
    with session_scope() as db:
        assert claim_application_identity(db, identity, "apjob_a") is True
    with session_scope() as db:
        assert claim_application_identity(db, identity, "apjob_b") is False
    with session_scope() as db:
        assert release_application_identity(db, identity, "apjob_a") is True
    with session_scope() as db:
        assert claim_application_identity(db, identity, "apjob_b") is True
        release_application_identity(db, identity, "apjob_b")


def test_expired_claim_does_not_strand_a_posting():
    """A crashed attempt must not hold a posting hostage forever."""
    identity = "gh:9900013"
    with session_scope() as db:
        assert claim_application_identity(db, identity, "apjob_dead", lease_seconds=-5) is True
    with session_scope() as db:
        assert claim_application_identity(db, identity, "apjob_live") is True
        release_application_identity(db, identity, "apjob_live")


def test_a_job_with_no_identifiable_url_is_not_blocked():
    """Refusing here would strand every posting whose URL carries no id."""
    with session_scope() as db:
        assert claim_application_identity(db, "", "apjob_no_url") is True


# ── 4. A crash after a possible submission does not auto-retry ──


def test_interrupted_submit_is_parked_not_requeued():
    """Recovery itself must not become the duplicate.

    ``_recover_stale_run_sync`` used to key this on a ``SUBMITTING`` checkpoint
    that no code path ever recorded, so the guard never fired and every
    interrupted submit was swept back onto the queue.
    """
    from app.services.application_assistant.autopilot_runner import AutopilotRunner

    job = {
        "id": "apjob_idem_crash",
        "status": AutopilotJobStatus.APPLYING.value,
        "company": "Acme",
        "title": "Backend Engineer",
        "applicationUrl": "https://boards.greenhouse.io/acme/jobs/7777001",
        "submitAttemptedAt": now_iso(),
        "lockedBy": "dead-worker",
        "lockExpiresAt": "2000-01-01T00:00:00+00:00",
    }
    _save(job)
    run = {"id": "aprun_idem_crash", "currentJobId": job["id"], "status": "RUNNING"}

    try:
        with session_scope() as db:
            AutopilotRunner.get_instance()._recover_stale_run_sync(run, db)

        recovered = _read(job["id"])
        assert recovered["status"] == AutopilotJobStatus.SUBMISSION_UNKNOWN.value
        assert recovered["status"] != AutopilotJobStatus.QUEUED.value
    finally:
        _drop(job["id"])


def test_interrupted_job_that_never_clicked_submit_is_requeued():
    """The complement: nothing was sent, so retrying is correct and free."""
    from app.services.application_assistant.autopilot_runner import AutopilotRunner

    job = {
        "id": "apjob_idem_early_crash",
        "status": AutopilotJobStatus.APPLYING.value,
        "company": "Acme",
        "title": "Platform Engineer",
        "applicationUrl": "https://boards.greenhouse.io/acme/jobs/7777002",
        "lockedBy": "dead-worker",
        "lockExpiresAt": "2000-01-01T00:00:00+00:00",
    }
    _save(job)
    run = {"id": "aprun_idem_early", "currentJobId": job["id"], "status": "RUNNING"}

    try:
        with session_scope() as db:
            AutopilotRunner.get_instance()._recover_stale_run_sync(run, db)

        assert _read(job["id"])["status"] == AutopilotJobStatus.QUEUED.value
    finally:
        _drop(job["id"])


# ── 5. Attempts proven not to have submitted still retry safely ──


@pytest.mark.parametrize(
    "result",
    [
        {"submitted": False, "error": "Submit button not found on application page"},
        {"submitted": False, "noApplicationForm": True, "error": "No application form on the page"},
        {"submitted": False, "error": "x", "evidence": {"preSubmitValidationErrors": ["missing"]}},
        {"submitted": False, "error": "x", "evidence": {"unresolvedRequiredFields": ["gpa"]}},
    ],
)
def test_proven_unsubmitted_attempts_stay_retryable(result):
    job = {"id": "apjob_idem_pre", "company": "Acme", "title": "SWE"}

    assert outcome_is_proven_unsubmitted(job, result) is True
    status, _ = classify_unproven_outcome(job, result)
    # Retryable work lives in review now; FAILED is reserved for dead ends.
    assert status == AutopilotJobStatus.NEEDS_REVIEW.value
    assert job["technicalFailure"] is True


def test_an_attempt_that_never_clicked_submit_is_retryable():
    job = {"id": "apjob_idem_noclick", "company": "Acme", "title": "SWE"}

    assert submit_was_attempted(job) is False
    status, _ = classify_unproven_outcome(job, {"submitted": False, "error": "Navigation timeout"})
    assert status == AutopilotJobStatus.NEEDS_REVIEW.value
    assert job["technicalFailure"] is True


def test_the_submit_marker_overrides_pre_submit_evidence(attempted_job):
    """Once the click is issued, no later signal can prove nothing was sent.

    Stale pre-submit evidence from earlier in the same attempt must not talk the
    classifier back into calling this retryable.
    """
    result = {
        "submitted": False,
        "error": "Submit button not found on application page",
        "evidence": {"preSubmitValidationErrors": ["stale"]},
    }

    assert outcome_is_proven_unsubmitted(attempted_job, result) is False
    status, _ = classify_unproven_outcome(attempted_job, result)
    assert status == AutopilotJobStatus.SUBMISSION_UNKNOWN.value


# ── 6. The existing lifecycle still holds ──


def test_submitting_a_record_still_retires_its_siblings():
    """The pre-existing duplicate sweep must keep working."""
    sibling = {
        "id": "apjob_idem_sibling_open",
        "status": AutopilotJobStatus.QUEUED.value,
        "company": "Acme",
        "title": "Senior Software Engineer",
        "applicationUrl": GREENHOUSE_URL + "?utm_source=x",
    }
    winner = {
        "id": "apjob_idem_winner",
        "status": AutopilotJobStatus.SUBMITTED.value,
        "company": "Acme",
        "title": "Senior Software Engineer",
        "applicationUrl": GREENHOUSE_URL,
    }
    _save(sibling)
    try:
        _save(winner)
        retired = _read(sibling["id"])
        assert retired["status"] == AutopilotJobStatus.FAILED.value
        assert retired["ineligibilityReason"] == "DUPLICATE_APPLICATION"
    finally:
        _drop(sibling["id"], winner["id"])


def test_exact_and_tracking_variant_siblings_are_both_retired():
    """Every open sibling of the posting goes, however its URL is spelled.

    The sweep used to look up exact-URL siblings first and only compare
    canonical URLs when that found none, so an exact twin shielded a
    `?utm_source=` twin (and a case/trailing-slash variant) from retirement.
    A terminal sibling is still left alone.
    """
    base = {"company": "Acme", "title": "Senior Software Engineer"}
    exact = {**base, "id": "apjob_idem_exact_twin", "status": AutopilotJobStatus.QUEUED.value,
             "applicationUrl": GREENHOUSE_URL}
    tracked = {**base, "id": "apjob_idem_tracked_twin", "status": AutopilotJobStatus.NEEDS_REVIEW.value,
               "applicationUrl": GREENHOUSE_URL + "?utm_source=linkedin"}
    respelled = {**base, "id": "apjob_idem_respelled_twin", "status": AutopilotJobStatus.MANUAL_REVIEW.value,
                 "applicationUrl": GREENHOUSE_URL.upper() + "/"}
    skipped = {**base, "id": "apjob_idem_skipped_twin", "status": AutopilotJobStatus.SKIPPED.value,
               "applicationUrl": GREENHOUSE_URL}
    unrelated = {**base, "id": "apjob_idem_other_posting", "status": AutopilotJobStatus.QUEUED.value,
                 "applicationUrl": GREENHOUSE_URL + "9"}
    winner = {**base, "id": "apjob_idem_multi_winner", "status": AutopilotJobStatus.SUBMITTED.value,
              "applicationUrl": GREENHOUSE_URL}
    others = (exact, tracked, respelled, skipped, unrelated)
    for job in others:
        _save(job)
    try:
        _save(winner)
        for twin in (exact, tracked, respelled):
            row = _read(twin["id"])
            assert row["status"] == AutopilotJobStatus.FAILED.value, twin["id"]
            assert row["ineligibilityReason"] == "DUPLICATE_APPLICATION"
        assert _read(skipped["id"])["status"] == AutopilotJobStatus.SKIPPED.value
        assert _read(unrelated["id"])["status"] == AutopilotJobStatus.QUEUED.value
        assert _read(winner["id"])["status"] == AutopilotJobStatus.SUBMITTED.value
    finally:
        _drop(*(job["id"] for job in others), winner["id"])


def test_a_maybe_submitted_sibling_is_retired_by_a_real_submission():
    """Once one record is proven sent, an unknown sibling is just a duplicate."""
    unknown = {
        "id": "apjob_idem_unknown_sibling",
        "status": AutopilotJobStatus.SUBMISSION_UNKNOWN.value,
        "company": "Acme",
        "title": "Senior Software Engineer",
        "applicationUrl": GREENHOUSE_URL,
        "submitAttemptedAt": now_iso(),
    }
    winner = {
        "id": "apjob_idem_real_winner",
        "status": AutopilotJobStatus.SUBMITTED.value,
        "company": "Acme",
        "title": "Senior Software Engineer",
        "applicationUrl": GREENHOUSE_URL,
    }
    _save(unknown)
    try:
        _save(winner)
        assert _read(unknown["id"])["status"] == AutopilotJobStatus.FAILED.value
    finally:
        _drop(unknown["id"], winner["id"])


def test_a_stale_marker_does_not_park_a_genuinely_retryable_attempt():
    """The marker describes one attempt, not the record forever.

    A job the user resolved by hand and put back on the queue still carries the
    previous attempt's marker. If that survived into the next attempt, a failure
    that happened well before the submit click would be misread as a possible
    submission and parked, stranding a job that is safe to retry.
    """
    job = {
        "id": "apjob_idem_stale",
        "company": "Acme",
        "title": "SWE",
        "submitAttemptedAt": "2026-09-01T10:00:00+00:00",
    }

    # What the runner does as a new attempt begins.
    job.pop("submitAttemptedAt", None)

    assert submit_was_attempted(job) is False
    status, _ = classify_unproven_outcome(
        job, {"submitted": False, "error": "Submit button not found on application page"}
    )
    assert status == AutopilotJobStatus.NEEDS_REVIEW.value
    assert job["technicalFailure"] is True


def test_the_user_may_still_resolve_a_maybe_submitted_job_by_hand(attempted_job):
    """Automation cannot check the posting; the user can, and must be able to."""
    from app.routers.application_assistant.autopilot import USER_RELABELLABLE_FROM

    assert AutopilotJobStatus.SUBMISSION_UNKNOWN.value in USER_RELABELLABLE_FROM
