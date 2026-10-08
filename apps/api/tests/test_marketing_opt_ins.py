"""Marketing and SMS opt-ins stay unticked; application consents are given.

HPE's form was submitted with "receive SMS messages" and "receive email
communications" ticked alongside the required privacy consents. The owner's
rule is no marketing opt-ins. A transactional-email consent about the
application itself (Regions, required) is not marketing.
"""

from __future__ import annotations

import pytest

from app.services.application_assistant.profile_answer_resolver import resolve_answer
from app.services.application_assistant.question_classifier import QuestionType, classify_question

PROFILE = {"email": "candidate@example.com", "smsConsent": "No", "marketingConsent": "No"}


@pytest.mark.parametrize(
    "label",
    [
        "I consent to receive email communications about future opportunities and events",
        "I would like to be part of the Autodesk, Inc. Talent Community, and receive information about job opportunities",
        "Sign me up for job alerts",
        "I agree to receive marketing communications from Acme",
    ],
)
def test_marketing_opt_ins_are_classified_and_declined(label):
    assert classify_question(label) == QuestionType.MARKETING_CONSENT
    assert resolve_answer(label, PROFILE, options=["Yes", "No"]).answer == "No"


def test_sms_opt_in_is_declined():
    label = "I consent to receive SMS messages from HPE regarding my application"
    assert resolve_answer(label, PROFILE, options=["Yes", "No"]).answer == "No"


def test_transactional_application_email_consent_is_given():
    label = ("By checking this box, I consent to receive transactional email messages "
             "regarding employment opportunities at Regions.")
    assert classify_question(label) == QuestionType.PRIVACY_CONSENT


def test_email_address_fields_still_get_the_address():
    for label in ("Email", "Email Address*", "Confirm Email"):
        assert classify_question(label) == QuestionType.EMAIL
