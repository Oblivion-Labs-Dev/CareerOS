from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

import app.services.error_fix_tracker as tracker_module
from app.main import app

client = TestClient(app)


@pytest.fixture()
def tracker(tmp_path, monkeypatch):
    history_file = tmp_path / "error-fix-history.jsonl"
    monkeypatch.setattr(tracker_module, "HISTORY_FILE", history_file)
    fresh = tracker_module.ErrorFixTracker()
    fresh._loaded = True
    monkeypatch.setattr(tracker_module, "error_fix_tracker", fresh)
    monkeypatch.setattr("app.services.error_investigation.error_fix_tracker", fresh)
    monkeypatch.setattr("app.services.runtime_metrics.error_fix_tracker", fresh)
    return fresh


def test_record_api_error_and_fix(tracker) -> None:
    tracker.record_api_response("GET", "/missing", 404)
    snapshot = tracker.snapshot()
    assert snapshot["totalErrorsTracked"] == 1
    assert snapshot["openErrors"] == 1

    tracker.record_api_response("GET", "/missing", 200)
    snapshot = tracker.snapshot()
    assert snapshot["totalFixesTracked"] == 1
    assert snapshot["openErrors"] == 0
    assert snapshot["recentFixes"][0]["signature"] == "GET /missing"


def test_record_client_error_and_fix_log(tracker) -> None:
    tracker.record_client_log({"level": "error", "source": "extension", "message": "Autofill timed out"})
    tracker.record_client_log({"level": "info", "source": "extension", "message": "Autofill issue fixed after reload"})
    snapshot = tracker.snapshot()
    assert snapshot["totalErrorsTracked"] == 1
    assert snapshot["totalFixesTracked"] == 1


def test_metrics_endpoint_includes_error_fix_payload() -> None:
    client.get("/health")
    response = client.get("/metrics")
    assert response.status_code == 200
    body = response.json()
    assert "errorFix" in body
    assert "totalFixesTracked" in body["errorFix"]
    assert "history" in body["errorFix"]


def test_root_dashboard_includes_manual_repair_panel() -> None:
    response = client.get("/")
    assert response.status_code == 200
    assert "Process Logs &amp; Errors" in response.text or "Process Logs & Errors" in response.text
    assert "process-logs-btn" in response.text
    assert "error-fix-history" in response.text
    assert "chart-error-fix" in response.text
    assert "investigate-open-btn" in response.text
    assert "investigate-dialog" in response.text


def test_investigate_error_endpoint(tracker) -> None:
    tracker.record_api_response("GET", "/broken", 500)
    error_id = tracker.list_open_errors()[0].id
    response = client.post(f"/errors/{error_id}/investigate")
    assert response.status_code == 200
    body = response.json()
    assert body["success"] is True
    assert body["errorId"] == error_id
    assert "Investigate and fix this CareerOS live error" in body["prompt"]
    assert body["investigationRequested"] is True


def test_investigate_open_errors_endpoint(tracker) -> None:
    tracker.record_api_response("GET", "/one", 500)
    tracker.record_client_log({"level": "error", "source": "extension", "message": "timeout"})
    response = client.post("/errors/investigate-open")
    assert response.status_code == 200
    body = response.json()
    assert body["openCount"] >= 2
    assert "open CareerOS errors" in body["prompt"]


def test_investigate_open_errors_empty(tracker) -> None:
    response = client.post("/errors/investigate-open")
    assert response.status_code == 404


def test_reconcile_resolved_errors(tracker) -> None:
    tracker.record_api_response("GET", "/email/verify", 503)
    tracker.record_api_response("GET", "/email/verify", 503)
    assert tracker.snapshot()["unresolvedErrors"] == 2

    recorded = tracker.reconcile_resolved_errors()
    assert recorded == 2
    snapshot = tracker.snapshot()
    assert snapshot["unresolvedErrors"] == 0
    assert snapshot["totalFixesTracked"] == 2


def test_noise_routes_not_tracked(tracker) -> None:
    tracker.record_api_response("GET", "/dev/demo/unhandled-scraper-error", 500)
    tracker.record_api_response("POST", "/dev/repair/process-logs", 404)
    assert tracker.snapshot()["totalErrorsTracked"] == 0
