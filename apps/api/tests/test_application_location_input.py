"""The location pass fills the application's field, not the site's job search.

Jack Henry's and Unifirst's posting pages carry a job-search "Location" box
(class="search-location"), which was typed into twice ("Auburn, WAAuburn, WA").
Runs the selector in Chromium: complex :not() support is the browser's.
"""

from __future__ import annotations

import asyncio

from app.services.application_assistant.playwright_autopilot_executor import (
    _APPLICATION_LOCATION_INPUT,
)

PAGE = """
<html><body>
  <form action="/search-jobs"><label for="search-location-1">Location</label>
    <input type="text" id="search-location-1" class="search-location" name="l"></form>
  <div role="search"><input id="header-location" name="location"></div>
  <form id="application">
    <label for="candidate-location">Location (City)</label><input id="candidate-location">
  </form>
</body></html>
"""


def _matched_ids(html: str) -> list[str]:
    async def go():
        from playwright.async_api import async_playwright

        async with async_playwright() as p:
            browser = await p.chromium.launch(headless=True)
            try:
                page = await browser.new_page()
                await page.set_content(html)
                return await page.locator(_APPLICATION_LOCATION_INPUT).evaluate_all(
                    "els => els.map(e => e.id)"
                )
            finally:
                await browser.close()

    return asyncio.run(go())


def test_only_the_application_location_field_matches():
    assert _matched_ids(PAGE) == ["candidate-location"]


def test_a_page_with_only_a_job_search_box_matches_nothing():
    html = '<form action="/search-jobs"><input id="search-location-1" class="search-location" name="l"></form>'
    assert _matched_ids(html) == []
