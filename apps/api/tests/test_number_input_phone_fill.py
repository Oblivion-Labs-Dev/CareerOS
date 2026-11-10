"""Regression: a phone field rendered as <input type="number"> must still get filled.

Seen live on Ashby (Freed, 2026-11-05): Playwright refuses to type
"(425) 336-9852" into a number input ("Cannot type text into
input[type=number]"), so Phone Number stayed empty and the job went to review.
A number input gets the numeric form of the value instead.
"""
from __future__ import annotations

from app.services.application_assistant.playwright_autopilot_executor import (
    _fill_first_visible,
    _numeric_value_for_number_input,
)
from tests.browser_test_utils import eval_in_pooled_page


def test_numeric_value_for_number_input():
    assert _numeric_value_for_number_input("(425) 336-9852") == "4253369852"
    assert _numeric_value_for_number_input("+1 425-336-9852") == "14253369852"
    assert _numeric_value_for_number_input("$150,000") == "150000"
    assert _numeric_value_for_number_input("3.5") == "3.5"
    assert _numeric_value_for_number_input("two weeks") is None


def test_formatted_phone_fills_a_number_input():
    html = '<label for="ph">Phone Number</label><input type="number" id="ph" name="phone">'

    async def check(page):
        ok = await _fill_first_visible(page, ["input[name*='phone' i]"], "(425) 336-9852")
        return ok, await page.input_value("#ph")

    assert eval_in_pooled_page(html, check) == (True, "4253369852")


def test_text_input_keeps_formatting():
    html = '<input type="tel" id="ph" name="phone">'

    async def check(page):
        await _fill_first_visible(page, ["input[name*='phone' i]"], "(425) 336-9852")
        return await page.input_value("#ph")

    assert eval_in_pooled_page(html, check) == "(425) 336-9852"
