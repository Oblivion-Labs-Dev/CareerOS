"""Auto-marking a manually-finished application from its confirmation email.

The rule that matters most here is one-email-one-job. Most ATS confirmations
name only the employer ("Thank you for applying to Robinhood"), so an
unrestricted match marked *every* open Robinhood job as submitted off a single
email — observed live: two real confirmations marked thirteen applications, and
eleven of those had never been sent. A false positive hides a real opportunity
from the list the user works through, which is worse than leaving the job alone.
"""

from datetime import datetime, timedelta, timezone

import pytest

from app.services.application_assistant import manual_submission_reconciler as reconciler


def _iso(offset_minutes: int) -> str:
    return (datetime.now(timezone.utc) + timedelta(minutes=offset_minutes)).isoformat()


def _thread(uid: str, subject: str, minutes_ago: int = -30) -> dict:
    return {"uid": uid, "subject": subject, "fromName": "Greenhouse", "date": _iso(minutes_ago)}


def _job(job_id: str, company: str, status: str = "MANUAL_REVIEW") -> dict:
    return {"id": job_id, "company": company, "status": status, "queuedAt": _iso(-600)}


@pytest.fixture
def harness(monkeypatch):
    """Drive the reconciler over in-memory jobs and a fake inbox."""
    state: dict = {"jobs": [], "threads": [], "saved": []}

    monkeypatch.setattr(reconciler, "list_autopilot_jobs", lambda _db: state["jobs"])
    monkeypatch.setattr(reconciler, "_fetch_confirmations", lambda _limit: state["threads"])
    monkeypatch.setattr(
        reconciler, "save_autopilot_job", lambda _db, job: state["saved"].append(job) or job
    )
    return state


def _run(state):
    return reconciler.reconcile_manual_submissions(db=object())


class TestOneEmailOneJob:
    def test_a_single_email_marks_only_one_job(self, harness):
        harness["jobs"] = [_job("a", "Robinhood"), _job("b", "Robinhood"), _job("c", "Robinhood")]
        harness["threads"] = [_thread("1", "Thank you for applying to Robinhood")]

        result = _run(harness)

        assert result["marked"] == 1
        assert sum(1 for j in harness["jobs"] if j["status"] == "SUBMITTED") == 1

    def test_two_emails_mark_two_jobs(self, harness):
        harness["jobs"] = [_job("a", "Robinhood"), _job("b", "Robinhood"), _job("c", "Robinhood")]
        harness["threads"] = [
            _thread("1", "Thank you for applying to Robinhood"),
            _thread("2", "Thank you for applying to Robinhood"),
        ]

        assert _run(harness)["marked"] == 2


class TestWhatCounts:
    def test_a_security_code_email_is_not_a_confirmation(self, harness):
        # Greenhouse sends this *before* the submission completes.
        harness["jobs"] = [_job("a", "Affirm")]
        harness["threads"] = [_thread("1", "Security code for your application to Affirm")]

        assert _run(harness)["marked"] == 0

    def test_a_different_employer_is_ignored(self, harness):
        harness["jobs"] = [_job("a", "Affirm")]
        harness["threads"] = [_thread("1", "Thank you for applying to Verkada")]

        assert _run(harness)["marked"] == 0

    def test_company_name_spelling_differences_still_match(self, harness):
        harness["jobs"] = [_job("a", "Doordashusa")]
        harness["threads"] = [_thread("1", "Thanks for applying to DoorDash USA")]

        assert _run(harness)["marked"] == 1

    def test_an_email_older_than_the_job_proves_nothing(self, harness):
        # A confirmation from a previous application to the same employer.
        job = _job("a", "Verkada")
        job["queuedAt"] = _iso(-10)
        harness["jobs"] = [job]
        harness["threads"] = [_thread("1", "Thank you for applying to Verkada", minutes_ago=-5000)]

        assert _run(harness)["marked"] == 0


class TestWhichJobsAreEligible:
    @pytest.mark.parametrize("status", ["MANUAL_REVIEW", "NEEDS_REVIEW", "FAILED"])
    def test_unfinished_applications_are_reconciled(self, harness, status):
        harness["jobs"] = [_job("a", "Verkada", status=status)]
        harness["threads"] = [_thread("1", "Thank you for applying to Verkada")]

        assert _run(harness)["marked"] == 1

    @pytest.mark.parametrize("status", ["QUEUED", "APPLYING", "SUBMITTED", "INELIGIBLE"])
    def test_other_statuses_are_left_alone(self, harness, status):
        # A queued job is one the automation still intends to try; marking it
        # submitted off a stray email would cancel a real attempt.
        harness["jobs"] = [_job("a", "Verkada", status=status)]
        harness["threads"] = [_thread("1", "Thank you for applying to Verkada")]

        assert _run(harness)["marked"] == 0


def test_a_marked_job_records_how_it_was_confirmed(harness):
    harness["jobs"] = [_job("a", "6Sense")]
    harness["threads"] = [_thread("1", "Thank you for applying to 6sense")]

    _run(harness)
    job = harness["jobs"][0]

    assert job["status"] == "SUBMITTED"
    assert job["submissionSource"] == "email-detected"
    assert job["previousStatus"] == "MANUAL_REVIEW"
    assert job["submissionEvidence"]["confirmationSource"] == "gmail"


def test_an_unreadable_inbox_changes_nothing(harness, monkeypatch):
    harness["jobs"] = [_job("a", "Verkada")]

    def _boom(_limit):
        raise RuntimeError("IMAP login failed")

    monkeypatch.setattr(reconciler, "_fetch_confirmations", _boom)
    result = _run(harness)

    assert result["success"] is False
    assert result["marked"] == 0
    assert harness["jobs"][0]["status"] == "MANUAL_REVIEW"


class TestOneEmailOneJobAcrossRuns:
    """The guard has to survive the end of a call, not just the end of a loop.

    The `consumed` set was a local, so every fresh run started empty and the
    same email was free to mark the next open job at that employer. Observed
    live over twelve hours: one "Thank you for applying to Coinbase" marked
    fifteen Coinbase jobs, one ServiceNow email marked twelve — and eleven of
    the ServiceNow jobs had been explicitly skipped as a hand-application
    target, so they were never sent at all.
    """

    def test_the_same_email_is_not_respent_on_a_later_run(self, harness):
        harness["jobs"] = [_job("a", "Coinbase"), _job("b", "Coinbase"), _job("c", "Coinbase")]
        harness["threads"] = [_thread("1", "Thank you for applying to Coinbase")]

        assert _run(harness)["marked"] == 1
        assert _run(harness)["marked"] == 0
        assert _run(harness)["marked"] == 0

        assert sum(1 for j in harness["jobs"] if j["status"] == "SUBMITTED") == 1

    def test_the_spent_email_is_recorded_on_the_job(self, harness):
        harness["jobs"] = [_job("a", "Coinbase")]
        harness["threads"] = [_thread("1", "Thank you for applying to Coinbase")]

        _run(harness)

        assert harness["jobs"][0]["submissionEvidence"]["confirmationUid"] == "1"

    def test_a_second_genuine_email_still_marks_a_second_job(self, harness):
        harness["jobs"] = [_job("a", "Coinbase"), _job("b", "Coinbase")]
        harness["threads"] = [_thread("1", "Thank you for applying to Coinbase")]
        assert _run(harness)["marked"] == 1

        harness["threads"].append(_thread("2", "Thank you for applying to Coinbase"))
        assert _run(harness)["marked"] == 1
        assert sum(1 for j in harness["jobs"] if j["status"] == "SUBMITTED") == 2


class TestTitleBearingSubjects:
    """Some subjects name the role, and then the email belongs to one job only."""

    def test_a_named_role_goes_to_that_job_not_a_sibling(self, harness):
        backend = _job("a", "Affirm")
        backend["title"] = "Senior CIAM Software Engineer"
        other = _job("b", "Affirm")
        other["title"] = "Staff Machine Learning Engineer"
        # Listed so the wrong job would be reached first on a company-only match.
        harness["jobs"] = [other, backend]
        harness["threads"] = [
            _thread("1", "We've received your application for Senior CIAM Software Engineer at Affirm")
        ]

        _run(harness)

        assert backend["status"] == "SUBMITTED"
        assert other["status"] == "MANUAL_REVIEW"

    def test_a_company_only_subject_still_matches_something(self, harness):
        job = _job("a", "Affirm")
        job["title"] = "Senior CIAM Software Engineer"
        harness["jobs"] = [job]
        harness["threads"] = [_thread("1", "Thank you for applying to Affirm")]

        assert _run(harness)["marked"] == 1
