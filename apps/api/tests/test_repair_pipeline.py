from __future__ import annotations

from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

import app.services.repair.store as store_module
from app.config import settings
from app.main import app
from app.services.error_fix_tracker import error_fix_tracker


@pytest.fixture()
def client(tmp_path, monkeypatch):
    store_file = tmp_path / "repair-tasks.json"
    log_file = tmp_path / "client.jsonl"
    monkeypatch.setattr(store_module, "STORE_FILE", store_file)
    monkeypatch.setattr("app.services.log_store.LOG_FILE", log_file)
    monkeypatch.setattr("app.services.repair.processor.repair_task_store", store_module.RepairTaskStore())
    monkeypatch.setattr("app.services.repair.processor.REPO_ROOT", tmp_path)
    return TestClient(app)


@pytest.fixture()
def tracker(tmp_path, monkeypatch):
    import app.services.error_fix_tracker as tracker_module
    import app.services.log_store as log_store_module

    history_file = tmp_path / "error-fix-history.jsonl"
    monkeypatch.setattr(tracker_module, "HISTORY_FILE", history_file)
    fresh = tracker_module.ErrorFixTracker()
    fresh._loaded = True
    monkeypatch.setattr(tracker_module, "error_fix_tracker", fresh)
    monkeypatch.setattr(log_store_module, "error_fix_tracker", fresh)
    monkeypatch.setattr("app.services.repair.log_source.error_fix_tracker", fresh)
    return fresh


def test_demo_endpoint_records_error_without_auto_processing(client, tracker, monkeypatch, tmp_path):
    import app.services.log_store as log_store_module

    log_file = tmp_path / "client.jsonl"
    monkeypatch.setattr(log_store_module, "LOG_FILE", log_file)

    response = client.get("/dev/demo/unhandled-scraper-error")
    assert response.status_code == 200
    body = response.json()
    assert body["success"] is False
    assert body["demo"] is True
    assert log_file.is_file()
    snapshot = tracker.snapshot()
    assert snapshot["totalErrorsTracked"] >= 1
    assert any(item.get("source") == "client" for item in snapshot.get("recentErrors", []))


def test_manual_process_hidden_outside_dev(client, monkeypatch):
    monkeypatch.setattr(settings, "career_os_dev_mode", False)
    response = client.post("/dev/repair/process-logs")
    assert response.status_code == 404


def test_manual_process_poc_flow(client, tracker, monkeypatch):
    client.get("/dev/demo/unhandled-scraper-error")

    mock_run = {
        "runId": "run-1",
        "taskId": "task-1",
        "status": "completed",
        "branch": "repair/demo-fix",
        "worktreePath": "/tmp/worktree",
        "changedFiles": ["tools/repair-orchestrator/demo-patch.txt"],
        "diffSummary": "Added regression patch placeholder",
        "commandsRun": [],
        "output": "Mock agent completed",
    }

    class FakeAdapter:
        def start(self, task, workspace):
            from app.services.repair.types import AgentRun

            return AgentRun(
                run_id="run-1",
                task_id=task.task_id,
                branch="repair/demo-fix",
                worktree_path="/tmp/worktree",
                status="completed",
                changed_files=["tools/repair-orchestrator/demo-patch.txt"],
                diff_summary="Added regression patch placeholder",
                output="Mock agent completed",
            )

        def get_status(self, run_id):
            return mock_run

        def cancel(self, run_id):
            return None

    with patch("app.services.repair.processor.get_agent_adapter", return_value=FakeAdapter()):
        with patch(
            "app.services.repair.processor._run_validation",
            return_value={"passed": True, "commands": [{"command": "mock", "passed": True, "exitCode": 0}]},
        ):
            response = client.post("/dev/repair/process-logs")

    assert response.status_code == 200
    body = response.json()
    assert body["logEntriesScanned"] >= 1
    assert body["errorsDiscovered"] >= 1
    assert body["duplicateGroups"] >= 1
    assert body["task"] is not None
    assert body["agentRun"]["status"] == "completed"
    assert body["validation"]["passed"] is True
    assert body["state"] == "completed"
    assert "Bearer" not in str(body)


def test_duplicate_active_run_blocked(client, tracker, monkeypatch):
    monkeypatch.setattr("app.services.repair.processor._active_run", True)
    try:
        response = client.post("/dev/repair/process-logs")
        assert response.status_code == 409
    finally:
        monkeypatch.setattr("app.services.repair.processor._active_run", False)
