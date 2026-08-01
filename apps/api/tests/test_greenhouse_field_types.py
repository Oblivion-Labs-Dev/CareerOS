"""Tests for Greenhouse field type detection and fill action selection."""

from __future__ import annotations

from app.services.application_assistant.providers.greenhouse import resolve_greenhouse_field_type


class TestGreenhouseFieldTypes:
    def test_text_input_stays_text_even_with_dropdown_noise(self):
        assert (
            resolve_greenhouse_field_type(tag="input", input_type="text", role="", aria_haspopup="")
            == "text"
        )

    def test_email_input_stays_email(self):
        assert resolve_greenhouse_field_type(tag="input", input_type="email") == "email"

    def test_native_select_is_select_one(self):
        assert resolve_greenhouse_field_type(tag="select") == "select-one"

    def test_combobox_is_select_one(self):
        assert resolve_greenhouse_field_type(tag="input", role="combobox", aria_haspopup="listbox") == "select-one"
