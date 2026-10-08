"""Healing never ticks an option of a checkbox choice group.

Truveta (2026-10-08) was submitted with all four sponsorship options ticked,
"No, I do not require sponsorship" among them, and both Yes and No on the
relocation question: healing resolved each option label as its own question.
Runs the real JS in Chromium: group membership depends on the rendered DOM.
"""

from __future__ import annotations

import asyncio

from app.services.application_assistant.playwright_autopilot_executor import (
    _affirms_checkbox,
    _is_choice_group_checkbox,
)

# Shaped like Greenhouse's job-boards form.
FORM = """
<html><body><form>
  <fieldset><legend>Do you now OR in the future require visa sponsorship to continue working in the US?*</legend>
    <input type="checkbox" id="s0" name="question_1[]"><label for="s0">Yes, I am on an F1 Visa/CPT/OPT</label>
    <input type="checkbox" id="s1" name="question_1[]"><label for="s1">Yes, I am on an H1B Visa</label>
    <input type="checkbox" id="s2" name="question_1[]"><label for="s2">No, I do not require sponsorship either now OR in the future</label>
  </fieldset>
  <div><input type="checkbox" id="n0" name="loose[]"><label for="n0">Seattle</label>
       <input type="checkbox" id="n1" name="loose[]"><label for="n1">Remote</label></div>
  <div><input type="checkbox" id="f_q9-labeled-checkbox-0" name="He/him">
       <input type="checkbox" id="f_q9-labeled-checkbox-1" name="She/her"></div>
  <fieldset><legend>Consent</legend>
    <input type="checkbox" id="c0" name="gdpr"><label for="c0">I agree to the privacy policy</label>
  </fieldset>
  <input type="checkbox" id="c1" name="ack"><label for="c1">I acknowledge</label>
</form></body></html>
"""


def _groups(ids: list[str]) -> dict[str, bool]:
    async def go():
        from playwright.async_api import async_playwright

        async with async_playwright() as p:
            browser = await p.chromium.launch(headless=True)
            try:
                page = await browser.new_page()
                await page.set_content(FORM)
                return {
                    i: await _is_choice_group_checkbox(page.locator(f'[id="{i}"]').first)
                    for i in ids
                }
            finally:
                await browser.close()

    return asyncio.run(go())


def test_options_of_a_choice_group_are_recognised():
    found = _groups(["s0", "s2", "n0", "f_q9-labeled-checkbox-1", "c0", "c1"])
    assert found == {
        "s0": True,
        "s2": True,
        "n0": True,
        "f_q9-labeled-checkbox-1": True,
        "c0": False,
        "c1": False,
    }


def test_only_an_affirmative_answer_ticks_a_box():
    assert _affirms_checkbox("Yes")
    assert _affirms_checkbox("I agree.")
    assert not _affirms_checkbox("Yes, I am on an H1B Visa")
    assert not _affirms_checkbox("No")
    assert not _affirms_checkbox("Auburn, Washington, United States")
    assert not _affirms_checkbox("")
