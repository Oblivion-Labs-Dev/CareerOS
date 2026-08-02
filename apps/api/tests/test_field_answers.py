"""Tests for user-provided field answers."""

from __future__ import annotations

from app.services.application_assistant.answer_classification import classify_answer, match_screening_answer
from app.services.application_assistant.field_answers import (
    list_pending_fields,
    save_field_answers,
    split_pending_fields,
)
from app.services.application_assistant.field_options import normalize_field_options


def test_match_screening_answer_by_pattern() -> None:
    profile = {
        "screeningAnswers": [
            {
                "id": "gender-identity",
                "question": "Gender identity",
                "answer": "Male",
                "matchPatterns": ["gender identity"],
            }
        ]
    }
    matched = match_screening_answer("What gender identity do you most closely identify with?", profile)
    assert matched is not None
    assert matched[1] == "Male"


def test_classify_answer_uses_profile_gender() -> None:
    profile = {"gender": "Female", "fullName": "Jane Doe"}
    cls, value, confidence, source, _sensitivity = classify_answer(
        label="What gender identity do you most closely identify with?",
        profile=profile,
        answer_library=[],
    )
    assert cls.value == "verified"
    assert value == "Female"
    assert confidence == 1.0


def test_normalize_field_options_drops_placeholders() -> None:
    assert normalize_field_options(["Select...", "Yes", "No", "yes"]) == ["Yes", "No"]


def test_sanitize_options_drops_leaked_phone_country_list() -> None:
    from app.services.application_assistant.field_options import sanitize_options_for_field

    leaked = ["United States +1", "Afghanistan +93", "Albania +355", "Algeria +213", "Andorra +376"]
    field = {
        "label": "In what cities are you available to work?",
        "fieldType": "select-one",
        "fieldId": "cities",
    }
    assert sanitize_options_for_field(field, leaked) == []


def test_filter_wizard_pending_rewrites_privacy_policy_to_checkbox() -> None:
    from app.services.application_assistant.field_answers import filter_wizard_pending

    pending = [
        {
            "fieldId": "privacy",
            "label": "I understand my application will be processed in accordance with Datadog's Candidate Privacy Policy.",
            "fieldType": "select-one",
            "wizardEligible": True,
            "options": ["United States +1", "Afghanistan +93", "Albania +355", "Algeria +213", "Andorra +376"],
        }
    ]
    wizard = filter_wizard_pending(pending)
    assert wizard[0]["fieldType"] == "checkbox"
    assert wizard[0]["options"] == []


def test_list_pending_fields_preserves_application_dropdown_options() -> None:
    draft = {
        "fields": [
            {
                "label": "Country",
                "classification": "unknown",
                "required": True,
                "fieldType": "select-one",
                "options": ["United States", "Canada", "Select a country"],
            }
        ]
    }
    pending = list_pending_fields(draft)
    assert pending[0]["options"] == ["United States", "Canada"]


def test_split_pending_fields_buckets_profile_and_application() -> None:
    pending = [
        {
            "fieldId": "f1",
            "label": "Gender",
            "normalizedKey": "gender",
            "suggestedProfileKey": "gender",
        },
        {
            "fieldId": "f2",
            "label": "Why Reddit?",
            "normalizedKey": "why_reddit",
            "suggestedProfileKey": None,
        },
    ]
    split = split_pending_fields(pending)
    assert len(split["profilePending"]) == 1
    assert split["profilePending"][0]["category"] == "profile"
    assert split["profileKeysMissing"] == ["gender"]
    assert len(split["applicationPending"]) == 1
    assert split["applicationPending"][0]["category"] == "application"
    assert len(split["pending"]) == 2


def test_list_pending_fields_excludes_browser_only_labels() -> None:
    draft = {
        "fields": [
            {"label": "Search", "classification": "unknown", "required": True, "fieldType": "search", "section": "Phone"},
            {"label": "Please specify", "classification": "unknown", "required": True},
            {"label": "If (f) Other please explain", "classification": "unknown", "required": True},
            {"label": "Gender", "classification": "unknown", "required": True, "suggestedProfileKey": "gender"},
        ]
    }
    pending = list_pending_fields(draft)
    assert len(pending) == 1
    assert pending[0]["label"] == "Gender"


def test_filter_wizard_pending_excludes_search_even_when_ai_marks_eligible() -> None:
    from app.services.application_assistant.field_answers import filter_wizard_pending

    pending = [
        {"fieldId": "1", "label": "Gender", "wizardEligible": True},
        {"fieldId": "2", "label": "Search", "wizardEligible": True, "fieldType": "search"},
    ]
    wizard = filter_wizard_pending(pending)
    assert len(wizard) == 1
    assert wizard[0]["label"] == "Gender"


def test_filter_wizard_pending_respects_ai_flag() -> None:
    from app.services.application_assistant.field_answers import filter_wizard_pending

    pending = [
        {"fieldId": "1", "label": "Gender", "wizardEligible": True},
        {"fieldId": "2", "label": "Search", "wizardEligible": False},
        {"fieldId": "3", "label": "Veteran", "wizardEligible": True},
    ]
    wizard = filter_wizard_pending(pending)
    assert len(wizard) == 2
    assert {f["label"] for f in wizard} == {"Gender", "Veteran"}


def test_fallback_enrich_marks_vague_fields_browser_only() -> None:
    from app.services.application_assistant.field_answers import _fallback_enrich_field

    field = _fallback_enrich_field({"label": "Attach", "fieldType": "file", "fieldId": "f1"})
    assert field["wizardEligible"] is False
    assert "resume" in field["displayTitle"].lower() or "document" in field["displayTitle"].lower()

    clear = _fallback_enrich_field({"label": "Gender", "fieldId": "f2", "required": True})
    assert clear["wizardEligible"] is True


def test_heuristic_dedupe_merges_similar_profile_questions() -> None:
    from app.services.application_assistant.field_answers import _heuristic_dedupe_pending

    occurrences = [
        {
            "fieldId": "f1",
            "appId": "app_a",
            "companyName": "SpaceX",
            "label": "Gender",
            "normalizedKey": "gender",
            "suggestedProfileKey": "gender",
            "displayTitle": "What is your gender identity?",
            "required": True,
            "options": ["Man", "Woman"],
            "wizardEligible": True,
        },
        {
            "fieldId": "f2",
            "appId": "app_b",
            "companyName": "Reddit",
            "label": "What gender do you identify as?",
            "normalizedKey": "what_gender_do_you_identify_as",
            "suggestedProfileKey": "gender",
            "displayTitle": "What gender do you identify as?",
            "required": True,
            "options": ["Male", "Female", "Non-binary"],
            "wizardEligible": True,
        },
    ]
    unified = _heuristic_dedupe_pending(occurrences)
    assert len(unified) == 1
    assert unified[0]["suggestedProfileKey"] == "gender"
    assert unified[0]["occurrenceCount"] == 2
    assert len(unified[0]["targets"]) == 2
    assert "Man" in unified[0]["options"] or "Male" in unified[0]["options"]


def test_sanitize_clears_placeholder_on_vague_fields() -> None:
    from app.services.application_assistant.field_answers import _sanitize_misleading_user_answers

    fields = [
        {
            "label": "Attach",
            "classification": "verified",
            "proposedValue": "-",
            "userProvided": True,
        },
        {
            "label": "Gender",
            "classification": "verified",
            "proposedValue": "Man",
            "userProvided": True,
        },
        {
            "label": "Search",
            "classification": "verified",
            "proposedValue": "-",
            "userProvided": True,
        },
    ]
    cleared = _sanitize_misleading_user_answers(fields)
    assert cleared == 2
    assert fields[0]["classification"] == "unknown"
    assert fields[0]["userProvided"] is False
    assert fields[1]["proposedValue"] == "Man"


def test_list_pending_fields_excludes_document_uploads() -> None:
    draft = {
        "fields": [
            {"label": "Attach", "classification": "unknown", "required": True},
            {"label": "Are you authorized to work?", "classification": "unknown", "required": True},
        ]
    }
    pending = list_pending_fields(draft)
    assert len(pending) == 1
    assert pending[0]["label"] == "Are you authorized to work?"


def test_list_pending_fields_excludes_verified_and_captcha() -> None:
    draft = {
        "fields": [
            {"label": "Email", "classification": "verified", "proposedValue": "a@b.com"},
            {"label": "Veteran status", "classification": "unknown", "required": True, "normalizedKey": "veteran"},
            {"label": "g-recaptcha-response", "classification": "unknown", "normalizedKey": "g-recaptcha-response"},
        ]
    }
    pending = list_pending_fields(draft)
    assert len(pending) == 1
    assert pending[0]["label"] == "Veteran status"


def test_save_field_answers_updates_profile_and_draft() -> None:
    from app.db.store import get_kv, session_scope, set_kv
    from app.services.application_assistant.persistence import create_application_draft, get_application_draft

    with session_scope() as db:
        set_kv(db, "profile", {"fullName": "Test User"})
        draft = create_application_draft(
            db,
            {
                "jobId": "job_test",
                "jobUrl": "https://example.com/apply",
                "companyName": "Test Co",
                "roleTitle": "Engineer",
                "status": "needs_review",
                "fields": [
                    {
                        "fieldId": "field_veteran",
                        "label": "Are you a veteran?",
                        "normalizedKey": "are_you_a_veteran",
                        "fieldType": "select-one",
                        "classification": "unknown",
                        "required": True,
                        "options": ["Yes", "No", "Prefer not to answer"],
                    }
                ],
            },
        )
        app_id = draft["id"]

        updated = save_field_answers(
            db,
            app_id,
            [{"fieldId": "field_veteran", "value": "No", "profileKey": "veteran"}],
        )
        assert updated is not None
        profile = get_kv(db, "profile") or {}
        assert profile.get("veteran") == "No"

        refreshed = get_application_draft(db, app_id)
        assert refreshed is not None
        field = refreshed["fields"][0]
        assert field["classification"] == "verified"
        assert field["proposedValue"] == "No"

        from app.services.application_assistant.persistence import delete_application_draft

        delete_application_draft(db, app_id)


def test_refresh_wizard_cache_from_readiness_filters_answered_fields() -> None:
    from app.services.application_assistant.field_answers import refresh_wizard_cache_from_readiness

    draft = {
        "aiAnalyzed": True,
        "wizardPendingCache": {
            "pending": [
                {"fieldId": "f1", "label": "Gender", "wizardEligible": True},
                {"fieldId": "f2", "label": "Veteran", "wizardEligible": True},
            ],
            "profilePending": [{"fieldId": "f1", "label": "Gender", "wizardEligible": True}],
            "applicationPending": [{"fieldId": "f2", "label": "Veteran", "wizardEligible": True}],
            "profileKeysMissing": ["gender"],
        },
    }
    readiness = {"pending": [{"fieldId": "f2", "label": "Veteran"}]}
    split = refresh_wizard_cache_from_readiness(draft, readiness)
    assert split is not None
    assert len(split["pending"]) == 1
    assert split["pending"][0]["fieldId"] == "f2"
    assert len(split["profilePending"]) == 0
    assert len(split["applicationPending"]) == 1


def test_refresh_wizard_cache_returns_none_without_analysis() -> None:
    from app.services.application_assistant.field_answers import refresh_wizard_cache_from_readiness

    draft = {"aiAnalyzed": False, "wizardPendingCache": {"pending": []}}
    assert refresh_wizard_cache_from_readiness(draft, {"pending": []}) is None


def test_normalize_submitted_value_checkbox() -> None:
    from app.services.application_assistant.field_answers import _normalize_submitted_value

    field = {"fieldType": "checkbox"}
    assert _normalize_submitted_value(field, "checked") == "yes"
    assert _normalize_submitted_value(field, "no") == "no"


def test_fallback_enrich_checkbox_consent() -> None:
    from app.services.application_assistant.field_answers import _fallback_enrich_field

    field = _fallback_enrich_field(
        {
            "label": "By checking this box, I consent to demographic data processing*",
            "fieldType": "checkbox",
            "fieldId": "consent",
        }
    )
    assert field["wizardEligible"] is True


def test_fallback_enrich_search_not_wizard() -> None:
    from app.services.application_assistant.field_answers import _fallback_enrich_field

    field = _fallback_enrich_field({"label": "Search", "fieldType": "search", "fieldId": "s1"})
    assert field["wizardEligible"] is False
