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
