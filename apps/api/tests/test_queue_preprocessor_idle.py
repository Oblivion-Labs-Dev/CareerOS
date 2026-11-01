"""The queue preprocessor stays out of the way while the queue is full.

The #74 idle check (a second re-score pass on unchanged data does nothing) now
lives in test_role_shape_match, since the role-shape rescorer replaced the local
model sync it was written for.
"""

from __future__ import annotations

from app.services.application_assistant.queue_preprocessor import QueuePreprocessor


def test_no_background_scrape_while_the_queue_is_over_its_cap(monkeypatch):
    """#78: a scrape slows the API for its whole duration; skip it at capacity."""
    import asyncio

    from app.services.application_assistant import queue_preprocessor as qp
    from app.services.job_discover import store as jd_store

    started = []

    async def fake_start(**kwargs):
        started.append(kwargs)
        return {"success": True}

    monkeypatch.setattr(jd_store, "start_scrape_background", fake_start)
    preprocessor = QueuePreprocessor()

    monkeypatch.setattr(preprocessor, "_queued_count", lambda: qp.HIGH_QUEUE_WATERMARK)
    preprocessor._last_scrape_at = -1e9
    asyncio.run(preprocessor._maybe_start_scrape())
    assert started == []

    monkeypatch.setattr(preprocessor, "_queued_count", lambda: qp.LOW_QUEUE_WATERMARK)
    preprocessor._last_scrape_at = -1e9
    asyncio.run(preprocessor._maybe_start_scrape())
    assert len(started) == 1
