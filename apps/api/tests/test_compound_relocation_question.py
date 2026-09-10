"""A compound "based in X or willing to relocate?" is decided by the relocation clause.

Ramp asks "Are you based in NYC or SF or willing to relocate?". The
LOCATION_CONFIRMATION pattern "are you based in" used to claim it and answer
"No" — true of the location half, false of the question as a whole — even though
the profile records a willingness to relocate. That told the employer the
opposite of the candidate's actual position on a required field.
"""

import pytest

from app.services.application_assistant.profile_answer_resolver import resolve_answer
from app.services.application_assistant.question_classifier import (
    QuestionType,
    classify_question,
)

YES_NO = ["Yes", "No"]

RELOCATION_PROFILE = {
    "city": "Auburn",
    "state": "WA",
    "relocate": "Yes",
    "willingToRelocate": "Yes",
}


class TestCompoundRelocationQuestion:
    @pytest.mark.parametrize("question", [
        "Are you based in NYC or SF or willing to relocate?",
        "Are you located in Austin or willing to relocate there?",
        "Are you willing to relocate, or already based in New York?",
    ])
    def test_compound_question_is_a_relocation_question(self, question):
        assert classify_question(question, YES_NO) is QuestionType.RELOCATE

    def test_compound_question_answers_yes_from_profile(self):
        resolution = resolve_answer(
            question_text="Are you based in NYC or SF or willing to relocate?",
            profile=RELOCATION_PROFILE,
            options=YES_NO,
        )
        assert resolution.answer == "Yes"

    def test_plain_relocation_question_still_works(self):
        assert classify_question("Are you willing to relocate?", YES_NO) is QuestionType.RELOCATE


class TestPlainLocationQuestionsUnaffected:
    """The new rules require the word "relocat", so pure location questions stay put."""

    @pytest.mark.parametrize("question", [
        "Are you based in Seattle?",
        "Do you permanently reside within the United States?",
        "Are you currently located in the United States?",
    ])
    def test_still_location_confirmation(self, question):
        assert classify_question(question, YES_NO) is QuestionType.LOCATION_CONFIRMATION

    def test_relocation_answer_is_never_invented(self):
        """With no relocation data recorded, the question must not resolve to Yes."""
        resolution = resolve_answer(
            question_text="Are you based in NYC or SF or willing to relocate?",
            profile={"city": "Auburn", "state": "WA"},
            options=YES_NO,
        )
        assert resolution.answer != "Yes"
