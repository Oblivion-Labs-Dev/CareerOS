"""Regression: a missing Playwright browser must pause the run, not fail every job.

Found live on 2026-10-28: another project's newer Playwright install pruned the
chromium_headless_shell build this API pins. Every launch then raised
"Executable doesn't exist", which classified as a transient BROWSER_CRASH, burned
three attempts and filed the posting as NEEDS_REVIEW. The run kept claiming jobs
for five hours and parked 711 healthy postings in review before anyone noticed.
"""

import asyncio
from contextlib import contextmanager

from app.services.application_assistant import autopilot_runner as module
from app.services.application_assistant import company_cap, persistence

MISSING = (
    "BrowserType.launch: Executable doesn't exist at C:\\Users\\x\\AppData\\Local\\"
    "ms-playwright\\chromium_headless_shell-1228\\chrome-headless-shell-win64\\"
    "chrome-headless-shell.exe\nLooks like Playwright was just installed or updated."
)


def test_missing_browser_executable_requeues_job_and_pauses_run(monkeypatch):
    saved_jobs = []
    run = {"id": "run", "status": "RUNNING"}

    @contextmanager
    def session():
        yield None

    monkeypatch.setattr(module, "session_scope", session)
    monkeypatch.setattr(module, "save_autopilot_job", lambda db, job: saved_jobs.append(dict(job)))
    monkeypatch.setattr(module, "get_autopilot_run", lambda db, run_id: run)
    monkeypatch.setattr(module, "save_autopilot_run", lambda db, r: run.update(r))
    monkeypatch.setattr(module, "claim_application_identity", lambda *a, **k: True)
    monkeypatch.setattr(module, "release_application_identity", lambda *a, **k: None)
    real_sleep = asyncio.sleep
    monkeypatch.setattr(module.asyncio, "sleep", lambda *a, **k: real_sleep(0))
    monkeypatch.setattr(persistence, "is_strict_duplicate_processed", lambda *a, **k: (False, None, None))
    monkeypatch.setattr(persistence, "list_submitted_duplicate_candidates", lambda *a, **k: [])
    monkeypatch.setattr(persistence, "list_autopilot_jobs", lambda *a, **k: [])
    monkeypatch.setattr(company_cap, "company_hold", lambda *a, **k: None)

    calls = []

    async def failing_pipeline(run_id, job_item, worker_state=None):
        calls.append(job_item.get("attemptCount"))
        raise RuntimeError(MISSING)

    runner = module.AutopilotRunner()
    monkeypatch.setattr(runner, "_execute_application_pipeline", failing_pipeline)

    job = {
        "id": "apjob_healthy",
        "company": "Acme",
        "title": "Senior Software Engineer",
        "applicationUrl": "https://job-boards.greenhouse.io/acme/jobs/1",
        "status": "QUEUED",
        "attemptCount": 0,
    }

    asyncio.run(runner._process_single_job_with_retries("run", job))

    assert calls == [1], "a missing browser is not transient: it must not be retried"
    final = saved_jobs[-1]
    assert final["status"] == "QUEUED"
    assert final["attemptCount"] == 0, "the job never got a real attempt"
    assert run["status"] == "PAUSED"
    assert "playwright install" in (run.get("pauseReason") or "")
