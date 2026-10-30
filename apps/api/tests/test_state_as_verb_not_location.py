""""Please state their name" uses "state" as a verb, not the US state.

A follow-up "If yes, please state their name, the department or studio
they work for, and their job title" matched the STATE pattern's bare
``\\bstate\\b`` and was submitted as "Washington" (2026-10-30).
"""

import pytest

from app.services.application_assistant.profile_answer_resolver import resolve_answer
from app.services.application_assistant.question_classifier import QuestionType, classify_question

PROFILE = {"state": "Washington"}


@pytest.mark.parametrize("question", [
    "If yes, please state their name, the department or studio they work for, and their job title (if you know it).",
    "Please state your reason for leaving.",
    "If so, state the name of the employee.",
])
def test_state_as_a_verb_is_not_the_state_field(question):
    assert classify_question(question) != QuestionType.STATE
    assert resolve_answer(question, PROFILE).answer != "Washington"


@pytest.mark.parametrize("question", ["State", "State*", "What state do you live in?", "State of residence", "Home state"])
def test_state_field_still_classifies(question):
    assert classify_question(question) == QuestionType.STATE
