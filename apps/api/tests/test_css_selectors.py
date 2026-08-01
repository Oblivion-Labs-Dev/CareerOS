"""Tests for CSS selector normalization."""

from app.services.application_assistant.css_selectors import normalize_css_selector


def test_numeric_id_selector() -> None:
    assert normalize_css_selector("#430") == '[id="430"]'


def test_valid_id_unchanged() -> None:
    assert normalize_css_selector("#email") == "#email"


def test_name_selector_unchanged() -> None:
    assert normalize_css_selector("[name='phone']") == "[name='phone']"
