"""After the submit click, only proof counts.

* A success-looking URL on an arbitrary site is not a verified submission;
  only an ATS's own confirmation address, or the page saying so, is.
* A validation error after the click permits another submission only when the
  same form is still on screen flagging fields. Otherwise the job may be at the
  employer already and no requeue path may send it again.
* Development and test runs never click submit on a real employer's form.
"""

from __future__ import annotations

import asyncio

import pytest

from app.db.store import now_iso, session_scope
from app.services.application_assistant.domain import AutopilotJobStatus
from app.services.application_assistant.persistence import (
    delete_autopilot_job,
    get_autopilot_job,
    save_autopilot_job,
)
from app.services.application_assistant.qwen_form_reviewer import verify_submission_confirmation
from app.services.application_assistant.submission_guard import live_submission_refusal
from app.services.application_assistant.submission_outcome import (
    post_click_rejection_is_conclusive,
    requeue_refusal_reason,
)
from app.services.application_assistant.submission_watcher import is_submission_confirmation_url

FORM = "https://job-boards.greenhouse.io/acme/jobs/4455661"


def _verdict(url: str, body: str = "") -> bool:
    return asyncio.run(verify_submission_confirmation(body, url, [], "Acme", "Engineer"))["submissionConfirmed"]


# ── Confirmation ───────────────────────────────────────────────────────────


@pytest.mark.parametrize("url", [
    "https://careers.acme.example/applied",
    "https://careers.acme.example/jobs/12/success",
    "https://careers.acme.example/thanks",
    "https://careers.acme.example/apply?submitted=true",
    "https://ats.example/job/confirmation",
])
def test_a_success_looking_url_alone_is_not_a_verified_submission(url):
    assert _verdict(url) is False


def test_the_same_url_with_the_page_saying_so_is_verified():
    assert _verdict("https://careers.acme.example/applied", "Thank you for applying!") is True


@pytest.mark.parametrize("url", [
    "https://job-boards.greenhouse.io/acme/jobs/4455661/confirmation",
    "https://job-boards.greenhouse.io/embed/job_app/confirmation?for=acme&token=1",
    "https://jobs.ebayinc.com/us/en/applythankyou?status=success&jobseqno=X",
])
def test_known_ats_confirmation_addresses_still_verify_on_their_own(url):
    # 752 of the 765 historical submissions were confirmed exactly this way,
    # every one of them later backed by the employer's email.
    assert _verdict(url) is True


def test_the_review_browser_ignores_confirmation_wording_outside_the_path():
    assert not is_submission_confirmation_url("https://jobs.acme.example/apply?utm_source=confirmation-email")
    assert is_submission_confirmation_url("https://careers.example.com/thank-you-for-applying")


# ── Post-click validation errors ───────────────────────────────────────────


def _conclusive(**overrides) -> bool:
    facts = dict(
        pre_click_url=FORM,
        post_click_url=FORM + "/",
        active_errors=["This field is required."],
        form_still_visible=True,
        submit_button_visible=True,
    )
    facts.update(overrides)
    return post_click_rejection_is_conclusive(**facts)


def test_same_form_flagging_fields_proves_the_employer_sent_it_back():
    assert _conclusive() is True


@pytest.mark.parametrize("overrides", [
    {"post_click_url": FORM + "/step-2"},
    {"post_click_url": "https://acme.example/careers"},
    {"form_still_visible": False},
    {"submit_button_visible": False},
    {"active_errors": []},
    {"pre_click_url": ""},
])
def test_anything_less_is_not_proof(overrides):
    assert _conclusive(**overrides) is False


@pytest.fixture
def clicked_review_job():
    job = {
        "id": "apjob_clicked_review",
        "status": AutopilotJobStatus.NEEDS_REVIEW.value,
        "company": "Acme",
        "title": "Platform Engineer",
        "applicationUrl": FORM,
        "submitAttemptedAt": now_iso(),
        "submissionEvidence": {"errorsFound": ["This field is required."]},
        "pendingQuestions": [],
    }
    with session_scope() as db:
        save_autopilot_job(db, dict(job))
    yield job
    with session_scope() as db:
        delete_autopilot_job(db, job["id"])


def test_a_clicked_job_without_proof_of_rejection_is_never_requeued(clicked_review_job):
    from app.routers.application_assistant.autopilot import reprocess_single_autopilot_job

    assert "may already have been submitted" in requeue_refusal_reason(clicked_review_job)
    response = asyncio.run(reprocess_single_autopilot_job(clicked_review_job["id"]))
    assert response["success"] is False
    with session_scope() as db:
        assert get_autopilot_job(db, clicked_review_job["id"])["status"] == "NEEDS_REVIEW"


def test_bulk_requeue_skips_a_clicked_job_without_proof(clicked_review_job):
    from app.routers.application_assistant.autopilot import _requeue_autopilot_jobs_by_status

    _requeue_autopilot_jobs_by_status(("NEEDS_REVIEW",))
    with session_scope() as db:
        assert get_autopilot_job(db, clicked_review_job["id"])["status"] == "NEEDS_REVIEW"


def test_a_proven_rejection_may_be_answered_and_retried(clicked_review_job):
    job = dict(clicked_review_job)
    job["submissionEvidence"] = {**job["submissionEvidence"], "rejectedBeforeAcceptance": True}
    assert requeue_refusal_reason(job) is None
    # And a job never clicked is as retryable as before.
    assert requeue_refusal_reason({"status": "NEEDS_REVIEW"}) is None


# ── Live submission gate ───────────────────────────────────────────────────


def test_a_test_run_never_clicks_submit_on_a_real_employer(monkeypatch):
    monkeypatch.delenv("CAREEROS_LIVE_APPLY", raising=False)
    monkeypatch.delenv("CAREEROS_ENV", raising=False)
    assert "a test run" in live_submission_refusal(FORM)
    # Local fixture pages stay clickable.
    assert live_submission_refusal("http://127.0.0.1:8123/application_form.html") is None


def test_development_env_is_gated_outside_tests_too(monkeypatch):
    monkeypatch.delenv("CAREEROS_LIVE_APPLY", raising=False)
    monkeypatch.delenv("PYTEST_CURRENT_TEST", raising=False)
    monkeypatch.setenv("CAREEROS_ENV", "development")
    assert "CAREEROS_ENV=development" in live_submission_refusal(FORM)
    monkeypatch.setenv("CAREEROS_LIVE_APPLY", "1")
    assert live_submission_refusal(FORM) is None


def test_the_owners_instance_and_production_are_not_gated(monkeypatch):
    monkeypatch.delenv("CAREEROS_LIVE_APPLY", raising=False)
    monkeypatch.delenv("PYTEST_CURRENT_TEST", raising=False)
    monkeypatch.delenv("CAREEROS_ENV", raising=False)
    assert live_submission_refusal(FORM) is None
    monkeypatch.setenv("CAREEROS_ENV", "production")
    assert live_submission_refusal(FORM) is None


def test_the_executor_checks_the_gate_before_the_submit_marker():
    """The refusal must come before on_submit_attempt, or a refused click would
    leave the job looking possibly-submitted and unretryable."""
    import inspect

    from app.services.application_assistant import playwright_autopilot_executor as executor

    source = inspect.getsource(executor)
    gate = source.index("live_submission_refusal(page.url)")
    marker = source.index("await on_submit_attempt()")
    click = source.index("await submit_button.click()")
    assert gate < marker < click
