"""Tests for intl-tel-input phone country field handling."""

from __future__ import annotations

from app.services.application_assistant.answer_classification import (
    classify_answer,
    infer_phone_country,
    is_phone_country_field,
    is_phone_country_search_field,
    match_profile_key,
)


class TestPhoneCountryFields:
    def test_country_next_to_phone_maps_to_phone_country(self):
        assert match_profile_key("Country*", field_id="country", selector_hint="#country") == "phoneCountry"

    def test_search_inside_iti_is_ui_chrome(self):
        assert is_phone_country_search_field("Search", selector_hint="#iti-0__search-input")
        assert match_profile_key("Search", selector_hint="#iti-0__search-input") is None

    def test_infer_us_from_local_phone(self):
        assert infer_phone_country({"phone": "(425) 336-9852", "location": "Seattle, WA"}) == "United States"

    def test_classify_phone_country_not_location(self):
        profile = {"phone": "(425) 336-9852", "location": "Seattle, WA"}
        cls, value, confidence, source, _ = classify_answer(
            label="Country*",
            profile=profile,
            field_id="country",
            selector_hint="#country",
        )
        assert cls.value == "verified"
        assert value == "United States"
        assert source == "profile.phoneCountry"
        assert confidence == 1.0

    def test_is_phone_country_field_by_selector(self):
        assert is_phone_country_field("Country*", field_id="country", selector_hint="#country")
        assert is_phone_country_field("Country*", selector_hint='[id="country"]')
