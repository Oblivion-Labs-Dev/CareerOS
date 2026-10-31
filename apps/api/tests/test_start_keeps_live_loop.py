"""start() on a run a live loop is already working must not touch that loop.

Regression: Apply (preflight approve), self-heal and the console's Start all
call start(). With a batch loop mid-application, start() cancelled the loop
after one second — killing the application in flight and leaving it APPLYING —
and, because the run heartbeat is only written between jobs, it also ran stale
run recovery against the job being applied to.
"""

from __future__ import annotations

import asyncio

import pytest

from app.db.store import delete_entity, session_scope, upsert_entity
from app.services.application_assistant import autopilot_runner as module
from app.services.application_assistant.persistence import (
    delete_autopilot_job,
    get_autopilot_job,
    save_autopilot_job,
)

RUN_ID = "aprun_live_loop_regression"


@pytest.fixture
def live_run():
    with session_scope() as db:
        job_id = save_autopilot_job(db, {
            "company": "Live Co", "title": "Senior Software Engineer", "status": "APPLYING",
            "applicationUrl": "https://boards.greenhouse.io/liveco/jobs/42",
        })["id"]
        # Written directly: save_autopilot_run always refreshes the heartbeat,
        # and the point is a heartbeat that looks stale while a job runs.
        upsert_entity(db, "aa_autopilot_run", {
            "id": RUN_ID,
            "status": "RUNNING",
            "startedAt": "2999-01-01T00:00:00+00:00",
            "lastHeartbeatAt": "2020-01-01T00:00:00+00:00",
            "currentJobId": job_id,
            "targetProcessCount": 5,
            "processedCount": 1,
        })
    yield job_id
    with session_scope() as db:
        delete_autopilot_job(db, job_id)
        delete_entity(db, "aa_autopilot_run", RUN_ID)


def test_start_resumes_in_place_without_cancelling_the_job_in_flight(live_run, monkeypatch):
    runner = module.AutopilotRunner()
    monkeypatch.setattr(runner, "_ensure_queue_preprocessor", lambda: None)

    async def scenario():
        in_flight = asyncio.create_task(asyncio.sleep(30))
        runner._loop_task = in_flight
        await runner.start(options={"targetProcessCount": 1, "priorityJobId": "apjob_next"})
        try:
            return in_flight, runner._loop_task, in_flight.cancelled() or in_flight.done()
        finally:
            runner._stop_requested = True
            in_flight.cancel()

    in_flight, loop_after, finished = asyncio.run(scenario())

    assert loop_after is in_flight
    assert finished is False
    assert runner.priority_job_ids[0] == "apjob_next"
    with session_scope() as db:
        assert get_autopilot_job(db, live_run)["status"] == "APPLYING"
