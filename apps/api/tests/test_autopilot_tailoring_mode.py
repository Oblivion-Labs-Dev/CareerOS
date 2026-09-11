import asyncio
from contextlib import contextmanager

import pytest

from app.db import store
from app.services.application_assistant import autopilot_runner as module
from app.services.application_assistant import job_filter_ranker, persistence, resume_diff_service
from app.services.application_assistant import playwright_autopilot_executor as executor


@pytest.mark.parametrize("stop_during_generation", [False, True])
@pytest.mark.parametrize("manual_override", [False, True])
def test_low_match_respects_explicit_apply_and_stop(monkeypatch, stop_during_generation, manual_override):
    runner = module.AutopilotRunner()
    modes = []
    # matchScore puts this job in the "honest" tailoring band (60 <= score < 80).
    # Tailoring strength is now chosen from the pre-tailoring score rather than
    # taken verbatim from the operator's setting; this test is about low-match
    # gating, so it pins the band it expects instead of asserting the old
    # "whatever the operator picked" contract.
    job = {
        "id": "test",
        "company": "Example",
        "title": "Engineer",
        "tailoringMode": "honest",
        "matchScore": 70,
    }
    job["manualMatchOverride"] = manual_override

    class EmployerReached(Exception):
        pass

    @contextmanager
    def session():
        yield None

    async def generate(*args, mode, **kwargs):
        modes.append(mode)
        runner._stop_requested = stop_during_generation
        # A low score with a genuinely tailored, submittable document: the point
        # of this test is that the *score* gate holds, so the quality gate must
        # not be what stops it or the test would pass for the wrong reason.
        return {
            "matchScore": 51,
            "totalChanges": 6,
            "tailoringFailed": False,
            "quality": {"ok": True, "changed": 6, "total": 17, "problems": []},
            "missingSkills": [],
        }

    async def submit(**kwargs):
        if manual_override and not stop_during_generation:
            raise EmployerReached
        pytest.fail("Low-match or stopped job must not reach employer")

    def render(*args):
        raise ValueError("Use the saved resume in this isolated test")

    monkeypatch.setattr(module, "session_scope", session)
    monkeypatch.setattr(module, "save_autopilot_job", lambda *args: None)
    monkeypatch.setattr(module, "get_autopilot_run", lambda *args: None)
    monkeypatch.setattr(persistence, "list_answer_library", lambda *args: [])
    monkeypatch.setattr(persistence, "get_settings", lambda *args: {})
    monkeypatch.setattr(store, "get_kv", lambda *args: {})
    monkeypatch.setattr(job_filter_ranker, "evaluate_hard_filters", lambda *args: (True, ""))
    monkeypatch.setattr(resume_diff_service, "generate_role_tailoring_diff", generate)
    monkeypatch.setattr(resume_diff_service, "render_tailored_resume_pdf", render)
    monkeypatch.setattr(executor, "execute_live_playwright_submission", submit)
    if manual_override and not stop_during_generation:
        with pytest.raises(EmployerReached):
            asyncio.run(runner._execute_application_pipeline("run", job))
    else:
        asyncio.run(runner._execute_application_pipeline("run", job))
    assert modes == ["honest"]
    assert job["tailoringMode"] == "honest"
    if stop_during_generation or not manual_override:
        assert job["status"] == ("QUEUED" if stop_during_generation else "SKIPPED")
