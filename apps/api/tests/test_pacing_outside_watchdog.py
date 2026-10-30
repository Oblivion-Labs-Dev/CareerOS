"""The submission gap must never be charged against the per-job watchdog.

Regression: the whole 300s gap was waited out in the click-time hook, inside
the 600s watchdog. A sequential batch hits that wait on almost every job, so
the watchdog fired after the click and real submissions were parked as
SUBMISSION_UNKNOWN. Most of the gap is now waited before the browser opens.
"""

import asyncio
from contextlib import contextmanager
from datetime import datetime, timezone

from app.db import store
from app.services.application_assistant import autopilot_runner as module
from app.services.application_assistant import job_filter_ranker, persistence, resume_diff_service
from app.services.application_assistant import playwright_autopilot_executor as executor
from app.services.application_assistant import submission_pacing


def test_pre_open_wait_leaves_only_the_headroom_for_click_time():
    now = datetime(2026, 10, 30, 12, 0, 0, tzinfo=timezone.utc)
    just_now = now.isoformat()
    assert submission_pacing.seconds_to_wait_before_opening(just_now, now=now) == (
        submission_pacing.MIN_SUBMISSION_GAP_SECONDS
        - submission_pacing.CLICK_TIME_WAIT_HEADROOM_SECONDS
    )
    assert submission_pacing.seconds_to_wait_before_opening(None, now=now) == 0.0


def test_a_pending_gap_does_not_time_out_the_submission(monkeypatch, tmp_path):
    # Scaled down: a 1.2s gap against a 0.5s watchdog. Waited entirely at
    # click time (the old behaviour) it always overran the watchdog.
    monkeypatch.setattr(submission_pacing, "MIN_SUBMISSION_GAP_SECONDS", 1.2)
    monkeypatch.setattr(submission_pacing, "CLICK_TIME_WAIT_HEADROOM_SECONDS", 0.2)
    monkeypatch.setattr(module, "CLICK_TIME_WAIT_HEADROOM_SECONDS", 0.2, raising=False)
    monkeypatch.setattr(module, "PLAYWRIGHT_WATCHDOG_TIMEOUT", 0.5)
    last_submission = datetime.now(timezone.utc).isoformat()
    monkeypatch.setattr(module, "most_recent_submit_attempt", lambda *a, **k: last_submission)

    runner = module.AutopilotRunner()
    job = {"id": "pace_watchdog", "company": "Example", "title": "Senior Engineer",
           "tailoringMode": "off", "matchScore": 90, "manualMatchOverride": True}
    clicked = {}

    @contextmanager
    def session():
        yield None

    async def generate(*args, mode, **kwargs):
        return {"matchScore": 90, "totalChanges": 0, "tailoringFailed": False,
                "quality": {"ok": True, "changed": 0, "total": 1, "problems": []}, "missingSkills": []}

    async def submit(**kwargs):
        await kwargs["on_submit_attempt"]()
        clicked["at"] = datetime.now(timezone.utc)
        return {"submitted": False, "error": "Submission unconfirmed", "evidence": {}}

    monkeypatch.setattr(module, "session_scope", session)
    monkeypatch.setattr(module, "save_autopilot_job", lambda *args: None)
    monkeypatch.setattr(module, "get_autopilot_run", lambda *args: None)
    monkeypatch.setattr(persistence, "list_answer_library", lambda *args: [])
    monkeypatch.setattr(persistence, "get_settings", lambda *args: {})
    monkeypatch.setattr(store, "get_kv", lambda *args: {})
    monkeypatch.setattr(store, "get_entity", lambda *args: None)
    monkeypatch.setattr(module, "__file__", str(tmp_path / "app/services/application_assistant/autopilot_runner.py"))
    monkeypatch.setattr(job_filter_ranker, "evaluate_hard_filters", lambda *args: (True, ""))
    monkeypatch.setattr(resume_diff_service, "generate_role_tailoring_diff", generate)
    monkeypatch.setattr(executor, "execute_live_playwright_submission", submit)

    asyncio.run(runner._execute_application_pipeline("run", job))

    assert "Timed out after" not in (job.get("lastError") or "")
    assert job.get("submitAttemptedAt")
    # The gap itself is still honoured.
    gap = (clicked["at"] - datetime.fromisoformat(last_submission)).total_seconds()
    assert gap >= 1.2 - 0.05
