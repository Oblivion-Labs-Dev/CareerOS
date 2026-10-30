"""Current-employer questions, and questions that only mention an organization.

Found on the 2026-10-30 night loop, Klaviyo (submitted):
- "Klaviyo is an AI-forward organization. Tell us a bit more about how you use AI
  in your work" was filled with "Microsoft": the bare ``organi[sz]ation``
  pattern made any sentence containing the word a CURRENT_COMPANY question.
- "What company are you currently employed at or have worked at most recently?"
  was answered "No": "are you currently employed at" matched the Yes/No
  COMPANY_HISTORY rule first.
"""

import pytest

from app.services.application_assistant.question_classifier import QuestionType, classify_question

CURRENT_EMPLOYER = [
    "What company are you currently employed at or have worked at most recently?",
    "What company are you currently working for?",
    "Organization",
    "Organisation name",
    "Current Organization",
    "Name of your current organization",
]

NOT_CURRENT_EMPLOYER = [
    "Klaviyo is an AI-forward organization. Tell us a bit more about how you use AI in your work",
    "Do you have any relatives employed by this organization?",
    "Have you previously worked for this organization? Yes or No",
    "Do you have experience working in an early stage organization with a healthcare focus?",
    "Are you currently employed by an entity within our broader organization? (e.g., ERGO, MR, or a subsidiary).",
]


@pytest.mark.parametrize("question", CURRENT_EMPLOYER)
def test_current_employer_questions(question):
    assert classify_question(question, "", None) == QuestionType.CURRENT_COMPANY


@pytest.mark.parametrize("question", NOT_CURRENT_EMPLOYER)
def test_mentioning_an_organization_is_not_a_current_employer_question(question):
    assert classify_question(question, "", None) != QuestionType.CURRENT_COMPANY
