"""A saved "never worked there" answer must not deny the candidate's real employers.

Observed on the live profile (2026-10-13): the saved Robinhood answer
"Have you ever worked for Robinhood as an employee, intern or contractor? -> No"
matches by the pattern ``ever\\s+worked\\s+for``, so the same question about
Amazon - where the candidate spent years - resolved to "No". A fuzzy-matched
answer-library entry ("I am a current employee" -> "No") did the same for
"Are you a current or former Amazon employee?". Work history on the profile is
the fact; saved answers about other employers are not.
"""

import pytest

from app.services.application_assistant.profile_answer_resolver import resolve_answer

YES_NO = ["Yes", "No"]

PROFILE = {
    "firstName": "Sam",
    "lastName": "Rivera",
    "currentCompany": "Microsoft",
    "workExperience": [
        {"company": "Microsoft", "title": "Senior Software Engineer", "currentlyEmployed": True},
        {"company": "Amazon", "title": "Software Development Engineer"},
    ],
    "screeningAnswers": [
        {
            "id": "company_history_robinhood",
            "question": "Have you ever worked for Robinhood as an employee, intern or contractor?",
            "answer": "No",
            "matchPatterns": [r"ever\s+worked\s+for"],
        },
        {
            "id": "relatives",
            "question": "Are you related to anyone who works here?",
            "answer": "No",
            "matchPatterns": [r"related\s+to"],
        },
    ],
}

ANSWER_LIB = [
    {
        "id": "lib_current_employee",
        "normalizedKey": "i am a current employee",
        "questionVariants": ["I am a current employee"],
        "value": "No",
        "verificationStatus": "verified",
    }
]


@pytest.mark.parametrize(
    "question",
    [
        "Have you ever worked for Amazon as an employee, intern or contractor?",
        # Twitch is an Amazon subsidiary; its forms ask about the parent.
        "Have you ever worked for Twitch or Amazon as an employee, intern or contractor?",
        "Have you ever worked for Microsoft as an employee, intern or contractor?",
    ],
)
def test_saved_answer_about_another_company_does_not_deny_real_employer(question):
    res = resolve_answer(question, PROFILE, YES_NO, answer_lib=ANSWER_LIB)
    assert res.answer == "Yes"


def test_fuzzy_library_answer_does_not_deny_real_employer():
    res = resolve_answer("Are you a current or former Amazon employee?", PROFILE, YES_NO, answer_lib=ANSWER_LIB)
    assert res.answer == "Yes"


def test_saved_answer_still_applies_to_companies_never_worked_for():
    res = resolve_answer(
        "Have you ever worked for Stripe as an employee, intern or contractor?", PROFILE, YES_NO, answer_lib=ANSWER_LIB
    )
    assert res.answer == "No"


def test_relative_question_naming_a_prior_employer_keeps_saved_answer():
    res = resolve_answer("Are you related to anyone who works at Amazon?", PROFILE, YES_NO, answer_lib=ANSWER_LIB)
    assert res.answer == "No"
