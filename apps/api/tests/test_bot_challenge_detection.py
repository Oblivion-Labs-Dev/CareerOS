"""A bot challenge counts only when one is actually being presented.

The detector this covers decides whether a failed submission is reported as
"bot protection blocked this" — an unfixable dead end that classifies as
BOT_PROTECTED_BOARD — or keeps its real reason. Getting that backwards buries a
live posting.

The old test matched /g-recaptcha|grecaptcha/ against document.innerHTML.
Greenhouse embeds reCAPTCHA on every board, so it was true for every Greenhouse
posting. Measured on the live queue: 56 Cloudflare applications were filed as
"reCAPTCHA bot protection blocked the submission" while their stored evidence
said "Page contains active validation errors: This field is required."

These run the real JS in a real Chromium, because the whole question is one of
computed layout and visibility — a string assertion would prove nothing.
"""

from __future__ import annotations

import asyncio

import pytest

from app.services.application_assistant.playwright_autopilot_executor import (
    _VISIBLE_BOT_CHALLENGE_JS,
)

pytestmark = pytest.mark.usefixtures("initialize_database")


def _detect(html: str) -> str:
    """Render `html` in Chromium and run the detector against it."""

    async def _run() -> str:
        from playwright.async_api import async_playwright

        async with async_playwright() as p:
            browser = await p.chromium.launch(headless=True)
            try:
                page = await browser.new_page(viewport={"width": 1280, "height": 900})
                await page.set_content(html)
                return await page.evaluate(_VISIBLE_BOT_CHALLENGE_JS)
            finally:
                await browser.close()

    return asyncio.run(_run())


# A stand-in for what Greenhouse actually serves: the reCAPTCHA script is on the
# page and the v3 badge is rendered, but nothing is being asked of the user.
GREENHOUSE_LIKE = """
<html><body>
  <form><label>Are you fluent in English?*</label><select><option></option></select>
    <button type="submit">Submit application</button></form>
  <script src="https://www.google.com/recaptcha/api.js"></script>
  <div class="grecaptcha-badge" style="width:256px;height:60px">
    <iframe src="https://www.google.com/recaptcha/api2/anchor" style="width:256px;height:60px"></iframe>
  </div>
  <div class="g-recaptcha" data-sitekey="abc" style="display:none"></div>
</body></html>
"""

INVISIBLE_V3 = """
<html><body>
  <form><button type="submit">Submit</button></form>
  <iframe src="https://www.google.com/recaptcha/api2/bframe" width="1" height="1"></iframe>
  <script>window.grecaptcha = {};</script>
</body></html>
"""

PRESENTED_CHECKBOX = """
<html><body>
  <form><button type="submit">Submit</button></form>
  <iframe src="https://www.google.com/recaptcha/api2/anchor" style="width:304px;height:78px"></iframe>
</body></html>
"""

PRESENTED_TURNSTILE = """
<html><body>
  <div class="cf-turnstile" style="width:300px;height:65px"></div>
</body></html>
"""

PRESENTED_TEXT = """
<html><body><div style="width:400px;height:200px">
  <h2>Verify you are human</h2><p>Complete the security check to continue.</p>
</div></body></html>
"""


def test_embedded_recaptcha_on_a_working_board_is_not_a_challenge():
    """The regression. Greenhouse embeds reCAPTCHA on every posting."""
    assert _detect(GREENHOUSE_LIKE) == ""


def test_the_v3_badge_alone_is_not_a_challenge():
    """The badge is always visible on v3 boards and asks the user for nothing."""
    assert _detect(INVISIBLE_V3) == ""


def test_a_presented_checkbox_is_a_challenge():
    assert _detect(PRESENTED_CHECKBOX) == "reCAPTCHA"


def test_a_presented_turnstile_widget_is_a_challenge():
    assert _detect(PRESENTED_TURNSTILE) == "Cloudflare Turnstile"


def test_visible_human_verification_wording_is_a_challenge():
    assert _detect(PRESENTED_TEXT) == "CAPTCHA"


def test_an_ordinary_application_form_is_not_a_challenge():
    assert _detect("<html><body><form><input name=name><button>Submit</button></form></body></html>") == ""
