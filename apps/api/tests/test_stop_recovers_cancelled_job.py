"""A stop that has to cancel the batch loop must not leave the job it was
working on stuck in APPLYING."""

from __future__ import annotations

import asyncio

import pytest

from app.db.store import session_scope
from app.services.application_assistant import autopilot_runner as module
from app.services.application_assistant.persistence import (
    delete_autopilot_job,
    get_autopilot_job,
    save_autopilot_job,
)

_created: list[str] = []


@pytest.fixture(autouse=True)
def remove_seeded_jobs():
    """The suite shares one database, and other tests read submit stamps across it."""
    yield
    with session_scope() as db:
        while _created:
            delete_autopilot_job(db, _created.pop())


def _applying_job(**extra) -> str:
    with session_scope() as db:
        job_id = save_autopilot_job(db, {
            "company": "Stop Co", "title": "Software Engineer", "status": "APPLYING",
            "applicationUrl": "https://careers.stop-co.example/job/1", **extra,
        })["id"]
    _created.append(job_id)
    return job_id


def _stop_while_wedged(monkeypatch, held_job_id: str) -> None:
    monkeypatch.setattr(module, "STOP_GRACE_SECONDS", 0.05)
    runner = module.AutopilotRunner()
    runner.active_run_id = None

    async def scenario() -> None:
        with session_scope() as db:
            held = get_autopilot_job(db, held_job_id)
        state = module.WorkerState(worker_id=f"{runner.worker_id}_slot0", slot=0)
        state.current_job = held
        runner.worker_states[0] = state
        runner._loop_task = asyncio.create_task(asyncio.sleep(60))
        await runner.stop()

    asyncio.run(scenario())


def _status(job_id: str) -> str:
    with session_scope() as db:
        return get_autopilot_job(db, job_id)["status"]


def test_cancelled_job_that_never_clicked_submit_goes_back_to_the_queue(monkeypatch):
    job_id = _applying_job()
    _stop_while_wedged(monkeypatch, job_id)
    assert _status(job_id) == "QUEUED"


def test_cancelled_job_that_clicked_submit_is_never_requeued(monkeypatch):
    job_id = _applying_job(submitAttemptedAt="2020-01-01T00:00:00+00:00")
    _stop_while_wedged(monkeypatch, job_id)
    assert _status(job_id) == "SUBMISSION_UNKNOWN"


def test_an_applying_job_the_loop_did_not_hold_is_left_alone(monkeypatch):
    held_id = _applying_job()
    other_id = _applying_job()
    _stop_while_wedged(monkeypatch, held_id)
    assert _status(other_id) == "APPLYING"
