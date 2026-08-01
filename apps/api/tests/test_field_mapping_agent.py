"""Tests for canonical registry and mapping pipeline."""

from __future__ import annotations

from app.services.application_assistant.canonical_registry import (
    canonical_to_value_ref,
    is_valid_canonical_key,
    resolve_value_ref,
)
from app.services.application_assistant.mapping_pipeline import apply_mapping_plan, default_field_mapping_settings


def test_valid_canonical_keys() -> None:
    assert is_valid_canonical_key("employment.current.company")
    assert is_valid_canonical_key("custom.my_question", approved_custom_keys={"my_question"})
    assert not is_valid_canonical_key("employment.invented.company")
    assert not is_valid_canonical_key("custom.not_approved", approved_custom_keys=set())


def test_canonical_to_value_ref() -> None:
    assert canonical_to_value_ref("employment.current.company") == "profile.employment.current.company"
    assert canonical_to_value_ref("documents.selected_resume") == "documents.defaultResume"
    assert canonical_to_value_ref("custom.salary_flex") == "answer_library.salary_flex"


def test_resolve_value_ref_company() -> None:
    profile = {"fullName": "Akshay Borse", "currentCompany": "Microsoft"}
    resolved = resolve_value_ref("profile.employment.current.company", profile=profile, answer_library=[])
    assert resolved is not None
    assert resolved[1] == "Microsoft"


def test_apply_mapping_plan_company_field() -> None:
    mapped = [
        {
            "fieldId": "field_12",
            "label": "Current or most recent employer",
            "fieldType": "text",
            "classification": "unknown",
            "selectorHint": "#company",
        }
    ]
    plan = {
        "pageSummary": "Greenhouse application form",
        "mappings": [
            {
                "fieldId": "field_12",
                "canonicalKey": "employment.current.company",
                "questionType": "employment_history",
                "confidence": 0.97,
                "reason": "Label asks for current employer",
                "classification": "verified",
                "requiresUserReview": False,
            }
        ],
        "unmappedFields": [],
        "blockers": [],
    }
    updated, report = apply_mapping_plan(
        mapped,
        plan,
        {"profile": {"currentCompany": "Microsoft"}, "answerLibrary": [], "documents": {}},
        mapping_settings=default_field_mapping_settings(),
    )
    assert updated[0]["proposedValue"] == "Microsoft"
    assert updated[0]["valueRef"] == "profile.employment.current.company"
    assert updated[0]["canonicalKey"] == "employment.current.company"
    assert len(report["applied"]) == 1


def test_apply_mapping_plan_rejects_invalid_key() -> None:
    mapped = [{"fieldId": "field_1", "label": "Foo", "classification": "unknown", "selectorHint": "#f"}]
    plan = {
        "mappings": [
            {
                "fieldId": "field_1",
                "canonicalKey": "identity.social_security",
                "confidence": 0.99,
                "reason": "bad",
            }
        ]
    }
    updated, report = apply_mapping_plan(
        mapped,
        plan,
        {"profile": {}, "answerLibrary": []},
        mapping_settings=default_field_mapping_settings(),
    )
    assert updated[0].get("proposedValue") is None
    assert report["rejected"]


def test_infer_canonical_from_field_country() -> None:
    from app.services.application_assistant.canonical_registry import infer_canonical_from_field

    assert infer_canonical_from_field({"label": "Country", "fieldType": "select-one"}) == "location.city"


def test_apply_rules_fallback_company() -> None:
    from app.services.application_assistant.mapping_pipeline import apply_rules_fallback

    mapped = [
        {
            "fieldId": "field_3",
            "label": "Name of your current company",
            "fieldType": "text",
            "classification": "unknown",
            "selectorHint": "#company",
        }
    ]
    updated, report = apply_rules_fallback(
        mapped,
        {"profile": {"currentCompany": "Microsoft"}, "answerLibrary": [], "documents": {}},
        default_field_mapping_settings(),
    )
    assert updated[0]["proposedValue"] == "Microsoft"
    assert len(report["applied"]) == 1


def test_parse_json_response_strips_think_blocks() -> None:
    from app.services.application_assistant.llm_client import LLMClient

    think_open, think_close = "<" + "think" + ">", "<" + "/" + "think" + ">"
    raw = (
        f"{think_open}Reason about fields here.{think_close}\n"
        '{"pageSummary":"form","mappings":[],"unmappedFields":[],"blockers":[]}'
    )
    parsed = LLMClient._parse_json_response(raw)
    assert parsed is not None
    assert parsed.get("pageSummary") == "form"


def test_parse_json_response_uses_last_think_block_only() -> None:
    from app.services.application_assistant.llm_client import LLMClient

    think_open, think_close = "<" + "think" + ">", "<" + "/" + "think" + ">"
    raw = (
        f"{think_open}Draft invalid: {{not valid json}}{think_close}\n"
        f"{think_open}Second pass reasoning{think_close}\n"
        '{"pageSummary":"final","mappings":[{"fieldId":"f1"}],"unmappedFields":[],"blockers":[]}'
    )
    parsed = LLMClient._parse_json_response(raw)
    assert parsed is not None
    assert parsed.get("pageSummary") == "final"
    assert parsed.get("mappings")[0]["fieldId"] == "f1"


def test_parse_json_response_ignores_braces_inside_thinking() -> None:
    from app.services.application_assistant.llm_client import LLMClient

    think_open, think_close = "<" + "think" + ">", "<" + "/" + "think" + ">"
    raw = (
        f"{think_open}Maybe map to {{\"wrong\": \"object\"}} for testing.{think_close}\n"
        '{"pageSummary":"ok","mappings":[],"unmappedFields":[],"blockers":[]}'
    )
    parsed = LLMClient._parse_json_response(raw)
    assert parsed is not None
    assert parsed.get("pageSummary") == "ok"


def test_parse_json_response_after_prose_following_think() -> None:
    from app.services.application_assistant.llm_client import LLMClient

    think_open, think_close = "<" + "think" + ">", "<" + "/" + "think" + ">"
    raw = (
        f"{think_open}Done reasoning.{think_close}\n"
        "Here is the mapping JSON:\n"
        "```json\n"
        '{"pageSummary":"form","mappings":[],"unmappedFields":[],"blockers":[]}\n'
        "```"
    )
    parsed = LLMClient._parse_json_response(raw)
    assert parsed is not None
    assert parsed.get("pageSummary") == "form"
