"""Tailoring effort is chosen by score band, and never loosens form answering."""

from __future__ import annotations

import pytest

from app.services.application_assistant.autopilot_runner import (
    MIN_MATCH_SCORE_TO_SUBMIT,
    TAILORING_HONEST_FLOOR,
    _tailoring_mode_for_score,
)
from app.services.application_assistant.persistence import TAILORING_MODE_PRESETS


@pytest.mark.parametrize("score", [80.0, 85.0, 95.0, 100.0])
def test_at_or_above_the_bar_needs_no_tailoring(score):
    assert _tailoring_mode_for_score(score, "honest") == "off"


@pytest.mark.parametrize("score", [60.0, 65.0, 70.0, 79.9])
def test_near_miss_uses_honest(score):
    assert _tailoring_mode_for_score(score, "honest") == "honest"


@pytest.mark.parametrize("score", [0.0, 20.0, 45.0, 59.9])
def test_distant_match_uses_aggressive(score):
    assert _tailoring_mode_for_score(score, "honest") == "aggressive"


def test_band_boundaries_are_exact():
    assert _tailoring_mode_for_score(TAILORING_HONEST_FLOOR, "honest") == "honest"
    assert _tailoring_mode_for_score(TAILORING_HONEST_FLOOR - 0.1, "honest") == "aggressive"
    assert _tailoring_mode_for_score(MIN_MATCH_SCORE_TO_SUBMIT, "honest") == "off"
    assert _tailoring_mode_for_score(MIN_MATCH_SCORE_TO_SUBMIT - 0.1, "honest") == "honest"


@pytest.mark.parametrize("score", [0.0, 50.0, 70.0, 95.0])
def test_operator_off_always_wins(score):
    """The bands decide how much to tailor, not whether the feature is on."""
    assert _tailoring_mode_for_score(score, "off") == "off"


def test_tailoring_mode_never_changes_form_answer_confidence():
    """The regression this exists for.

    "aggressive" used to drop auto-accept from 0.90 to 0.75 and review from
    0.70 to 0.50. Since aggressive is selected precisely for the postings the
    candidate matches worst, asking for stronger resume wording also made the
    system fill in form answers it was least sure about, on the applications
    where being wrong is most likely.
    """
    accept = {p["autoAcceptConfidence"] for p in TAILORING_MODE_PRESETS.values()}
    review = {p["reviewConfidence"] for p in TAILORING_MODE_PRESETS.values()}
    assert accept == {0.90}, f"auto-accept must not vary by tailoring mode, got {accept}"
    assert review == {0.70}, f"review threshold must not vary by tailoring mode, got {review}"
