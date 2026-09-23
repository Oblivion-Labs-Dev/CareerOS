"""Do not re-apply to a posting that already has a submitted application.

An ATS silently refuses the second attempt — the form just stays on screen —
which the executor reports as "submit button is still active" only after a full
browser run. Observed live on Affirm: a posting applied to two days earlier was
retried, failed opaquely, and burned an attempt.
"""

from app.services.application_assistant.ineligibility import find_duplicate_submission

JOB = {
    "id": "apjob_new",
    "company": "Affirm",
    "title": "Senior Software Engineer, Affirm Bank",
    "applicationUrl": "https://job-boards.greenhouse.io/affirm/jobs/7812982003",
}


def test_matches_on_application_url():
    prior = [{"id": "apjob_old", "company": "Affirm", "title": "Something Else Entirely",
              "applicationUrl": "https://job-boards.greenhouse.io/affirm/jobs/7812982003/"}]
    assert find_duplicate_submission(JOB, prior)["id"] == "apjob_old"


def test_matches_on_company_and_title_when_the_url_is_missing():
    # The real case: the earlier row predates URL capture and stores None, so a
    # URL-only check finds nothing.
    prior = [{"id": "apjob_old", "company": "Affirm",
              "title": "Senior Software Engineer, Affirm Bank", "applicationUrl": None}]
    assert find_duplicate_submission(JOB, prior)["id"] == "apjob_old"


def test_ignores_a_different_posting_at_the_same_company():
    prior = [{"id": "apjob_old", "company": "Affirm", "title": "Senior Software Engineer, Card Ledger",
              "applicationUrl": "https://job-boards.greenhouse.io/affirm/jobs/9999999"}]
    assert find_duplicate_submission(JOB, prior) is None


def test_ignores_itself():
    assert find_duplicate_submission(JOB, [JOB]) is None


def test_no_prior_submissions_is_not_a_duplicate():
    assert find_duplicate_submission(JOB, []) is None


def test_matching_is_case_and_whitespace_insensitive():
    prior = [{"id": "apjob_old", "company": "  affirm ",
              "title": "SENIOR SOFTWARE ENGINEER, AFFIRM BANK ", "applicationUrl": None}]
    assert find_duplicate_submission(JOB, prior)["id"] == "apjob_old"


def test_captcha_blocked_boards_go_to_manual_review_not_a_terminal_bucket():
    """A CAPTCHA board is not a dead end — the candidate can submit it by hand.

    The challenge exists precisely to stop automation and must never be
    defeated, but the posting is live and worth applying to. So it belongs in
    MANUAL_REVIEW: visible as a real opportunity, out of the answer-a-question
    review list, and never retried by the runner.
    """
    from app.services.application_assistant.domain import AutopilotJobStatus
    from app.services.application_assistant.ineligibility import (
        MANUAL_REASONS,
        TERMINAL_REASONS,
        IneligibilityReason,
        apply_ineligibility,
        classify_ineligibility,
    )

    assert IneligibilityReason.BOT_PROTECTED_BOARD in MANUAL_REASONS
    assert IneligibilityReason.BOT_PROTECTED_BOARD not in TERMINAL_REASONS

    job = {"id": "apjob_x", "lastError": "Cloudflare Turnstile on careers.roblox.com"}
    classified = classify_ineligibility(job)
    assert classified is not None
    reason, detail = classified
    assert reason is IneligibilityReason.BOT_PROTECTED_BOARD

    apply_ineligibility(job, reason, detail)
    assert job["status"] == AutopilotJobStatus.MANUAL_REVIEW.value
    # Still never retried: no number of attempts gets past a CAPTCHA.
    assert job["hasPersistentBlock"] is True


def test_an_expired_posting_is_still_terminal():
    """The manual bucket must not swallow genuine dead ends."""
    from app.services.application_assistant.domain import AutopilotJobStatus
    from app.services.application_assistant.ineligibility import (
        IneligibilityReason,
        apply_ineligibility,
    )

    job = {"id": "apjob_y"}
    apply_ineligibility(job, IneligibilityReason.POSTING_EXPIRED, "Posting removed")
    # Still terminal: a dead end is FAILED now, which nothing retries.
    assert job["status"] == AutopilotJobStatus.FAILED.value
    assert job["hasPersistentBlock"] is True


def test_recaptcha_wording_also_classifies_as_bot_protected():
    from app.services.application_assistant.ineligibility import (
        IneligibilityReason,
        classify_ineligibility,
    )

    job = {"id": "apjob_y", "lastError": "reCAPTCHA bot protection on this board blocked the submission"}
    reason, _ = classify_ineligibility(job)
    assert reason is IneligibilityReason.BOT_PROTECTED_BOARD
