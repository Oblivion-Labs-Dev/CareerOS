""""Can you present documentation of your legal right to live and work here?"

Glidewell's form (2026-10-30 night loop) asked this as a required Yes/No. It
classified as UNKNOWN, so the field stayed blank. It is a work-authorization
question: a candidate authorized to work in the US (here on H-1B) can present
that documentation.
"""

from app.services.application_assistant.profile_answer_resolver import resolve_answer
from app.services.application_assistant.question_classifier import QuestionType, classify_question

Q = "If hired, can you present documentation of your legal right to live and work in this country?"
PROFILE = {"authorizedToWorkInUS": True, "workAuth": {"authorizedToWorkInUS": True, "requiresSponsorshipNowOrFuture": True}}


def test_documentation_of_legal_right_to_work_is_work_authorization():
    assert classify_question(Q, "", ["Yes", "No"]) == QuestionType.WORK_AUTHORIZED


def test_documentation_of_legal_right_to_work_is_yes_when_authorized():
    assert resolve_answer(Q, PROFILE, options=["Select an option...", "Yes", "No"]).answer == "Yes"
