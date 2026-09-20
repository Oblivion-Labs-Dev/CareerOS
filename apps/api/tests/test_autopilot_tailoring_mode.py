import asyncio
from contextlib import contextmanager

import pytest

from app.db import store
from app.services.application_assistant import autopilot_runner as module
from app.services.application_assistant import job_filter_ranker, persistence, resume_diff_service
from app.services.application_assistant import playwright_autopilot_executor as executor


@pytest.mark.parametrize("stop_during_generation", [False, True])
@pytest.mark.parametrize("manual_override", [False, True])
@pytest.mark.parametrize("render_fails", [False, True])
def test_low_match_respects_explicit_apply_and_stop(monkeypatch, tmp_path, stop_during_generation, manual_override, render_fails):
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
        if manual_override and not stop_during_generation and not render_fails:
            raise EmployerReached
        pytest.fail("Low-match, stopped, or failed-render job must not reach employer")

    def render(*args):
        if render_fails:
            raise ValueError("Controlled render failure")
        import pymupdf
        with pymupdf.open() as document:
            document.new_page().insert_text((36,36),'Synthetic tailored resume')
            return document.tobytes()

    monkeypatch.setattr(module, "session_scope", session)
    monkeypatch.setattr(module, "save_autopilot_job", lambda *args: None)
    monkeypatch.setattr(module, "get_autopilot_run", lambda *args: None)
    monkeypatch.setattr(persistence, "list_answer_library", lambda *args: [])
    monkeypatch.setattr(persistence, "get_settings", lambda *args: {})
    monkeypatch.setattr(store, "get_kv", lambda *args: {})
    monkeypatch.setattr(store, "get_entity", lambda *args: None)
    # The runner writes rendered documents relative to this module. Keep every
    # test artifact in pytest's temporary tree, never the user's resume folder.
    monkeypatch.setattr(module, "__file__", str(tmp_path / 'app/services/application_assistant/autopilot_runner.py'))
    monkeypatch.setattr(job_filter_ranker, "evaluate_hard_filters", lambda *args: (True, ""))
    monkeypatch.setattr(resume_diff_service, "generate_role_tailoring_diff", generate)
    monkeypatch.setattr(resume_diff_service, "render_tailored_resume_pdf", render)
    monkeypatch.setattr(executor, "execute_live_playwright_submission", submit)
    if manual_override and not stop_during_generation and not render_fails:
        with pytest.raises(EmployerReached):
            asyncio.run(runner._execute_application_pipeline("run", job))
    else:
        asyncio.run(runner._execute_application_pipeline("run", job))
    assert modes == ["honest"]
    assert job["tailoringMode"] == "honest"
    if stop_during_generation or not manual_override or render_fails:
        assert job["status"] == ("QUEUED" if stop_during_generation else "NEEDS_REVIEW")
    if render_fails and manual_override and not stop_during_generation:
        assert job['resumeTailoringFailed'] is True
