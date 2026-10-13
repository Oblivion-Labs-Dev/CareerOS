"""Betterteam's single "Your Name" box wants the whole name; it was left blank."""

from app.services.application_assistant.profile_answer_resolver import resolve_answer
from app.services.application_assistant.question_classifier import QuestionType, classify_question

PROFILE = {"firstName": "Akshay", "lastName": "Borse", "fullName": "Akshay Borse"}


def test_your_name_is_the_full_name():
    assert classify_question("Your Name") == QuestionType.FULL_NAME
    assert classify_question("Your name *") == QuestionType.FULL_NAME
    assert resolve_answer("Your Name", PROFILE).answer == "Akshay Borse"


def test_longer_questions_mentioning_your_name_are_not_name_fields():
    assert classify_question("Is your name on the lease?") != QuestionType.FULL_NAME
    assert classify_question("Your name as a referrer") != QuestionType.FULL_NAME
