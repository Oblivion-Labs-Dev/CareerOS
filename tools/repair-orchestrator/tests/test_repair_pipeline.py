from __future__ import annotations

import pytest

from repair_orchestrator.config import settings
from repair_orchestrator.db import init_db, session_scope
from repair_orchestrator.incidents.fingerprint import compute_fingerprint
from repair_orchestrator.incidents.grouping import ingest_error_event
from repair_orchestrator.security.guardrails import is_protected_path, validate_patch_files
from repair_orchestrator.security.sanitization import sanitize_error_event, sanitize_string
from repair_orchestrator.review.reviewer import review_patch


@pytest.fixture(autouse=True)
def temp_db(tmp_path, monkeypatch):
    db_path = tmp_path / "repair-test.db"
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
    yield


def _sample_event(**overrides):
    payload = {
        "severity": "error",
        "service": "career-os-api",
        "environment": "local",
        "errorType": "ScraperFailure",
        "message": "Unexpected scraper failure token=Bearer secret123",
        "stackTrace": 'File "apps/api/app/services/job_discover/store.py", line 42, in scrape',
        "correlationId": "corr-1",
        "endpoint": "POST /jobs/discover/scrape",
        "gitCommitSha": "abc123",
        "applicationVersion": "0.1.0",
        "sourceLocation": "apps/api/app/services/job_discover/store.py:42",
        "feature": "scraper",
        "metadata": {"password": "hidden", "route": "/jobs/discover/scrape"},
    }
    payload.update(overrides)
    return payload


def test_sanitize_error_event_redacts_sensitive_data():
    sanitized = sanitize_error_event(_sample_event())
    assert "secret123" not in sanitized["message"]
    assert sanitized["metadata"]["password"] == "[REDACTED]"


def test_fingerprint_is_stable():
    event = _sample_event()
    assert compute_fingerprint(event) == compute_fingerprint(event)


def test_duplicate_events_group_into_one_incident():
    with session_scope() as session:
        first = ingest_error_event(session, _sample_event())
        second = ingest_error_event(session, _sample_event(correlationId="corr-2"))
    assert first["fingerprint"] == second["fingerprint"]
    assert second["occurrenceCount"] == 2
    assert second["taskCreated"] is True


def test_threshold_prevents_premature_task_creation():
    with session_scope() as session:
        result = ingest_error_event(session, _sample_event())
    assert result["occurrenceCount"] == 1
    assert result["taskCreated"] is False


def test_protected_file_enforcement():
    ok, violations = validate_patch_files([".env"], 100)
    assert ok is False
    assert any("Protected file" in item for item in violations)


def test_is_protected_path():
    assert is_protected_path(".github/workflows/ci.yml") is True
    assert is_protected_path("apps/web/app/page.tsx") is False


def test_reviewer_rejects_failed_validation():
    review = review_patch({"component": "scraper"}, {"passed": False})
    assert review.decision == "reject"


def test_reviewer_requires_human_review_for_auth_changes():
    review = review_patch(
        {"component": "api", "changedFiles": ["apps/api/app/routers/api.py"], "patchSummary": "fix auth"},
        {"passed": True},
    )
    assert review.decision == "human_review"


def test_sanitize_string_truncates_long_values():
    assert len(sanitize_string("x" * 3000, max_length=100)) <= 100
