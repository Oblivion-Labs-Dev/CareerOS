"""Regression test for a real, repeated incident (2026-09-15, see NIGHT_BATCH_DECISIONS.md):
`_fill_all_greenhouse_comboboxes` inherits the page's whole-job default timeout (hundreds of
seconds) on every individual Playwright RPC call. When the browser's IPC connection goes
unresponsive mid-field (confirmed live via py-spy three times in one night), a single
`.count()`/`.evaluate()` call hung indefinitely instead of failing fast, starving the entire
job until the much-larger outer job-level watchdog eventually fired.

This test simulates exactly that: a fake Locator whose `.count()` never returns, and asserts
the function still completes well under its own per-field timeout instead of hanging.
"""

from __future__ import annotations

import asyncio
import time

import pytest

from app.services.application_assistant.playwright_autopilot_executor import (
    _fill_all_greenhouse_comboboxes,
)


class _HangingLocator:
    """Mimics a Playwright Locator whose RPC to the browser never returns —
    the exact live signature caught via py-spy (idle inside the IPC send/receive)."""

    def __init__(self) -> None:
        self.first = self

    async def count(self) -> int:
        await asyncio.sleep(3600)
        return 0


class _FakePage:
    async def eval_on_selector_all(self, selector: str, script: str) -> list[str]:
        return ["field-1"]

    def locator(self, selector: str) -> _HangingLocator:
        return _HangingLocator()


def test_hung_combobox_field_does_not_hang_the_whole_function() -> None:
    async def run() -> tuple[dict[str, str], dict[str, str]]:
        # Outer bound is a safety net for the TEST itself, well above the function's own
        # ~15s per-field timeout — if the fix regresses, this fires and fails the test
        # loudly instead of hanging the suite for an hour.
        return await asyncio.wait_for(
            _fill_all_greenhouse_comboboxes(_FakePage(), profile={}, answer_lib=[]),
            timeout=20.0,
        )

    start = time.monotonic()
    filled, filled_ids = asyncio.run(run())
    elapsed = time.monotonic() - start

    assert filled == {}
    assert filled_ids == {}
    # Must recover via its own per-field timeout (~15s), not the test's 20s outer bound.
    assert elapsed < 18.0, f"took {elapsed:.1f}s — the per-field timeout may not be firing"
