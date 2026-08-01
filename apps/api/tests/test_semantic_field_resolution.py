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
