"""Tests for fast replay batch fill."""

from __future__ import annotations

from pathlib import Path

import pytest

from app.services.application_assistant.field_fill_engine import fill_page_fast_replay

FIXTURE = Path(__file__).parent / "fixtures" / "greenhouse" / "application_form.html"


def test_fill_page_fast_replay_batch_text_fields() -> None:
    import asyncio

    pytest.importorskip("playwright")
    from playwright.async_api import async_playwright

    async def _run() -> None:
        async with async_playwright() as p:
            browser = await p.chromium.launch(headless=True)
            page = await browser.new_page()
            await page.goto(FIXTURE.as_uri())

            actions = [
                {
                    "type": "fill_field",
                    "selector": "#first_name",
                    "selectorHint": "#first_name",
                    "fieldType": "text",
                    "fieldLabel": "First Name",
                    "value": "Jane",
                },
                {
                    "type": "fill_field",
                    "selector": "#last_name",
                    "selectorHint": "#last_name",
                    "fieldType": "text",
                    "fieldLabel": "Last Name",
                    "value": "Doe",
                },
                {
                    "type": "fill_field",
                    "selector": "#email",
                    "selectorHint": "#email",
                    "fieldType": "email",
                    "fieldLabel": "Email",
                    "value": "jane@example.com",
                },
                {
                    "type": "fill_field",
                    "selector": "#work_auth",
                    "selectorHint": "#work_auth",
                    "fieldType": "select-one",
                    "fieldLabel": "Work auth",
                    "value": "Yes",
                },
            ]

            result = await fill_page_fast_replay(page, actions)
            assert len(result["filled"]) >= 3
            assert await page.input_value("#first_name") == "Jane"
            assert await page.input_value("#last_name") == "Doe"
            assert await page.input_value("#email") == "jane@example.com"
            await browser.close()

    asyncio.run(_run())


def test_fill_page_fast_replay_misclassified_greenhouse_text_fields() -> None:
    import asyncio

    pytest.importorskip("playwright")
    from playwright.async_api import async_playwright

    async def _run() -> None:
        async with async_playwright() as p:
            browser = await p.chromium.launch(headless=True)
            page = await browser.new_page()
            await page.goto(FIXTURE.as_uri())

            actions = [
                {
                    "type": "fill_field",
                    "selector": "#first_name",
                    "fieldType": "select-one",
                    "normalizedKey": "first_name",
                    "value": "Akshay",
                },
                {
                    "type": "fill_field",
                    "selector": "#email",
                    "fieldType": "select-one",
                    "normalizedKey": "email",
                    "value": "ada@example.com",
                },
            ]

            result = await fill_page_fast_replay(page, actions)
            assert len(result["filled"]) == 2
            assert await page.input_value("#first_name") == "Akshay"
            assert await page.input_value("#email") == "ada@example.com"
            await browser.close()

    asyncio.run(_run())
