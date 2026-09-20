"""One question answered once should clear every application that asks it.

Fifty Roblox postings stalling on the same screening question is not fifty
pieces of review work. The answer library already propagates a saved answer by
word overlap; these cover the grouping that makes that visible and orders it by
what actually finishes work.
"""

from __future__ import annotations

from app.services.application_assistant.pending_question_groups import (
    group_pending_questions,
    summarise,
)


def _job(job_id: str, company: str, *questions: str) -> dict:
    return {
        "id": job_id,
        "company": company,
        "pendingQuestions": [{"question": q, "fieldType": "text", "options": []} for q in questions],
    }


VISA = "Do you now or in the future require visa sponsorship to work in the US?"
VISA_REWORDED = "Will you now or in the future require sponsorship for a US work visa?"
GAMING = "Tell us about your passion for gaming"


# ── Grouping ─────────────────────────────────────────────────────────────────


def test_the_same_question_across_many_jobs_becomes_one_row():
    jobs = [_job(f"j{i}", "Roblox", VISA) for i in range(50)]

    groups = group_pending_questions(jobs)

    assert len(groups) == 1
    assert groups[0].job_count == 50
    assert groups[0].companies == {"Roblox": 50}


def test_rewordings_collapse_together():
    """The executor's questions are LLM-rephrased, so the same underlying field
    comes back worded differently. Exact matching would split one question into
    many rows the user answers repeatedly."""
    jobs = [_job("a", "Roblox", VISA), _job("b", "Roblox", VISA_REWORDED)]

    groups = group_pending_questions(jobs)

    assert len(groups) == 1
    assert groups[0].job_count == 2
    assert len(groups[0].variants) == 2


def test_genuinely_different_questions_stay_separate():
    jobs = [_job("a", "Riot", VISA), _job("b", "Riot", GAMING)]

    assert len(group_pending_questions(jobs)) == 2


def test_the_fullest_wording_is_the_one_shown():
    """A truncated rendering of a question is harder to answer correctly."""
    short = "Require visa sponsorship?"
    jobs = [_job("a", "X", short), _job("b", "X", VISA)]

    groups = group_pending_questions(jobs)

    assert groups[0].question == VISA


def test_one_question_spanning_companies_is_still_one_row():
    jobs = [_job("a", "Roblox", VISA), _job("b", "Okta", VISA), _job("c", "Okta", VISA)]

    groups = group_pending_questions(jobs)

    assert groups[0].job_count == 3
    assert groups[0].companies == {"Roblox": 1, "Okta": 2}
    assert "across 2 companies" in groups[0].headline()


# ── Honest counting: what an answer actually finishes ────────────────────────


def test_a_question_that_finishes_a_job_is_counted_as_such():
    jobs = [_job(f"j{i}", "Roblox", VISA) for i in range(3)]

    groups = group_pending_questions(jobs)

    assert groups[0].unblocks_alone == 3
    assert groups[0].headline().startswith("Finishes 3 applications")


def test_a_job_with_two_blockers_is_not_promised_to_either():
    """The correction that matters.

    An application is only done when every question it asks is answered.
    Counting a job as "unblocked" by each of its two blockers would promise
    twice what a single answer delivers.
    """
    jobs = [_job("a", "Canonical", VISA, GAMING)]

    groups = group_pending_questions(jobs)

    assert len(groups) == 2
    assert all(group.unblocks_alone == 0 for group in groups)
    assert all(group.job_count == 1 for group in groups)
    assert "still needs other answers" in groups[0].headline()


def test_ordering_prefers_what_finishes_work_over_what_is_merely_common():
    """A question asked by 40 applications that finishes none of them is worse
    use of the next minute than one that finishes five."""
    common_but_useless = [_job(f"c{i}", "BigCo", VISA, f"unique filler question {i}") for i in range(40)]
    less_common_but_finishing = [_job(f"f{i}", "SmallCo", GAMING) for i in range(5)]

    groups = group_pending_questions(common_but_useless + less_common_but_finishing)

    assert groups[0].question == GAMING
    assert groups[0].unblocks_alone == 5
    visa_group = next(g for g in groups if "sponsorship" in g.question.lower())
    assert visa_group.job_count == 40
    assert visa_group.unblocks_alone == 0


# ── Shape and edges ──────────────────────────────────────────────────────────


def test_summary_reports_the_promisable_number():
    jobs = [_job("a", "X", VISA), _job("b", "X", VISA, GAMING)]

    summary = summarise(group_pending_questions(jobs))

    assert summary["blockedJobCount"] == 2
    assert summary["singleAnswerJobCount"] == 1, "only job a is finished by one answer"
    assert "need only one answer" in summary["headline"]


def test_jobs_without_pending_questions_are_ignored():
    jobs = [{"id": "a", "company": "X"}, {"id": "b", "company": "X", "pendingQuestions": []}]

    assert group_pending_questions(jobs) == []


def test_blank_questions_are_skipped():
    jobs = [{"id": "a", "company": "X", "pendingQuestions": [{"question": "   "}, {"question": VISA}]}]

    groups = group_pending_questions(jobs)

    assert len(groups) == 1


# ── Answering a group ────────────────────────────────────────────────────────


def _save(job: dict) -> None:
    from app.db.store import session_scope
    from app.services.application_assistant.persistence import save_autopilot_job

    with session_scope() as db:
        save_autopilot_job(db, dict(job))


def _read(job_id: str) -> dict:
    from app.db.store import session_scope
    from app.services.application_assistant.persistence import get_autopilot_job

    with session_scope() as db:
        return get_autopilot_job(db, job_id)


def _answer(**kwargs) -> dict:
    from app.db.store import session_scope
    from app.services.application_assistant.pending_question_groups import (
        answer_question_group,
    )

    with session_scope() as db:
        return answer_question_group(db, **kwargs)


def test_answering_requeues_every_application_it_finishes():
    """The point of grouping: answer once, not fifty times."""
    ids = [f"apjob_grp_{i}" for i in range(3)]
    for job_id in ids:
        _save({**_job(job_id, "Roblox", VISA), "status": "NEEDS_REVIEW"})
    try:
        result = _answer(question=VISA, answer="Yes", variants=[VISA], job_ids=ids)

        assert result["requeuedCount"] == 3
        assert all(_read(job_id)["status"] == "QUEUED" for job_id in ids)
    finally:
        _drop(*ids)


def test_a_job_with_another_blocker_is_not_requeued():
    """Answering one of two questions does not finish the application, and
    requeueing it would spend a browser run rediscovering the second."""
    _save({**_job("apjob_grp_two", "Canonical", VISA, GAMING), "status": "NEEDS_REVIEW"})
    try:
        result = _answer(question=VISA, answer="Yes", variants=[VISA], job_ids=["apjob_grp_two"])

        assert result["requeuedCount"] == 0
        assert result["stillBlockedCount"] == 1
        job = _read("apjob_grp_two")
        assert job["status"] == "NEEDS_REVIEW"
        assert len(job["pendingQuestions"]) == 1, "only the answered question is cleared"
        assert job["customAnswers"][VISA] == "Yes"
    finally:
        _drop("apjob_grp_two")


def test_the_answer_is_saved_with_every_wording_seen():
    """So a later rephrasing of the same field matches it instead of asking
    again — the library matches by word overlap, not exact text."""
    from app.db.store import session_scope
    from app.services.application_assistant.persistence import list_answer_library

    _save({**_job("apjob_grp_lib", "Roblox", VISA), "status": "NEEDS_REVIEW"})
    try:
        _answer(question=VISA, answer="Yes", variants=[VISA, VISA_REWORDED], job_ids=["apjob_grp_lib"])

        with session_scope() as db:
            # Match on the reworded variant specifically: other tests in this
            # file also save a "Yes", so picking the first one is a coin toss.
            entry = next(
                e for e in list_answer_library(db)
                if VISA_REWORDED in (e.get("questionVariants") or [])
            )
        assert entry["value"] == "Yes"
        assert entry["verificationStatus"] == "verified"
    finally:
        _drop("apjob_grp_lib")


def test_an_empty_answer_is_refused():
    import pytest

    with pytest.raises(ValueError):
        _answer(question=VISA, answer="   ", job_ids=[])


def _drop(*job_ids: str) -> None:
    from app.db.store import session_scope
    from app.services.application_assistant.persistence import delete_autopilot_job

    with session_scope() as db:
        for job_id in job_ids:
            delete_autopilot_job(db, job_id)


def test_the_serialised_group_carries_both_counts():
    jobs = [_job("a", "X", VISA), _job("b", "X", VISA, GAMING)]

    payload = group_pending_questions(jobs)[0].to_dict()

    assert payload["jobCount"] >= payload["unblocksAlone"]
    assert set(payload) >= {"question", "jobIds", "jobCount", "unblocksAlone", "companies", "headline"}
