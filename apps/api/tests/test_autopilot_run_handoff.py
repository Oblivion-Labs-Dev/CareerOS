import asyncio
from contextlib import contextmanager

from app.services.application_assistant import autopilot_runner as module


def test_new_run_started_during_healing_is_not_abandoned(monkeypatch):
    runner = module.AutopilotRunner()
    runner.active_run_id = "first"
    runs = {"first": {"id": "first", "status": "RUNNING", "processedCount": 1, "targetProcessCount": 1}}
    healed = []

    @contextmanager
    def session():
        yield None

    async def heal(run_id):
        healed.append(run_id)
        if run_id == "first":
            runs["second"] = {"id": "second", "status": "RUNNING", "processedCount": 1, "targetProcessCount": 1}
            runner.active_run_id = "second"

    monkeypatch.setattr(module, "session_scope", session)
    monkeypatch.setattr(module, "get_autopilot_run", lambda db, id: runs.get(id))
    monkeypatch.setattr(module, "get_active_autopilot_run", lambda db: next((r for r in runs.values() if r["status"] == "RUNNING"), None))
    monkeypatch.setattr(module, "save_autopilot_run", lambda db, run: runs.update({run["id"]: run}))
    monkeypatch.setattr(runner, "_trigger_post_batch_self_healing", heal)
    asyncio.run(asyncio.wait_for(runner._process_batch_loop(), timeout=1))
    assert healed == ["first", "second"]
    assert runs["second"]["status"] == "COMPLETED"
