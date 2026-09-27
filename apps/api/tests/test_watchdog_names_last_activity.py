"""#81: a job that hangs must say what it was doing, not only which coarse
checkpoint it had reached. 46 jobs died with "Timed out after 600s while at
QUESTIONS_COMPLETED" and nothing else to go on."""

import asyncio
from contextlib import contextmanager

from app.db import store
from app.services.application_assistant import autopilot_runner as module
from app.services.application_assistant import job_filter_ranker, persistence, resume_diff_service
from app.services.application_assistant import playwright_autopilot_executor as executor


def test_watchdog_timeout_reports_the_last_activity(monkeypatch, tmp_path):
    runner = module.AutopilotRunner()
    job = {"id": "hang81", "company": "Example", "title": "Senior Engineer",
           "tailoringMode": "off", "matchScore": 90, "manualMatchOverride": True}

    @contextmanager
    def session():
        yield None

    async def generate(*args, mode, **kwargs):
        return {"matchScore": 90, "totalChanges": 0, "tailoringFailed": False,
                "quality": {"ok": True, "changed": 0, "total": 1, "problems": []}, "missingSkills": []}

    async def hanging_submit(**kwargs):
        kwargs["log_callback"]("Auto-healing 13 field(s) (Round 1)...", "warning")
        await asyncio.sleep(3600)

    monkeypatch.setattr(module, "PLAYWRIGHT_WATCHDOG_TIMEOUT", 0.2)
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
    monkeypatch.setattr(executor, "execute_live_playwright_submission", hanging_submit)

    asyncio.run(runner._execute_application_pipeline("run", job))

    assert "Timed out after" in (job.get("lastError") or "")
    assert "Auto-healing 13 field(s)" in job["lastError"]
    assert any("Auto-healing 13 field(s)" in e["message"] and e["level"] == "error" for e in runner.activity_log)
