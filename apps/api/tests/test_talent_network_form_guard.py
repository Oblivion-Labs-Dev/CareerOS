"""A Radancy talent-network signup is not an application form.

NetApp's, Sony Pictures', Jack Henry's and Unifirst's posting pages carry a
job-alert signup (name, email, keyword + location, posted to /form/submit),
which the runner filled as if it were the application.
"""

from __future__ import annotations

import asyncio

from app.services.application_assistant.playwright_autopilot_executor import (
    _only_talent_network_forms,
)

SEL = '#first_name, #email, input[id*="first_name" i], input[name*="first_name" i], input[name*="last_name" i]'

RADANCY = """
<form action="https://careers.example.com/form/submit" data-form>
  <input id="form-field-1-first_name" name="first_name"><input name="last_name">
  <input class="keyword-location" data-keyword-list="kw" name="Location">
</form>
"""

GREENHOUSE = """
<form id="application-form" action="/apply">
  <input id="first_name"><input id="email">
  <label><input type="checkbox"> Join our talent community</label>
</form>
"""


def _talent_only(html: str) -> bool:
    async def go():
        from playwright.async_api import async_playwright

        async with async_playwright() as p:
            browser = await p.chromium.launch(headless=True)
            try:
                page = await browser.new_page()
                await page.set_content(f"<html><body>{html}</body></html>")
                return await _only_talent_network_forms(page, SEL)
            finally:
                await browser.close()

    return asyncio.run(go())


def test_radancy_job_alert_signup_is_not_an_application():
    assert _talent_only(RADANCY)


def test_a_real_application_form_is_kept():
    assert not _talent_only(GREENHOUSE)


def test_an_application_beside_a_signup_is_kept():
    assert not _talent_only(RADANCY + GREENHOUSE)
