"""Regression: the fuzzy radio pass must never tick a wrong EEO option.

Seen live on Ashby forms (Render, Crusoe; 2026-11-04): the resolver answered
Race with "Asian (Not Hispanic or Latino)" but the form ended up on
"Hispanic or Latino", because that option's text is a substring of the wanted
answer and it came first in the group. A negated mention ("not X") is not a
match for X, and an ambiguous fuzzy match must leave the field alone so it
goes to review instead of submitting a wrong answer.
"""
from __future__ import annotations

from app.services.application_assistant.playwright_autopilot_executor import _select_radio_option
from tests.browser_test_utils import eval_in_pooled_page


def _group(name: str, options: list[str]) -> str:
    rows = "".join(
        f'<label><input type="radio" name="{name}" id="{name}_{i}" value="{opt}">{opt}</label>'
        for i, opt in enumerate(options)
    )
    return f'<fieldset><legend>Q</legend>{rows}</fieldset>'


RACE_SHORT = _group("race", ["Hispanic or Latino", "White", "Asian", "Decline to self-identify"])


def test_negated_substring_is_not_chosen_over_the_real_option():
    async def check(page):
        ok = await _select_radio_option(page, "race_0", "Asian (Not Hispanic or Latino)")
        return ok, await page.is_checked("#race_0"), await page.is_checked("#race_2")

    assert eval_in_pooled_page(RACE_SHORT, check) == (True, False, True)


AMBIGUOUS = _group("amb", ["Yes, full time", "Yes, part time", "No"])


def test_ambiguous_fuzzy_match_ticks_nothing():
    async def check(page):
        ok = await _select_radio_option(page, "amb_0", "Yes")
        checked = [await page.is_checked(f"#amb_{i}") for i in range(3)]
        return ok, checked

    assert eval_in_pooled_page(AMBIGUOUS, check) == (False, [False, False, False])
