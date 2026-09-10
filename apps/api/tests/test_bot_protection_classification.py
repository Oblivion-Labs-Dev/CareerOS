"""A board that refuses automation is a manual-review job, not a dead end.

Two regressions are covered here:

* Ashby rejects an automated submission server-side with "flagged as possible
  spam" — no challenge iframe and no "captcha" wording — so the executor's DOM
  sweep for reCAPTCHA/Turnstile/hCaptcha never fires and the job was landing in
  FAILED.
* The DataDome and hCaptcha patterns were written into the source with literal
  backspace bytes instead of ``\\b`` escapes, so they matched nothing at all.
  These assertions fail loudly if that ever happens again.
"""

import re

from app.services.application_assistant.domain import IneligibilityReason
from app.services.application_assistant.ineligibility import _ERROR_TEXT_RULES

ASHBY_SPAM_ERROR = (
    "Page contains active validation errors: We couldn't submit your application\n\n"
    "Your application submission was flagged as possible spam. If you believe this "
    "was a mistake, please submit your application again."
)

SMARTRECRUITERS_DATADOME_ERROR = (
    "Application page did not render — blocked by DataDome bot protection"
)


def _bot_patterns():
    for reason, patterns in _ERROR_TEXT_RULES:
        if reason is IneligibilityReason.BOT_PROTECTED_BOARD:
            return patterns
    raise AssertionError("No BOT_PROTECTED_BOARD rule found")


def _matches(text: str) -> bool:
    return any(re.search(p, text, re.IGNORECASE) for p in _bot_patterns())


class TestBotProtectionPatterns:
    def test_ashby_spam_rejection_is_bot_protection(self):
        assert _matches(ASHBY_SPAM_ERROR)

    def test_datadome_is_detected(self):
        assert _matches(SMARTRECRUITERS_DATADOME_ERROR)

    def test_recaptcha_still_detected(self):
        assert _matches("reCAPTCHA bot protection blocked the submission")

    def test_ordinary_validation_error_is_not_bot_protection(self):
        """A missing required field must stay fixable, not become a dead end."""
        assert not _matches(
            "Page contains active validation errors: Missing entry for "
            "required field: What are your pronouns?"
        )


class TestPatternsAreWellFormed:
    def test_no_literal_control_characters(self):
        """Guards the \\b-as-backspace corruption that silenced two patterns."""
        for pattern in _bot_patterns():
            assert "\x08" not in pattern, f"literal backspace in {pattern!r}"

    def test_every_pattern_compiles(self):
        for pattern in _bot_patterns():
            re.compile(pattern)
