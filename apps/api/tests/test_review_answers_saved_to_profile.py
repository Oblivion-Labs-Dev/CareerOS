"""An answer given in Review is saved to the candidate's Profile.

The Profile page's "Screening answers" and the form filler's first-choice
source are both `profile.screeningAnswers`. Review answers used to go only to
the Answer Library, so nothing the user answered appeared on their Profile.
"""

from __future__ import annotations

import copy

import pytest

from app.db.store import get_kv, session_scope, set_kv
from app.routers.application_assistant.autopilot import approve_staged_answer
from app.services.application_assistant.pending_question_groups import answer_question_group
from app.services.application_assistant.persistence import (
    delete_autopilot_job,
    get_autopilot_job,
    save_autopilot_job,
)
from app.services.application_assistant.profile_answer_resolver import resolve_answer

QUESTION = "What languages do you speak and how proficient are you?*"


@pytest.fixture
def profile_snapshot():
    with session_scope() as db:
        original = copy.deepcopy(get_kv(db, "profile") or {})
    yield
    with session_scope() as db:
        set_kv(db, "profile", original)


@pytest.fixture
def review_job():
    job = {
        "id": "apjob_review_to_profile",
        "status": "NEEDS_REVIEW",
        "company": "Flexport",
        "title": "Senior SWE",
        "applicationUrl": "https://boards.greenhouse.io/flexport/jobs/1",
        "pendingQuestions": [{"question": QUESTION, "fieldType": "text"}],
    }
    with session_scope() as db:
        save_autopilot_job(db, dict(job))
    yield job
    with session_scope() as db:
        delete_autopilot_job(db, job["id"])


def _saved_entries(question_fragment: str) -> list[dict]:
    with session_scope() as db:
        profile = get_kv(db, "profile") or {}
    return [e for e in profile.get("screeningAnswers") or [] if question_fragment in str(e.get("question"))]


def test_a_group_answer_is_saved_to_the_profile_and_requeues_the_job(profile_snapshot, review_job):
    with session_scope() as db:
        answer_question_group(
            db, question=QUESTION, answer="English (native), Hindi (fluent)",
            variants=["What languages do you speak and how proficient are you?"], job_ids=[review_job["id"]],
        )

    entries = _saved_entries("What languages do you speak")
    assert len(entries) == 1
    assert entries[0]["answer"] == "English (native), Hindi (fluent)"
    with session_scope() as db:
        assert get_autopilot_job(db, review_job["id"])["status"] == "QUEUED"


def test_the_next_application_resolves_the_question_from_the_profile(profile_snapshot, review_job):
    with session_scope() as db:
        answer_question_group(db, question=QUESTION, answer="English (native)", job_ids=[review_job["id"]])
        profile = get_kv(db, "profile") or {}

    # A later posting asks the same thing without the required-field asterisk.
    later = "What languages do you speak and how proficient are you?"
    resolution = resolve_answer(later, profile)

    assert resolution.answer == "English (native)"
    assert str(resolution.profile_key).startswith("screeningAnswers.")


def test_answering_again_updates_the_profile_entry_instead_of_duplicating_it(profile_snapshot, review_job):
    with session_scope() as db:
        answer_question_group(db, question=QUESTION, answer="English", job_ids=[review_job["id"]])
        answer_question_group(db, question=QUESTION.rstrip("*"), answer="English, Spanish", job_ids=[])

    entries = _saved_entries("What languages do you speak")
    assert len(entries) == 1
    assert entries[0]["answer"] == "English, Spanish"


def test_approve_and_continue_also_saves_to_the_profile(profile_snapshot, review_job):
    with session_scope() as db:
        result = approve_staged_answer(
            review_job["id"], payload={"question": "What is your earliest start date?", "answer": "Two weeks after offer"}, db=db,
        )

    assert result["job"]["status"] == "QUEUED"
    entries = _saved_entries("earliest start date")
    assert [e["answer"] for e in entries] == ["Two weeks after offer"]
