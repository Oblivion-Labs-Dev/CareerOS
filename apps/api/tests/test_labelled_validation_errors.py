"""A review for "This field is required." must say which field.

Seven Braze applications went to review on 2026-09-27 with only that text; the
screenshot showed the empty field was the required Talent Community opt-in.
Runs the real JS in Chromium: the pairing depends on the rendered DOM.
"""

from __future__ import annotations

import asyncio

import pytest

from app.services.application_assistant.playwright_autopilot_executor import (
    _labelled_validation_errors,
)

pytestmark = pytest.mark.usefixtures("initialize_database")

# Shaped like Greenhouse's job-boards form after a failed submit.
FORM = """
<html><body><form>
  <div class="field"><label for="a">LinkedIn Profile</label><input id="a" value="https://linkedin.com/in/x"></div>
  <div class="field"><label for="b">Select 'Yes' to join Braze's Talent Community*</label>
    <select id="b"><option></option></select><p class="helper-text">This field is required.</p></div>
  <div class="field"><label for="c">Will you now or in the future require visa sponsorship?*</label>
    <select id="c"><option></option></select><span class="error">This field is required.</span></div>
</form></body></html>
"""


def _run(html: str):
    async def go():
        from playwright.async_api import async_playwright

        async with async_playwright() as p:
            browser = await p.chromium.launch(headless=True)
            try:
                page = await browser.new_page()
                await page.set_content(html)
                return await _labelled_validation_errors(page)
            finally:
                await browser.close()

    return asyncio.run(go())


def test_each_required_message_is_paired_with_its_field():
    fields = _run(FORM)
    labels = sorted(f["label"] for f in fields)
    assert labels == [
        "Select 'Yes' to join Braze's Talent Community*",
        "Will you now or in the future require visa sponsorship?*",
    ]
    assert all(f["message"] == "This field is required." for f in fields)


def test_a_clean_form_reports_nothing():
    assert _run("<html><body><div class='field'><label>Name</label><input value='A'></div></body></html>") == []
