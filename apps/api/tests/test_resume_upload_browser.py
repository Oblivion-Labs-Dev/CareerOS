"""Opt-in local browser regression; never opens an employer site."""
import asyncio
import os

import pytest

from app.services.application_assistant.playwright_autopilot_executor import _fill_standard_and_react_fields


@pytest.mark.skipif(os.getenv("CAREEROS_BROWSER_TESTS") != "1", reason="Requires local Chromium")
def test_resume_input_removed_after_upload_does_not_stall(tmp_path):
    from playwright.async_api import async_playwright

    resume = tmp_path / "candidate.pdf"
    resume.write_bytes(b"%PDF-1.4\n%%EOF")

    async def run():
        async with async_playwright() as playwright:
            browser = await playwright.chromium.launch(headless=True)
            try:
                page = await browser.new_page()
                page.set_default_timeout(10_000)
                await page.set_content('<input type="file" name="resume" onchange="this.remove()">')
                filled, _ = await asyncio.wait_for(
                    _fill_standard_and_react_fields(page, {}, [], "Example", "Engineer", str(resume)),
                    timeout=5,
                )
                assert filled["Resume"] == "candidate.pdf"
                assert await page.locator('input[type="file"]').count() == 0
            finally:
                await browser.close()

    asyncio.run(run())
