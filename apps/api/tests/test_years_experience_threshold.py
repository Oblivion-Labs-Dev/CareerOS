"""A years-of-experience Yes/No must answer the threshold that was asked.

Live Reddit posting: "Do you have fewer than five years of experience
architecting and scaling distributed backend systems?" was answered "Yes" for a
nine-year engineer — untrue, and a screening knockout on a real application.
The resolver answered "Yes" to every YEARS_EXPERIENCE boolean regardless of the
number in the question or which direction it pointed.
"""

import pytest

from app.services.application_assistant.profile_answer_resolver import resolve_answer

NINE_YEARS = {"yearsExperience": "9"}
YES_NO = ["Yes", "No"]


def answer(question: str) -> str | None:
    return resolve_answer(question, NINE_YEARS, options=YES_NO).answer


@pytest.mark.parametrize(
    ("question", "expected"),
    [
        ("Do you have fewer than five years of experience architecting backend systems?", "No"),
        ("Do you have less than 3 years of experience with Python?", "No"),
        ("Do you have at most 5 years of professional experience?", "No"),
        ("Do you have at least 5 years of experience with backend systems?", "Yes"),
        ("Do you have 8+ years of experience in software engineering?", "Yes"),
        ("Do you have more than 2 years of experience?", "Yes"),
        ("Do you have at least 12 years of experience?", "No"),
        ("Do you have at least ten years of experience?", "No"),
    ],
)
def test_threshold_direction_is_answered_truthfully(question, expected):
    assert answer(question) == expected


def test_early_career_is_still_no():
    assert answer("Are you in your early career?") == "No"


def test_a_non_experience_question_with_a_number_is_not_hijacked():
    # The threshold rule only claims questions that are actually about years of
    # experience — a sponsorship question mentioning a duration is not one.
    profile = {**NINE_YEARS, "sponsorship": "No", "requiresSponsorship": "No"}
    result = resolve_answer(
        "Will you now or in the future require visa sponsorship?", profile, options=YES_NO,
    )
    assert result.answer == "No"


def test_a_years_boolean_without_a_threshold_still_answers():
    # No number to compare against, so the existing "has experience" rule stands
    # rather than the field being dropped.
    assert answer("Do you have several years of experience?") == "Yes"
