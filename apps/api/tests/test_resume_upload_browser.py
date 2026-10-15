"""Opt-in local browser regression; never opens an employer site."""
import asyncio
import os

import pytest

from app.services.application_assistant.playwright_autopilot_executor import _fill_standard_and_react_fields
from tests.browser_test_utils import eval_in_pooled_page


@pytest.mark.skipif(os.getenv("CAREEROS_BROWSER_TESTS") != "1", reason="Requires local Chromium")
def test_resume_input_removed_after_upload_does_not_stall(tmp_path):
    resume = tmp_path / "candidate.pdf"
    resume.write_bytes(b"%PDF-1.4\n%%EOF")

    async def _action(page):
        filled, _ = await asyncio.wait_for(
            _fill_standard_and_react_fields(page, {}, [], "Example", "Engineer", str(resume)),
            timeout=5,
        )
        assert filled["Resume"] == "candidate.pdf"
        assert await page.locator('input[type="file"]').count() == 0

    eval_in_pooled_page(
        '<input type="file" name="resume" onchange="this.remove()">',
        _action,
        timeout=10,
    )

