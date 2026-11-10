"""Questions the candidate answered once, resolved deterministically after.

GPA thresholds and bands, CEFR-prefixed and "conversational level" English
ladders, and salary-range yes/no questions all reached review although the
profile held what was needed to answer them.
"""

from __future__ import annotations

import pytest

from app.services.application_assistant.profile_answer_resolver import resolve_answer

YN = ["Yes", "No"]
PROFILE = {
    "englishLevel": "Fluent",
    "graduateGpa": "3.77",
    "salaryExpectations": "$140,000",
}


def _r(question, opts=None, profile=PROFILE):
    return resolve_answer(question, profile, opts)


@pytest.mark.parametrize(
    "question, opts, expected",
    [
        ("Do you have a cumulative GPA of 3.0 or higher? *", None, "Yes"),
        ("Is your cumulative GPA equal to or higher than 2.8?", YN, "Yes"),
        ("Do you have a GPA of at least 3.9?", YN, "No"),
    ],
)
def test_gpa_threshold_compares_recorded_gpa(question, opts, expected):
    assert _r(question, opts).answer == expected


def test_gpa_band_rounds_down_never_up():
    opts = ["4.0 out of 4.0", "3.9 out of 4.0", "3.8 out of 4.0", "3.7 out of 4.0", "3.6 out of 4.0"]
    assert _r("What was your GPA?", opts).answer == "3.7 out of 4.0"


def test_undergraduate_gpa_is_not_answered_with_graduate_gpa():
    res = _r("What was your undergraduate GPA?")
    assert res.answer is None
    assert res.blocking_errors


def test_gpa_still_blocks_with_nothing_recorded():
    res = _r("Do you have a cumulative GPA of 3.0 or higher?", YN, profile={})
    assert res.answer is None
    assert res.blocking_errors


def test_english_cefr_prefixed_options():
    opts = ["C2: Proficient.", "C1: Advanced.", "B2: Upper-Intermediate.", "B1: Intermediate.", "A2: Pre-Intermediate.", "A1: Basic"]
    assert _r("What's your english level?", opts).answer == "C2: Proficient."


def test_english_conversational_ladder_takes_top_rung_for_fluent():
    opts = ["Basic conversational level", "Intermediate conversational level",
            "Upper intermediate conversational level", "Advanced conversational level"]
    assert _r("What's your oral english level?*", opts).answer == "Advanced conversational level"


def test_english_conversational_ladder_not_inflated_for_lower_level():
    opts = ["Basic conversational level", "Intermediate conversational level", "Advanced conversational level"]
    res = _r("What's your oral english level?*", opts, profile={**PROFILE, "englishLevel": "Intermediate"})
    assert res.answer != "Advanced conversational level"


@pytest.mark.parametrize(
    "question",
    [
        "Our base salary range for this role is $154,000 - $175,000 annually. Do you acknowledge "
        "and agree that this is within your expectations?",
        "For this position, the expected base pay range is: $170,000-$220,000 per year. Does this "
        "meet your compensation expectations?",
        "Do your compensation expectations align with the posted range? (Base compensation)*",
        "The salary for this position is listed in the description. Is this salary within your expectations?*",
    ],
)
def test_salary_range_meeting_expectation_is_yes(question):
    assert _r(question, YN).answer == "Yes"


def test_salary_range_below_expectation_goes_to_review():
    res = _r("For this position, the expected base pay range is: $90,000-$120,000 per year. "
             "Does this meet your compensation expectations?", YN)
    assert res.answer is None
    assert res.blocking_errors


def test_salary_range_in_thousands_shorthand():
    res = _r("The range is $100k - $130k. Does this meet your compensation expectations?", YN)
    assert res.answer is None
