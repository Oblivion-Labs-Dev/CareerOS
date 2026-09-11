from datetime import UTC, datetime

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.db.store import EntityStore, KVStore, SessionLocal, get_entity, list_entities, set_kv, upsert_entity
from app.routers.application_assistant.progress import db_session, router
from app.services.career_progress import (
    acknowledge_milestone,
    complete_quest,
    preferences,
    progress_snapshot,
    save_preferences,
    week_key,
)

NOW = datetime(2026, 9, 10, 12, tzinfo=UTC)


@pytest.fixture
def db():
    session = SessionLocal()
    session.query(EntityStore).delete()
    session.query(KVStore).delete()
    yield session
    session.rollback()
    session.close()


def test_week_is_local_monday_and_goal_survives_reload(db):
    boundary = datetime(2026, 9, 7, 1, tzinfo=UTC)
    assert week_key(boundary, "UTC") == "2026-09-07"
    assert week_key(boundary, "America/Los_Angeles") == "2026-08-31"
    save_preferences(db, 2, "America/Los_Angeles")
    db.expire_all()
    assert preferences(db) == {"weeklyGoal": 2, "timezone": "America/Los_Angeles"}


def test_check_in_is_idempotent_and_preserves_history(db):
    week = week_key(NOW, "UTC")
    first = complete_quest(db, "resume", week, NOW)
    second = complete_quest(db, "resume", week, NOW)
    assert first == second
    assert len(list_entities(db, "career_progress_event")) == 1
    assert progress_snapshot(db, NOW)["completedCount"] == 1
    future = datetime(2026, 9, 17, tzinfo=UTC)
    snapshot = progress_snapshot(db, future)
    assert snapshot["completedCount"] == 0
    assert len(snapshot["history"]) == 1
    assert snapshot["milestones"][0]["earnedAt"] == NOW.isoformat()


def test_stale_week_unknown_quest_and_unearned_badge_rejected(db):
    with pytest.raises(ValueError):
        complete_quest(db, "resume", "2026-08-31", NOW)
    with pytest.raises(ValueError):
        complete_quest(db, "fake", "2026-09-07", NOW)
    assert list_entities(db, "career_progress_event") == []


def test_confirmation_evidence_controls_records_and_milestones(db):
    for id, status in [("confirmed", "SUBMITTED"), ("unverified", "SUBMITTED"), ("failed", "FAILED")]:
        upsert_entity(db, "aa_autopilot_job", {"id": id, "status": status, "submittedAt": "2026-09-08T12:00:00Z", "applicationId": "tracker"})
    set_kv(db, "autopilot_submission_receipts", {"confirmed": {"jobId": "confirmed", "qwenReview": {"submissionConfirmed": True, "reason": "ATS confirmation"}, "confirmationText": "Acme received your application."}})
    upsert_entity(db, "application", {"id": "tracker", "firstResponseAt": "2026-09-09", "interviewAt": "2026-10-01"})
    result = progress_snapshot(db, NOW)
    assert result["records"]["confirmedTotal"] == 1
    assert result["records"]["bestWeekCount"] == 1
    assert result["milestones"][1]["earnedAt"]
    assert result["milestones"][2]["earnedAt"]
    assert result["milestones"][3]["earnedAt"] is None
    assert get_entity(db, "aa_autopilot_job", "failed")["status"] == "FAILED"


def test_goal_reached_uses_check_ins_not_submission_count(db):
    save_preferences(db, 2, "UTC")
    for quest in ["resume", "shortlist"]:
        complete_quest(db, quest, "2026-09-07", NOW)
    assert progress_snapshot(db, NOW)["goalReached"] is True
    assert progress_snapshot(db, NOW)["records"]["confirmedTotal"] == 0


def test_milestone_acknowledgement_is_persisted_once(db):
    current = datetime.now(UTC)
    complete_quest(db, "resume", week_key(current, "UTC"), current)
    acknowledge_milestone(db, "first_step")
    acknowledge_milestone(db, "first_step")
    db.expire_all()
    assert progress_snapshot(db)["milestones"][0]["seen"] is True
    assert len(list_entities(db, "career_progress_event")) == 2


def test_progress_requires_authentication_when_login_enabled(db, monkeypatch):
    from app.middleware import auth

    monkeypatch.setattr(auth, "is_auth_configured", lambda: True)
    monkeypatch.setattr(auth, "verify_session_token", lambda token: None)
    app = FastAPI()
    app.add_middleware(auth.AuthGateMiddleware)
    app.include_router(router)
    app.dependency_overrides[db_session] = lambda: db
    with TestClient(app) as client:
        assert client.get("/application-assistant/progress").status_code == 401
        assert client.put("/application-assistant/progress/preferences", json={"weeklyGoal": 1, "timezone": "UTC"}).status_code == 401
    assert preferences(db)["weeklyGoal"] == 3


def test_api_validates_preferences_and_unknown_achievements(db):
    app = FastAPI()
    app.include_router(router)
    app.dependency_overrides[db_session] = lambda: db
    with TestClient(app) as client:
        for payload in [{"weeklyGoal": 0, "timezone": "UTC"}, {"weeklyGoal": 4, "timezone": "UTC"}, {"weeklyGoal": True, "timezone": "UTC"}, {"weeklyGoal": 2, "timezone": "Imaginary/Zone"}]:
            assert client.put("/application-assistant/progress/preferences", json=payload).status_code == 422
        assert client.post("/application-assistant/progress/milestones/first_offer/seen").status_code == 409
        assert client.get("/application-assistant/progress").status_code == 200
