"""Tests for AI semantic field resolution."""

from __future__ import annotations

from app.services.application_assistant.canonical_registry import registry_context_for_prompt
from app.services.application_assistant.semantic_field_resolution import _field_needs_semantic_resolution


def test_registry_context_includes_saved_question_wording() -> None:
    ctx = registry_context_for_prompt(
        [
            {
                "normalizedKey": "why_reddit",
                "questionVariants": ["Why do you want to work at Reddit?", "What excites you about Reddit?"],
                "value": "Mission alignment",
                "verificationStatus": "verified",
            }
        ]
    )
    assert ctx["savedAnswers"][0]["normalizedKey"] == "why_reddit"
    assert len(ctx["savedAnswers"][0]["questions"]) == 2
    assert ctx["savedAnswers"][0]["hasValue"] is True


def test_field_needs_semantic_resolution_for_unknown_only() -> None:
    assert _field_needs_semantic_resolution({"classification": "unknown", "label": "Why join us?"}) is True
    assert _field_needs_semantic_resolution(
        {
            "classification": "verified",
            "source": "answer_library.ans_1",
            "mappedBy": "semantic",
        }
    ) is False
    assert _field_needs_semantic_resolution(
        {"classification": "verified", "source": "profile.gender", "label": "Gender"}
    ) is False


def test_preferred_name_resolves_first_name_only():
    from app.services.application_assistant.profile_answer_resolver import resolve_answer
    from app.services.application_assistant.question_classifier import QuestionType, classify_question

    profile = {
        "firstName": "Akshay",
        "lastName": "Borse",
        "fullName": "Akshay Borse",
        "preferredName": "Akshay",
    }

    qtype = classify_question("Preferred Name", "preferred_name")
    assert qtype == QuestionType.PREFERRED_NAME

    res = resolve_answer("Preferred Name", profile, field_id="preferred_name")
    assert res.answer == "Akshay"
    assert res.answer != "Akshay Borse"


def test_other_links_resolves_empty_when_no_link_instead_of_essay():
    from app.services.application_assistant.profile_answer_resolver import resolve_answer
    from app.services.application_assistant.question_classifier import QuestionType, classify_question

    profile = {
        "firstName": "Akshay",
        "lastName": "Borse",
        "linkedin": "https://linkedin.com/in/akshayborse",
        "github": "https://github.com/amsborse",
    }

    qtype = classify_question("Other Links", "other_links")
    assert qtype == QuestionType.WEBSITE

    res = resolve_answer("Other Links", profile, field_id="other_links")
    # Must NOT be an essay text (e.g. "Yes, extensive production experience...")
    assert "production experience" not in res.answer.lower()
    assert res.answer == "" or res.answer.startswith("http")


