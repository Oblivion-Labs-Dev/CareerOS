"""#59: the runner, not the queue, keeps non-Senior/Staff/Principal roles from being applied to."""

import asyncio
from contextlib import contextmanager

import pytest

from app.db import store
from app.services.application_assistant import autopilot_runner as module
from app.services.application_assistant import playwright_autopilot_executor as executor
from app.services.application_assistant import resume_diff_service


def test_a_queued_role_below_senior_is_skipped_not_applied(monkeypatch):
    saved = []

    @contextmanager
    def session():
        yield None

    async def never(*args, **kwargs):
        pytest.fail("A role below Senior must not be tailored or submitted")

    monkeypatch.setattr(module, "session_scope", session)
    monkeypatch.setattr(module, "save_autopilot_job", lambda db, job: saved.append(dict(job)))
    monkeypatch.setattr(module, "get_autopilot_run", lambda *args: None)
    monkeypatch.setattr(store, "get_kv", lambda *args: {})
    monkeypatch.setattr(resume_diff_service, "generate_role_tailoring_diff", never)
    monkeypatch.setattr(executor, "execute_live_playwright_submission", never)

    job = {
        "id": "apjob_level",
        "company": "Example",
        "title": "Software Engineer II",
        "location": "Seattle, WA",
        "applicationUrl": "https://job-boards.greenhouse.io/example/jobs/123456",
        "status": "QUEUED",
    }
    asyncio.run(module.AutopilotRunner()._execute_application_pipeline("run", job))

    assert job["status"] == "SKIPPED"
    assert "not a Senior, Staff or Principal software role" in job["skipReason"]
    assert saved and saved[-1]["status"] == "SKIPPED"
