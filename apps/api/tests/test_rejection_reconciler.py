"""One-rejection-email-one-job guarantee for the Gmail rejection reconciler.

Mirrors test_manual_submission_reconciler.py's own rule: a rejection email
that names only the employer must never mark more than one SUBMITTED job
REJECTED, and the same email must never be re-spent on a later run.
"""

from datetime import datetime, timedelta, timezone

import pytest

from app.services.application_assistant import rejection_reconciler as reconciler


def _iso(offset_minutes: int) -> str:
    return (datetime.now(timezone.utc) + timedelta(minutes=offset_minutes)).isoformat()


def _thread(uid: str, subject: str, snippet: str = "", minutes_ago: int = -30) -> dict:
    return {"uid": uid, "subject": subject, "snippet": snippet, "fromName": "Greenhouse", "date": _iso(minutes_ago)}


def _job(job_id: str, company: str, title: str = "Software Engineer", status: str = "SUBMITTED", submitted_minutes_ago: int = -600) -> dict:
    return {"id": job_id, "company": company, "title": title, "status": status, "submittedAt": _iso(submitted_minutes_ago)}


REJECTION_SUBJECT = "Update on your application to {company}"
REJECTION_SNIPPET = "Thank you for your interest. Unfortunately, we have decided not to move forward with your application at this time."


@pytest.fixture
def harness(monkeypatch):
    state: dict = {"jobs": [], "threads": [], "saved": []}
    monkeypatch.setattr(reconciler, "list_autopilot_jobs", lambda _db: state["jobs"])
    monkeypatch.setattr(reconciler, "_fetch_rejection_threads", lambda _limit, _window_days: state["threads"])
    monkeypatch.setattr(
        reconciler, "save_autopilot_job", lambda _db, job: state["saved"].append(job) or job
    )
    return state


def _run(state):
    return reconciler.reconcile_rejections(db=object())


class TestOneEmailOneJob:
    def test_a_single_rejection_marks_only_one_job(self, harness):
        harness["jobs"] = [_job("a", "Robinhood"), _job("b", "Robinhood"), _job("c", "Robinhood")]
        harness["threads"] = [_thread("1", REJECTION_SUBJECT.format(company="Robinhood"), REJECTION_SNIPPET)]

        result = _run(harness)

        # Ambiguous (3 open SUBMITTED jobs, no title named) -> nothing marked,
        # never guessed.
        assert result["marked"] == 0
        assert all(j["status"] == "SUBMITTED" for j in harness["jobs"])

    def test_company_alone_with_no_title_named_is_never_matched(self, harness):
        # There is no company-only fallback: two false-positive mechanisms
        # turned up in it during validation (2026-09-16 — a despacing bug,
        # then a real company name coincidentally named in an unrelated
        # sign-off), so even an unambiguous single-company match is left
        # alone unless the email also names the specific role.
        harness["jobs"] = [_job("a", "Robinhood"), _job("b", "Coinbase")]
        harness["threads"] = [_thread("1", REJECTION_SUBJECT.format(company="Robinhood"), REJECTION_SNIPPET)]

        result = _run(harness)

        assert result["marked"] == 0
        assert harness["jobs"][0]["status"] == "SUBMITTED"

    def test_company_plus_named_title_marks_the_one_open_job(self, harness):
        harness["jobs"] = [_job("a", "Robinhood", title="Senior Backend Engineer"), _job("b", "Coinbase")]
        snippet = REJECTION_SNIPPET + " for the Senior Backend Engineer role"
        harness["threads"] = [_thread("1", REJECTION_SUBJECT.format(company="Robinhood"), snippet)]

        result = _run(harness)

        assert result["marked"] == 1
        assert harness["jobs"][0]["status"] == "REJECTED"
        assert harness["jobs"][1]["status"] == "SUBMITTED"

    def test_title_named_in_body_disambiguates_multiple_open_jobs(self, harness):
        harness["jobs"] = [
            _job("a", "Robinhood", title="Senior Backend Engineer"),
            _job("b", "Robinhood", title="Staff Frontend Engineer"),
        ]
        snippet = REJECTION_SNIPPET + " for the Senior Backend Engineer role"
        harness["threads"] = [_thread("1", REJECTION_SUBJECT.format(company="Robinhood"), snippet)]

        result = _run(harness)

        assert result["marked"] == 1
        assert harness["jobs"][0]["status"] == "REJECTED"
        assert harness["jobs"][1]["status"] == "SUBMITTED"

    def test_only_submitted_jobs_are_candidates(self, harness):
        harness["jobs"] = [_job("a", "Robinhood", status="NEEDS_REVIEW")]
        harness["threads"] = [_thread("1", REJECTION_SUBJECT.format(company="Robinhood"), REJECTION_SNIPPET)]

        assert _run(harness)["marked"] == 0
        assert harness["jobs"][0]["status"] == "NEEDS_REVIEW"

    def test_rejection_before_submission_is_ignored(self, harness):
        # A rejection dated before this job's own submittedAt cannot be about it.
        harness["jobs"] = [_job("a", "Robinhood", submitted_minutes_ago=-5)]
        harness["threads"] = [_thread("1", REJECTION_SUBJECT.format(company="Robinhood"), REJECTION_SNIPPET, minutes_ago=-30)]

        assert _run(harness)["marked"] == 0

    def test_confirmation_only_wording_is_not_in_the_rejection_phrase_list(self):
        # `reconcile_rejections` no longer re-classifies fetched threads — it
        # trusts `_fetch_rejection_threads`'s own IMAP search (see that
        # function's docstring for why: re-checking against a truncated
        # snippet risked missing the very phrase that got the email fetched).
        # So a confirmation email never reaching `reconcile_rejections` in the
        # first place depends on these phrases never matching one — this
        # guards that property directly instead of through a mocked fetch
        # that bypasses the real search entirely.
        phrases = reconciler._rejection_phrases()
        assert phrases, "rejection phrase list must not be empty"
        confirmation_wording = "thank you for applying we've received your application"
        assert not any(p in confirmation_wording for p in phrases)


class TestCompanyNameCannotCrossWordBoundaries:
    """Regression for a real production incident (2026-09-16): the company
    substring check despaced the whole haystack before comparing, so "Oura"
    matched inside despaced "...our application..." -> "...ourapplication...".
    A genuine Samsara rejection got credited to a completely unrelated,
    never-rejected Oura application this way. 118 jobs were wrongly marked
    REJECTED in one run before this was caught and reverted.
    """

    def test_short_company_name_does_not_match_across_word_boundaries(self, harness):
        harness["jobs"] = [_job("a", "Oura"), _job("b", "Samsara")]
        # No literal "Oura" anywhere, but despacing "our application" produces
        # the substring "ouraapplication" containing "oura".
        snippet = REJECTION_SNIPPET + " Thank you for your application to Samsara."
        harness["threads"] = [_thread("1", "Thank you for your interest in Samsara", snippet)]

        result = _run(harness)

        assert harness["jobs"][0]["status"] == "SUBMITTED"  # Oura must not be touched
        # Two SUBMITTED Samsara candidates would make this ambiguous anyway,
        # but the key assertion is that Oura was never a candidate at all.
        assert all(j["company"] != "Oura" or j["status"] == "SUBMITTED" for j in harness["jobs"])

    def test_company_name_far_from_the_actual_rejection_is_not_matched(self, harness):
        # Real false positive (2026-09-16): a genuine MISUMI rejection's
        # sign-off read "wish you all the best with your future endeavors" —
        # "Future" is a real, long-enough (6 char) tracked company name that
        # coincidentally appears hundreds of characters away from the actual
        # "unfortunately, we have decided not to move forward" sentence.
        harness["jobs"] = [_job("a", "Future")]
        far_away_padding = "word " * 100
        snippet = (
            "thank you for your interest. unfortunately, we have decided not to move forward at this time. "
            + far_away_padding
            + "we wish you all the best with your future endeavors."
        )
        harness["threads"] = [_thread("1", "Regarding your application", snippet)]

        assert _run(harness)["marked"] == 0
        assert harness["jobs"][0]["status"] == "SUBMITTED"

    def test_common_english_word_company_name_is_not_matched_on_company_pass_alone(self, harness):
        # "Nice" is a real employer in this dataset and an ordinary English
        # word — must not be marked from company-only matching without the
        # role also being named.
        harness["jobs"] = [_job("a", "Nice")]
        snippet = REJECTION_SNIPPET + " It was nice of you to apply."
        harness["threads"] = [_thread("1", "Update on your application", snippet)]

        assert _run(harness)["marked"] == 0
        assert harness["jobs"][0]["status"] == "SUBMITTED"


class TestConditionalBoilerplateIsNotARejection:
    """Regression for a real production incident (2026-09-16): a plain
    Honeycomb "thank you for applying" confirmation contains the sentence
    "if you are not selected for this position, continue to keep an eye on
    our careers page" — a literal, contiguous match for the "not selected"
    rejection phrase, but conditional boilerplate, not an actual decision.
    96 ordinary confirmations matched this way after the word-boundary and
    bag-of-words fixes alone.
    """

    def test_conditional_not_selected_is_not_genuine(self):
        text = (
            "thank you for applying. our team will review your application. "
            "if you are not selected for this position, continue to keep an eye "
            "on our careers page as we're growing."
        )
        assert reconciler._has_genuine_rejection_wording(text) is False

    def test_declarative_not_selected_is_genuine(self):
        text = "after careful review, we regret to inform you that you were not selected for this role."
        assert reconciler._has_genuine_rejection_wording(text) is True

    def test_unfortunately_alone_with_no_decision_context_is_not_genuine(self):
        # Real false positive (2026-09-16): a plain Vonage "Application
        # Received" confirmation's unattended-mailbox disclaimer said
        # "replies will unfortunately not be read" — "unfortunately" present,
        # no rejection determination anywhere near it.
        text = (
            "please note: do not reply to this email. this email is sent from an "
            "unattended mailbox. replies will unfortunately not be read. "
            "hi akshay, thank you for your interest in java software engineer."
        )
        assert reconciler._has_genuine_rejection_wording(text) is False

    def test_unfortunately_with_nearby_decision_wording_is_genuine(self):
        text = "thank you for your interest. unfortunately, we have decided to move forward with other candidates."
        assert reconciler._has_genuine_rejection_wording(text) is True

    def test_declarative_rejection_elsewhere_in_a_longer_email_is_still_genuine(self):
        # A real rejection can still contain an unrelated "if you have
        # questions" sentence later — only the specific occurrence next to a
        # conditional marker should be discounted, not the whole email.
        text = (
            "after careful review we have decided not to proceed with your application at this time. "
            "if you have any questions, feel free to reach out."
        )
        assert reconciler._has_genuine_rejection_wording(text) is True


class TestNotRespentAcrossRuns:
    def test_the_same_rejection_email_is_not_respent(self, harness):
        harness["jobs"] = [_job("a", "Coinbase", title="Senior Backend Engineer")]
        snippet = REJECTION_SNIPPET + " for the Senior Backend Engineer role"
        harness["threads"] = [_thread("1", REJECTION_SUBJECT.format(company="Coinbase"), snippet)]

        first = _run(harness)
        assert first["marked"] == 1
        assert harness["jobs"][0]["status"] == "REJECTED"

        # A second run sees the same email uid, but the job is no longer a
        # SUBMITTED candidate at all now — either way it must not re-fire.
        second = _run(harness)
        assert second["marked"] == 0

    def test_a_second_genuine_rejection_still_marks_a_second_job(self, harness):
        harness["jobs"] = [
            _job("a", "Coinbase", title="Senior Backend Engineer"),
            _job("b", "Affirm", title="Staff Payments Engineer"),
        ]
        snippet_a = REJECTION_SNIPPET + " for the Senior Backend Engineer role"
        harness["threads"] = [_thread("1", REJECTION_SUBJECT.format(company="Coinbase"), snippet_a)]
        first = _run(harness)
        assert first["marked"] == 1

        snippet_b = REJECTION_SNIPPET + " for the Staff Payments Engineer role"
        harness["threads"] = [_thread("2", REJECTION_SUBJECT.format(company="Affirm"), snippet_b)]
        second = _run(harness)
        assert second["marked"] == 1
        assert harness["jobs"][1]["status"] == "REJECTED"
