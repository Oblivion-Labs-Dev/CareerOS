"""Tests for review-mode autofill validation and saved-field merge."""

from __future__ import annotations

from app.services.application_assistant.browser_runner import _merge_saved_fields
from app.services.application_assistant.mapping_validation import validate_mapping_for_fill


class TestReviewAutofill:
    def test_merge_saved_restores_verified_confidence(self):
        mapped = [
            {
                "fieldId": "f1",
                "label": "Email",
                "normalizedKey": "email",
                "classification": "unknown",
                "confidence": 0.4,
                "requiresUserReview": True,
                "selectorHint": "#email",
            }
        ]
        saved = [
            {
                "fieldId": "f1",
                "label": "Email",
                "normalizedKey": "email",
                "classification": "verified",
                "proposedValue": "jane@example.com",
                "confidence": 1.0,
                "filled": True,
            }
        ]
        merged = _merge_saved_fields(mapped, saved)
        assert merged[0]["classification"] == "verified"
        assert merged[0]["proposedValue"] == "jane@example.com"
        assert merged[0]["confidence"] >= 1.0
        assert merged[0]["requiresUserReview"] is False

    def test_validate_verified_in_review_mode_ignores_low_confidence(self):
        field = {
            "label": "Email",
            "classification": "verified",
            "proposedValue": "jane@example.com",
            "confidence": 0.3,
            "selectorHint": "#email",
            "fieldType": "email",
        }
        ok, reason = validate_mapping_for_fill(
            field,
            auto_confidence=0.9,
            review_confidence=0.7,
            review_mode=True,
        )
        assert ok is True
        assert reason == "ok"

    def test_validate_verified_without_review_mode_still_requires_confidence(self):
        field = {
            "label": "Email",
            "classification": "verified",
            "proposedValue": "jane@example.com",
            "confidence": 0.3,
            "selectorHint": "#email",
            "fieldType": "email",
        }
        ok, reason = validate_mapping_for_fill(
            field,
            auto_confidence=0.9,
            review_confidence=0.7,
            review_mode=False,
        )
        assert ok is False
        assert reason == "low_confidence"

    def test_review_mode_skips_locator_uniqueness(self):
        import asyncio

        from app.services.application_assistant.mapping_validation import validate_mapping_on_page

        class FakePage:
            pass

        field = {
            "label": "What gender identity do you most closely identify with? *",
            "classification": "verified",
            "proposedValue": "Man",
            "selectorHint": "#430",
            "fieldType": "select-one",
        }
        ok, reason = asyncio.run(validate_mapping_on_page(FakePage(), field, review_mode=True))
        assert ok is True
        assert reason == "ok"
