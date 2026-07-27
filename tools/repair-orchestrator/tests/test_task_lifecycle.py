from __future__ import annotations

import pytest

from repair_orchestrator.models import TaskStatus
from repair_orchestrator.tasks.lifecycle import transition_task
from repair_orchestrator.db import RepairTaskRow, dump_json, session_scope, init_db
from repair_orchestrator.config import settings


@pytest.fixture(autouse=True)
def temp_db(tmp_path, monkeypatch):
    db_path = tmp_path / "lifecycle.db"
    monkeypatch.setattr(settings, "repair_database_url", f"sqlite:///{db_path}")
    from repair_orchestrator import db as db_module

    db_module.engine.dispose()
    db_module._ensure_sqlite_dir(settings.repair_database_url)
    db_module.engine = db_module.create_engine(
        settings.repair_database_url, connect_args={"check_same_thread": False}
    )
    db_module.SessionLocal = db_module.sessionmaker(bind=db_module.engine, autoflush=False, autocommit=False)
    init_db()


def _seed_task(status: TaskStatus = TaskStatus.DETECTED) -> str:
    task_id = "task-123"
    with session_scope() as session:
        session.add(
            RepairTaskRow(
                task_id=task_id,
                incident_fingerprint="fp1",
                title="Test",
                status=status.value,
                severity="error",
                component="scraper",
                payload_json=dump_json({"auditHistory": []}),
                created_at="2026-01-01T00:00:00+00:00",
                updated_at="2026-01-01T00:00:00+00:00",
            )
        )
    return task_id


def test_valid_task_transition():
    task_id = _seed_task(TaskStatus.DETECTED)
    with session_scope() as session:
        updated = transition_task(session, task_id, TaskStatus.READY_FOR_AGENT)
    assert updated["status"] == TaskStatus.READY_FOR_AGENT.value


def test_invalid_task_transition_rejected():
    task_id = _seed_task(TaskStatus.DETECTED)
    with session_scope() as session:
        with pytest.raises(ValueError):
            transition_task(session, task_id, TaskStatus.APPROVED)
