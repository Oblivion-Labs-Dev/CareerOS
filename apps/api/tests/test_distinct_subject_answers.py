"""A saved answer is never reused for a question about a different subject.

"…hands-on experience with React and React Native?", "…with Python and
Django?" and "…with FHIR and HL7?" share half their words. Word overlap alone
grouped them, saved the React answer under all three wordings, and answered the
FHIR question "I've shipped production features using both React…".
"""

from __future__ import annotations

from app.services.application_assistant.pending_question_groups import group_pending_questions
from app.services.application_assistant.profile_answer_resolver import (
    _find_user_approved_answer,
)

REACT = "Which of the following best describes your hands-on production experience with React and React Native?*"
DJANGO = "Which best describes your hands-on experience with Python and Django?*"
FHIR = "Which best describes your hands-on experience building production software with FHIR and HL7?*"
REACT_ANSWER = "I've shipped production features using both React and React Native"


def _library(*variants: str, value: str = REACT_ANSWER) -> list[dict]:
    return [{"questionVariants": list(variants), "value": value, "verificationStatus": "verified"}]


def test_a_saved_answer_is_not_reused_for_a_different_technology() -> None:
    lib = _library(REACT)
    assert _find_user_approved_answer(DJANGO, lib) is None
    assert _find_user_approved_answer(FHIR, lib) is None


def test_a_rewording_that_only_adds_words_still_reuses_the_answer() -> None:
    lib = _library("Are you legally authorized to work in the United States?", value="Yes")
    assert _find_user_approved_answer("Are you authorized to work in the United States?", lib) == "Yes"


def test_a_truncated_label_still_reuses_the_answer() -> None:
    lib = _library("How did you perform in your native language at high school?", value="Top 1%")
    assert _find_user_approved_answer("How did you perform in your native language at hig", lib) == "Top 1%"


def test_questions_about_different_technologies_are_separate_groups() -> None:
    for order in ([REACT, DJANGO, FHIR], [DJANGO, REACT, FHIR], [FHIR, DJANGO, REACT]):
        jobs = [
            {"id": f"job{i}", "company": f"Co{i}", "pendingQuestions": [{"question": q}]}
            for i, q in enumerate(order)
        ]
        assert [len(g.variants) for g in group_pending_questions(jobs)] == [1, 1, 1]
