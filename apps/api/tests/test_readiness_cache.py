"""/autopilot/readiness caches its grouped questions until a job is written (#100).

The cache must never show a question that has been answered, or hide one that
has just appeared: it is rebuilt on every autopilot-job write, including after
the write commits (a read that ran in between saw the old rows).
"""

from __future__ import annotations

import pytest

from app.db.store import SessionLocal, delete_entity, session_scope
from app.routers.application_assistant import autopilot as autopilot_routes
from app.routers.application_assistant.autopilot import autopilot_readiness
from app.services.application_assistant import pending_question_groups
from app.services.application_assistant.persistence import save_autopilot_job

QUESTION = "Which orbital launch vehicle did you most recently integrate payloads for?"


def _job(job_id: str, status: str) -> dict:
    return {
        "id": job_id,
        "status": status,
        "title": "Engineer",
        "company": "OrbitCo",
        "applicationUrl": f"https://jobs.lever.co/orbitco/{job_id}",
        "pendingQuestions": [{"question": QUESTION, "fieldType": "text", "options": []}],
    }


def _asked() -> bool:
    return any(g["question"] == QUESTION for g in autopilot_readiness()["questions"]["groups"])


@pytest.fixture()
def clean():
    autopilot_routes._readiness_questions.clear()
    yield
    with session_scope() as db:
        delete_entity(db, "aa_autopilot_job", "readiness_cache_job")
    autopilot_routes._readiness_questions.clear()


def test_unchanged_queue_is_served_from_cache(clean, monkeypatch) -> None:
    calls = []
    real = pending_question_groups.group_pending_questions
    monkeypatch.setattr(pending_question_groups, "group_pending_questions", lambda jobs: calls.append(1) or real(jobs))
    autopilot_readiness()
    autopilot_readiness()
    assert len(calls) == 1


def test_new_and_answered_questions_show_immediately(clean) -> None:
    assert not _asked()
    with session_scope() as db:
        save_autopilot_job(db, _job("readiness_cache_job", "NEEDS_REVIEW"))
    assert _asked()
    with session_scope() as db:
        save_autopilot_job(db, {**_job("readiness_cache_job", "QUEUED"), "pendingQuestions": []})
    assert not _asked()


def test_read_during_an_uncommitted_write_is_not_kept(clean) -> None:
    assert not _asked()
    db = SessionLocal()
    try:
        save_autopilot_job(db, _job("readiness_cache_job", "NEEDS_REVIEW"))
        db.flush()
        assert not _asked()  # another connection cannot see the write yet
        db.commit()
    finally:
        db.close()
    assert _asked()
