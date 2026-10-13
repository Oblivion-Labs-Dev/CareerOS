"""The runner, not the queue, keeps a posting the hard filters reject from being applied to.

The queue keeps every non-duplicate posting (#59), so a rejection the
ineligibility classifier does not recognise must still end as a soft SKIP here.
Mid-level software titles are applied to, so an aggregator listing URL
stands in for the rejection.
"""

import asyncio
from contextlib import contextmanager

import pytest

from app.db import store
from app.services.application_assistant import autopilot_runner as module
from app.services.application_assistant import playwright_autopilot_executor as executor
from app.services.application_assistant import resume_diff_service


def test_a_hard_filter_rejection_is_skipped_not_applied(monkeypatch):
    saved = []

    @contextmanager
    def session():
        yield None

    async def never(*args, **kwargs):
        pytest.fail("A posting the hard filters reject must not be tailored or submitted")

    monkeypatch.setattr(module, "session_scope", session)
    monkeypatch.setattr(module, "save_autopilot_job", lambda db, job: saved.append(dict(job)))
    monkeypatch.setattr(module, "get_autopilot_run", lambda *args: None)
    monkeypatch.setattr(store, "get_kv", lambda *args: {})
    monkeypatch.setattr(resume_diff_service, "generate_role_tailoring_diff", never)
    monkeypatch.setattr(executor, "execute_live_playwright_submission", never)

    job = {
        "id": "apjob_level",
        "company": "Example",
        "title": "Senior Software Engineer",
        "location": "Seattle, WA",
        "applicationUrl": "https://www.linkedin.com/jobs/view/123456",
        "status": "QUEUED",
    }
    asyncio.run(module.AutopilotRunner()._execute_application_pipeline("run", job))

    assert job["status"] == "SKIPPED"
    assert "aggregator listing page" in job["skipReason"]
    assert saved and saved[-1]["status"] == "SKIPPED"
