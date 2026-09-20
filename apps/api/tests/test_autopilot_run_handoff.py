import asyncio
from contextlib import contextmanager

from app.services.application_assistant import autopilot_runner as module


def test_completed_run_hands_off_to_new_active_run(monkeypatch):
    runner = module.AutopilotRunner()
    runner.active_run_id = "first"
    # Batch targets now roll over continuously. A completed predecessor can
    # still exist when a newly started run becomes active; it must be adopted.
    runs = {
        "first": {"id": "first", "status": "COMPLETED"},
        "second": {"id": "second", "status": "RUNNING", "processedCount": 1, "targetProcessCount": 1},
    }
    processed = []

    @contextmanager
    def session():
        yield None

    def save(db, run):
        runs[run['id']] = run
        processed.append(run['id'])
        runner._stop_requested = True  # Observe one rollover without starting workers.

    monkeypatch.setattr(module, "session_scope", session)
    monkeypatch.setattr(module, "get_autopilot_run", lambda db, id: runs.get(id))
    monkeypatch.setattr(module, "get_active_autopilot_run", lambda db: next((r for r in runs.values() if r["status"] == "RUNNING"), None))
    monkeypatch.setattr(module, "save_autopilot_run", save)
    asyncio.run(asyncio.wait_for(runner._process_batch_loop(), timeout=1))
    assert runner.active_run_id == 'second'
    assert processed == ['second']
    assert runs['second']['processedCount'] == 0
    assert runs["second"]["status"] == "RUNNING"
