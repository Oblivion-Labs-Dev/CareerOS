"""#74: a queue row that already carries its source's match is not rewritten,
so the preprocessor loop can go idle instead of re-scanning every table each
second."""

from __future__ import annotations

from app.db.store import session_scope
from app.services.application_assistant.persistence import (
    delete_autopilot_job,
    save_autopilot_job,
    upsert_discovered_job,
)
from app.services.application_assistant.queue_preprocessor import QueuePreprocessor

MATCH = {
    "matchScore": 81.0,
    "matchReason": "strong backend fit",
    "keyMatchingSkills": ["python"],
    "missingSkills": [],
    "matchMethod": "mistral-ollama",  # anything but "ollama-local" triggered #74
    "matchModel": "mistral",
}


def test_second_sync_on_unchanged_data_does_nothing():
    with session_scope() as db:
        upsert_discovered_job(db, {"id": "aa_idle74", "company": "Acme", "title": "Senior Software Engineer",
                                   "applicationUrl": "https://boards.greenhouse.io/acme/jobs/74",
                                   "mistralMatch": MATCH})
        save_autopilot_job(db, {"id": "apjob_idle74", "jobId": "aa_idle74", "status": "QUEUED",
                                "company": "Acme", "title": "Senior Software Engineer",
                                "applicationUrl": "https://boards.greenhouse.io/acme/jobs/74",
                                "matchScore": 40.0, "matchMethod": "heuristic"})
    try:
        preprocessor = QueuePreprocessor()
        assert preprocessor._sync_queue_match_scores() >= 1
        assert preprocessor._sync_queue_match_scores() == 0
    finally:
        with session_scope() as db:
            delete_autopilot_job(db, "apjob_idle74")


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
