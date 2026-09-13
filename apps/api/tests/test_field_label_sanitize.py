"""Every row in the review list must state a question a person can answer.

These are the exact strings that reached the list as "required fields" and made
it unusable: an option's own text, internal field ids, and invisible characters
around required markers.
"""

import pytest

from app.services.application_assistant.playwright_autopilot_executor import (
    sanitize_field_label,
)


@pytest.mark.parametrize("raw", ["Yes", "No", "Other", "Select...", "N/A", "true"])
def test_an_option_is_not_a_question(raw):
    # Observed live: a Roblox radio group whose option text became the question,
    # so the review list asked the user to answer a question called "Yes".
    assert sanitize_field_label(raw) == ""


@pytest.mark.parametrize("raw", ["CA_47143", "QA_12203581", "12345", "a1b2c3d4e5f6", "q_9182"])
def test_an_internal_id_is_not_a_question(raw):
    assert sanitize_field_label(raw) == ""


def test_strips_invisible_characters_around_required_markers():
    # U+2060 WORD JOINER, as Epic Games renders it. Invisible on screen, but it
    # defeats exact matching against the saved answer library.
    raw = "How did you hear about this job posting?\u2060*\u2060:"
    assert sanitize_field_label(raw) == "How did you hear about this job posting?"


def test_strips_required_markers_and_collapses_whitespace():
    assert sanitize_field_label("  Are you open to  relocation? * ") == "Are you open to relocation?"
    assert sanitize_field_label("May we contact your current employer?*") == (
        "May we contact your current employer?"
    )


def test_keeps_a_real_question_intact():
    raw = "Do you now, or will you in the future, require sponsorship?"
    assert sanitize_field_label(raw) == raw
    # A question that merely contains an answer word is still a question.
    assert sanitize_field_label("Yes or no: can you start in May?") == (
        "Yes or no: can you start in May?"
    )


def test_empty_input_is_handled():
    assert sanitize_field_label("") == ""
    assert sanitize_field_label(None) == ""
