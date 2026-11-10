"""Regression: a missing resume file must pause the run, never submit without one.

Found live 2026-11-03: the resume folder moved from D:\3 - Resources to
D:\2 - Areas, the configured resume path stopped existing, get_active_resume_path
returned "" and 26 applications went out with no resume ("Resume/CV is required").
"""
import asyncio
from contextlib import contextmanager

from app.services.application_assistant import autopilot_runner as module
from app.services.application_assistant import company_cap, persistence

from tests.test_autopilot_floor_gate import _run


def test_pipeline_refuses_to_submit_without_a_resume(monkeypatch, tmp_path):
    raised = None
    try:
        _run(monkeypatch, tmp_path, score=75, tailoring_mode="off", resume=False)
    except module.ResumeMissingError as exc:
        raised = exc
    assert raised is not None, "the employer must never be reached without a resume"


def test_pipeline_submits_when_resume_exists(monkeypatch, tmp_path):
    job, reached, _ = _run(monkeypatch, tmp_path, score=75, tailoring_mode="off")
    assert reached
    assert job["resumeFileUsed"] == "resume.pdf"


def test_missing_resume_requeues_job_and_pauses_run(monkeypatch):
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

    async def pipeline(run_id, job_item, worker_state=None):
        calls.append(1)
        raise module.ResumeMissingError()

    runner = module.AutopilotRunner()
    monkeypatch.setattr(runner, "_execute_application_pipeline", pipeline)
    job = {
        "id": "apjob_x", "company": "Acme", "title": "Senior Software Engineer",
        "applicationUrl": "https://job-boards.greenhouse.io/acme/jobs/1",
        "status": "QUEUED", "attemptCount": 0,
    }

    asyncio.run(runner._process_single_job_with_retries("run", job))

    assert calls == [1], "a missing resume is not transient: it must not be retried"
    assert saved_jobs[-1]["status"] == "QUEUED"
    assert saved_jobs[-1]["attemptCount"] == 0
    assert run["status"] == "PAUSED"
    assert "resume" in (run.get("pauseReason") or "").lower()
