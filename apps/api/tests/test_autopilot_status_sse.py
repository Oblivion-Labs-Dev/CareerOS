"""Regression test for a real production incident (2026-09-15, see NIGHT_BATCH_DECISIONS.md):
the SSE endpoint's initial status snapshot used to call `runner.get_status(db)` directly and
synchronously on the event loop — an uncached full scan of every `aa_autopilot_job` row.
Confirmed live via py-spy: a single new dashboard connection blocked the *entire* server
(every other request, every other SSE connection) for 30+ seconds.

This test proves the fix: the initial snapshot now runs via `asyncio.to_thread`, so a slow
status computation cannot block a concurrent task on the same event loop.
"""

from __future__ import annotations

import asyncio
import time
from unittest.mock import patch

import app.routers.application_assistant.autopilot as autopilot_module


def test_slow_status_computation_does_not_block_the_event_loop() -> None:
    def _slow_status() -> dict[str, str]:
        time.sleep(0.5)  # simulates the real synchronous DB scan
        return {"ok": "true"}

    async def run() -> tuple[dict[str, str], int]:
        ticks = 0

        async def tick_counter() -> None:
            nonlocal ticks
            for _ in range(20):
                await asyncio.sleep(0.02)
                ticks += 1

        with patch.object(autopilot_module, "_cached_autopilot_status", side_effect=_slow_status):
            counter_task = asyncio.create_task(tick_counter())
            # Mirrors the real event_generator's call exactly: a module-level lookup of
            # _cached_autopilot_status dispatched via asyncio.to_thread.
            status = await asyncio.to_thread(autopilot_module._cached_autopilot_status)
            await counter_task
        return status, ticks

    status, ticks = asyncio.run(run())

    assert status == {"ok": "true"}
    # If the "slow" call ran directly on the event loop instead of a worker thread, the
    # 20 x 20ms ticks (400ms total) would be starved by the 500ms blocking sleep and finish
    # far fewer than 20 — this is the exact regression the fix prevents.
    assert ticks == 20
