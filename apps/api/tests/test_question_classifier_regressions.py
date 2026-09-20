"""Classifier regressions found by running real applications.

Both of these sent otherwise-complete applications to review, and neither was
visible from the error text - the question simply arrived at a resolver that had
nothing to say about it.
"""

from __future__ import annotations

import pytest

from app.services.application_assistant.question_classifier import QuestionType, classify_question


def _t(question: str) -> QuestionType:
    return classify_question(question)


@pytest.mark.parametrize(
    "question",
    [
        # Lyft. "business unit of Lyft" matched a bare word-boundary test on
        # "unit" in the ADDRESS_LINE_2 patterns, so an employment-history
        # question was routed to the address resolver.
        "Have you been employed by Lyft, or any subsidiary, affiliate, or business "
        "unit of Lyft, in the past (whether on a full-time or part-time basis)?",
        # Brex. The compound phrasing with commas between the adverb and the
        # verb fell through every pattern and reached UNKNOWN.
        "Do you currently, or have you previously, worked at Capital One or a "
        "company acquired by Capital One as an employee, contractor or intern?",
        "Have you previously worked at Amazon?",
        "Have you ever been employed by Twitch?",
        "Are you a former employee of this company?",
    ],
)
def test_employment_history_questions_classify_as_company_history(question):
    assert _t(question) == QuestionType.COMPANY_HISTORY


@pytest.mark.parametrize(
    "question",
    [
        "Address Line 2",
        "Street Address 2",
        "Apt, Suite, etc.",
        "Apartment or suite number",
        "Unit #",
        "Street address line 2 (apt, suite)",
        "Suite",
    ],
)
def test_real_address_line_2_labels_still_classify(question):
    """The narrowed patterns must not lose genuine address fields."""
    assert _t(question) == QuestionType.ADDRESS_LINE_2


def test_plain_street_address_is_not_line_2():
    assert _t("Street Address") == QuestionType.ADDRESS


def test_unit_in_a_non_address_sentence_is_not_an_address():
    """The specific shape of the Lyft bug, stated directly."""
    assert _t("Which business unit would you join?") != QuestionType.ADDRESS_LINE_2
    assert _t("Have you worked for any business unit of Stripe?") == QuestionType.COMPANY_HISTORY


def test_previously_applied_is_not_treated_as_employment():
    """'Applied to' is not employment history.

    The profile records no application history, so there is no honest answer -
    this must not be quietly answered as though it were a "did you work here"
    question.
    """
    assert _t("Have you previously applied to Amazon or any Amazon subsidiary?") != QuestionType.COMPANY_HISTORY


# The fixes below came from bucketing ~1,200 live NEEDS_REVIEW/STAGED jobs by
# their "DOM Verification mismatch: Required field '<X>' is empty" reason:
# each of these labels was resolved to the wrong QuestionType (or none at
# all), so the field was either filled with an answer that could never match
# whatever control the field really was, or never attempted.


def test_academic_self_rating_is_not_a_school_name_request():
    """"...at high school" contains "school" but wants a subjective rating.

    No resolver can answer this honestly without fabricating a claim, so it
    must fall to UNKNOWN (the normal LLM/manual-review path) rather than be
    answered with the candidate's actual school name.
    """
    assert _t("How did you perform in mathematics at high school?") == QuestionType.UNKNOWN
    assert _t("How did you perform in your native language at high school?") == QuestionType.UNKNOWN


def test_name_entry_attestation_is_not_a_name_request():
    """"Have you added your...name" asks whether a field was filled in correctly."""
    assert (
        _t("Have you added your full legal name and surname (including any middle names)?")
        == QuestionType.ACCURACY_CONFIRMATION
    )


@pytest.mark.parametrize(
    "question",
    [
        "Are you authorized to lawfully work in the country where this role is located?",
        "Are you legally authorized to work in the country where this role is based?",
    ],
)
def test_work_authorization_with_adverb_is_not_country(question):
    """An adverb between "to" and "work" must not fall through to COUNTRY."""
    assert _t(question) == QuestionType.WORK_AUTHORIZED


def test_where_are_you_based_is_location_not_unknown():
    assert _t("Where are you currently based?") == QuestionType.LOCATION


def test_highest_level_of_completed_education_is_degree():
    assert _t("What is your highest level of completed education?") == QuestionType.DEGREE


def test_available_to_begin_work_is_notice_period():
    assert _t("When are you available to begin work at Encora?") == QuestionType.NOTICE_PERIOD


@pytest.mark.parametrize(
    "question",
    [
        "Please email me about future job openings",
        "Email me about other job openings within the Booking Holdings entities and recruitment-related communications",
    ],
)
def test_marketing_opt_in_is_not_an_email_address_request(question):
    """A checkbox to opt into marketing email is not a request for the candidate's address."""
    assert _t(question) == QuestionType.MARKETING_CONSENT


@pytest.mark.parametrize(
    "question",
    [
        # Scale AI's phrasing. Neither writes "government employee" adjacently,
        # so both fell through to UNKNOWN and were answered "NA" -- a non-answer
        # on a compliance question whose factual answer is "No".
        "Are you a current or former civilian or military employee of the United States"
        " Government? (If yes, when/where were you last employed and what was your"
        " highest grade/rank and title?)",
        "Do you have any restrictions on post-government employment?"
        " (If yes, please describe.)",
        "Have you been involved in procurement or contract award activities as a"
        " government employee?",
    ],
)
def test_government_employment_questions_are_conflict_checks(question):
    assert _t(question) == QuestionType.GOVERNMENT_CONFLICT


@pytest.mark.parametrize(
    "question",
    [
        "Are you legally authorized to work in the United States?",
        "Will you now or in the future require sponsorship for employment visa status?",
    ],
)
def test_widened_government_patterns_do_not_swallow_work_authorization(question):
    """The government-conflict patterns mention "United States" and "employment",
    which the work-authorization and sponsorship questions also do."""
    assert _t(question) != QuestionType.GOVERNMENT_CONFLICT
