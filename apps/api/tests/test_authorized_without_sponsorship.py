""""Authorized to work without sponsorship?" is No for a candidate on H-1B.

Found live on the 2026-10-30 night loop: a Greenhouse form asked "Are you
authorized to work in the United States without Visa Sponsorship or EAD?" and
Autopilot submitted "Yes". The question classified as plain WORK_AUTHORIZED, and
the saved "Are you legally authorized to work in the United States? -> Yes"
answer (pattern ``authorized\s+to\s+work``) matched it before any rule could
notice the "without sponsorship" condition. The wordings below are from real
forms in the database.
"""

import pytest

from app.services.application_assistant.profile_answer_resolver import resolve_answer

PROFILE = {
    "country": "United States",
    "citizenshipCountry": "India",
    "authorizedToWorkInUS": True,
    "requiresSponsorship": "Yes",
    "workAuth": {
        "authorizedToWorkInUS": True,
        "requiresSponsorshipNowOrFuture": True,
        "authorizationType": "H-1B",
        "permanentWorkAuthorization": False,
    },
    "screeningAnswers": [
        {
            "id": "work_auth_us",
            "question": "Are you legally authorized to work in the United States?",
            "answer": "Yes",
            "matchPatterns": [r"authorized\s+to\s+work", r"eligible\s+to.*work"],
        },
    ],
}

WITHOUT_SPONSORSHIP = [
    "Are you authorized to work in the United States without Visa Sponsorship or EAD?",
    "Are you authorized to work in the United States without sponsorship now or in the future?",
    "Are you legally authorized to work in the United States without visa sponsorship, now or in the future?",
    "Are you currently authorized to work in the United States without requiring visa sponsorship, now or in the future?",
    "This position is not eligible for Visa Sponsorship. Applicants must be authorized to work in the "
    "United States without the need for Visa Sponsorship by the start date of employment. By selecting "
    '"Yes," you confirm that you do not require Visa Sponsorship.',
]


@pytest.mark.parametrize("question", WITHOUT_SPONSORSHIP)
def test_authorized_without_sponsorship_is_no_on_h1b(question):
    assert resolve_answer(question, PROFILE, options=["Yes", "No"]).answer == "No"


def test_plain_authorization_question_still_yes():
    res = resolve_answer("Are you legally authorized to work in the United States?", PROFILE, options=["Yes", "No"])
    assert res.answer == "Yes"
