"""Autopilot's match floor gates every auto-apply, and Autopilot never tailors.

Owner decision, 2026-11-01: resume tailoring is a manual step only, and the
minimum match score (default 60) gates every automatic submission whatever the
configured tailoring mode. Before this, a run with tailoring "off" bypassed the
floor entirely (worklist F9) and submitted 37-45% matches.
"""
import asyncio
from contextlib import contextmanager

import pytest

from app.db import store
from app.services.application_assistant import autopilot_runner as module
from app.services.application_assistant import job_filter_ranker, persistence, resume_diff_service
from app.services.application_assistant import playwright_autopilot_executor as executor


class EmployerReached(Exception):
    pass


def _run(monkeypatch, tmp_path, *, score, tailoring_mode, override=False, floor=60.0):
    runner = module.AutopilotRunner()
    runner.min_match_score = floor
    job = {
        "id": "floor-test",
        "company": "Example",
        "title": "Engineer",
        "tailoringMode": tailoring_mode,
        "matchScore": score,
        "manualMatchOverride": override,
    }
    tailored = []

    @contextmanager
    def session():
        yield None

    async def generate(*args, **kwargs):
        tailored.append(kwargs.get("mode"))
        return {"matchScore": 99, "quality": {"ok": True, "changed": 9}}

    async def submit(**kwargs):
        raise EmployerReached

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

    reached = False
    try:
        asyncio.run(runner._execute_application_pipeline("run", job))
    except EmployerReached:
        reached = True
    return job, reached, tailored


def test_default_floor_is_60():
    assert module.MIN_MATCH_SCORE_TO_SUBMIT == 60.0


@pytest.mark.parametrize("tailoring_mode", ["off", "honest", "aggressive"])
def test_below_floor_is_held_and_never_tailored(monkeypatch, tmp_path, tailoring_mode):
    job, reached, tailored = _run(monkeypatch, tmp_path, score=45, tailoring_mode=tailoring_mode)
    assert not reached, "a below-floor match must never reach the employer"
    assert tailored == []
    assert job["status"] == "NEEDS_REVIEW"
    assert "below the 60% floor" in job["skipReason"]


@pytest.mark.parametrize("tailoring_mode", ["off", "honest"])
def test_at_or_above_floor_submits_master_resume_untailored(monkeypatch, tmp_path, tailoring_mode):
    job, reached, tailored = _run(monkeypatch, tmp_path, score=60, tailoring_mode=tailoring_mode)
    assert reached
    assert tailored == []
    assert job["tailoringMode"] == "off"


def test_explicit_apply_below_floor_submits_without_tailoring(monkeypatch, tmp_path):
    job, reached, tailored = _run(monkeypatch, tmp_path, score=45, tailoring_mode="honest", override=True)
    assert reached
    assert tailored == []


def test_run_floor_overrides_default(monkeypatch, tmp_path):
    job, reached, _ = _run(monkeypatch, tmp_path, score=75, tailoring_mode="off", floor=80.0)
    assert not reached
    assert "below the 80% floor" in job["skipReason"]
