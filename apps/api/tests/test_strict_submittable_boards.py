"""With submittableBoardsStrict, a run that has only boards it cannot finish
unattended left pauses between jobs instead of falling back to them."""

from __future__ import annotations

import asyncio

import pytest

from app.db.store import session_scope
from app.services.application_assistant import autopilot_runner as module
from app.services.application_assistant.persistence import (
    delete_autopilot_job,
    get_autopilot_job,
    get_autopilot_run,
    list_autopilot_jobs,
    save_autopilot_job,
    save_autopilot_run,
)

OFF_BOARD_URL = "https://careers.example-employer.com/job/123/apply"
GREENHOUSE_URL = "https://job-boards.greenhouse.io/exampleco/jobs/456"


@pytest.fixture(autouse=True)
def empty_queue():
    """The suite shares one database; only this test's jobs may be claimable."""
    with session_scope() as db:
        for job in list_autopilot_jobs(db):
            if job.get("status") in ("QUEUED", "APPLYING"):
                delete_autopilot_job(db, job["id"])


def _seed(urls: list[str]) -> tuple[str, list[str]]:
    with session_scope() as db:
        run = save_autopilot_run(db, {"status": "RUNNING", "processedCount": 0, "targetProcessCount": 5})
        job_ids = [
            save_autopilot_job(db, {
                "company": f"Strict Co {i}", "title": "Software Engineer",
                "status": "QUEUED", "applicationUrl": url,
            })["id"]
            for i, url in enumerate(urls)
        ]
    return run["id"], job_ids


def _runner(monkeypatch, run_id: str, *, strict: bool) -> tuple[module.AutopilotRunner, list[str]]:
    runner = module.AutopilotRunner()
    runner.active_run_id = run_id
    runner.submittable_boards_only = True
    runner.submittable_boards_strict = strict
    claimed: list[str] = []

    async def no_refill(*_args, **_kwargs):
        return None

    async def fake_slot(_semaphore, _run_id, job_item, _ws, _slot_idx):
        claimed.append(job_item["id"])
        runner._stop_requested = True

    monkeypatch.setattr(runner, "_ensure_queue_preprocessor", lambda: None)
    monkeypatch.setattr(runner, "_refill_queue", no_refill)
    monkeypatch.setattr(runner, "_run_worker_slot", fake_slot)
    return runner, claimed


def test_strict_run_pauses_instead_of_claiming_an_off_board_job(monkeypatch):
    run_id, (job_id,) = _seed([OFF_BOARD_URL])
    runner, claimed = _runner(monkeypatch, run_id, strict=True)

    asyncio.run(asyncio.wait_for(runner._process_batch_loop(), timeout=10))

    assert claimed == []
    with session_scope() as db:
        assert get_autopilot_run(db, run_id)["status"] == "PAUSED"
        assert get_autopilot_job(db, job_id)["status"] == "QUEUED"


def test_strict_run_still_claims_a_submittable_job(monkeypatch):
    run_id, (off_board_id, greenhouse_id) = _seed([OFF_BOARD_URL, GREENHOUSE_URL])
    runner, claimed = _runner(monkeypatch, run_id, strict=True)

    asyncio.run(asyncio.wait_for(runner._process_batch_loop(), timeout=10))

    assert claimed == [greenhouse_id]
    with session_scope() as db:
        assert get_autopilot_run(db, run_id)["status"] == "RUNNING"


def test_strict_is_the_default():
    assert module.AutopilotRunner().submittable_boards_strict is True


def test_run_with_strict_off_falls_back_to_the_full_queue(monkeypatch):
    run_id, (job_id,) = _seed([OFF_BOARD_URL])
    runner, claimed = _runner(monkeypatch, run_id, strict=False)

    asyncio.run(asyncio.wait_for(runner._process_batch_loop(), timeout=10))

    assert claimed == [job_id]
