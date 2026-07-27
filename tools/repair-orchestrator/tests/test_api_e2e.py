from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from repair_orchestrator.config import settings
from repair_orchestrator.db import init_db, session_scope
from repair_orchestrator.main import app


@pytest.fixture()
def client(tmp_path, monkeypatch):
    db_path = tmp_path / "repair-api.db"
    monkeypatch.setattr(settings, "repair_database_url", f"sqlite:///{db_path}")
    monkeypatch.setattr(settings, "min_occurrences_for_task", 2)
    from repair_orchestrator import db as db_module

    db_module.engine.dispose()
    db_module._ensure_sqlite_dir(settings.repair_database_url)
    db_module.engine = db_module.create_engine(
        settings.repair_database_url, connect_args={"check_same_thread": False}
    )
    db_module.SessionLocal = db_module.sessionmaker(bind=db_module.engine, autoflush=False, autocommit=False)
    init_db()
    return TestClient(app)


def _event():
    return {
        "severity": "error",
        "service": "career-os-api",
        "environment": "local",
        "errorType": "DemoScraperFailure",
        "message": "Simulated scraper profile fetch failure",
        "stackTrace": 'File "apps/api/app/routers/repair_demo.py", line 10, in trigger',
        "correlationId": "demo-1",
        "endpoint": "GET /dev/demo/unhandled-scraper-error",
        "gitCommitSha": "demo",
        "applicationVersion": "0.1.0",
        "sourceLocation": "apps/api/app/routers/repair_demo.py:10",
        "feature": "scraper",
        "metadata": {"demo": True},
    }


def test_health_endpoint(client):
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json()["service"] == "repair-orchestrator"


def test_e2e_demo_flow(client, monkeypatch):
    from repair_orchestrator.models import ValidationResult

    monkeypatch.setattr(
        "repair_orchestrator.api.routes.run_validation",
        lambda commands=None, repo_root=None: ValidationResult(
            passed=True,
            commands=[{"command": "mock-test", "passed": True, "exitCode": 0}],
            regressionTestPresent=True,
        ),
    )

    first = client.post("/events", json=_event())
    second = client.post("/events", json={**_event(), "correlationId": "demo-2"})
    assert first.status_code == 200
    assert second.status_code == 200
    assert second.json()["occurrenceCount"] == 2
    task_id = second.json()["taskId"]
    assert task_id

    approve = client.post(f"/tasks/{task_id}/approve-agent")
    assert approve.status_code == 200

    validate = client.post(f"/tasks/{task_id}/validate")
    assert validate.status_code == 200

    review = client.post(f"/tasks/{task_id}/review")
    assert review.status_code == 200
    review_body = review.json()["review"]
    assert review_body["decision"] in {"approve", "human_review", "reject", "needs_changes"}
    assert "riskLevel" in review_body

    task = client.get(f"/tasks/{task_id}")
    assert task.status_code == 200
    assert task.json()["auditHistory"]
