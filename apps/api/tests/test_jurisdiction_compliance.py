"""Jurisdiction-aware warnings on the employer's own form question — see the
module docstring in jurisdiction_compliance.py for what these do and do not
claim. Warn-only: none of these ever block or auto-answer anything.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from app.services.application_assistant.jurisdiction_compliance import (
    check_immigration_status_screening,
    check_salary_history_request,
    collect_job_compliance_warnings,
)


@dataclass
class _FakeResolution:
    """Stands in for AnswerResolution — collect_job_compliance_warnings only
    duck-types on these three attributes."""
    question: str = ""
    field_id: str = ""
    compliance_warnings: list[str] = field(default_factory=list)


# ── Immigration-status screening ─────────────────────────────────────────────


def test_plain_work_authorization_never_warns():
    assert check_immigration_status_screening("Are you authorized to work in the United States?") is None


def test_plain_sponsorship_question_never_warns():
    q = "Will you now or in the future require sponsorship for employment visa status?"
    assert check_immigration_status_screening(q) is None


def test_are_you_a_citizen_warns():
    warning = check_immigration_status_screening("Are you a US citizen?")
    assert warning is not None
    assert warning.category == "immigration_status_screening"


def test_permanent_resident_status_only_warns():
    warning = check_immigration_status_screening("Are you a permanent resident status only?")
    assert warning is not None


def test_permanence_qualified_authorization_warns():
    """The Haseeb-style proxy: adding a permanence qualifier converts a
    lawful authorization question into a status screen."""
    q = "Are you legally authorized to work in Canada on a permanent basis?"
    warning = check_immigration_status_screening(q)
    assert warning is not None
    assert warning.category == "immigration_status_screening"


def test_empty_question_never_warns():
    assert check_immigration_status_screening("") is None
    assert check_immigration_status_screening(None) is None  # type: ignore[arg-type]


def test_the_warning_never_asserts_the_employer_broke_the_law():
    warning = check_immigration_status_screening("Are you a US citizen?")
    assert "not legal advice" in warning.message.lower()
    assert "breaking the law" not in warning.message.lower()
    assert "illegal" not in warning.message.lower()


# ── Salary-history requests ──────────────────────────────────────────────────


def test_salary_history_in_a_banned_state_warns():
    warning = check_salary_history_request("What is your current salary?", {"state": "California"})
    assert warning is not None
    assert warning.category == "salary_history"


def test_salary_history_matching_is_case_insensitive_on_state():
    assert check_salary_history_request("What is your current salary?", {"state": "CALIFORNIA"}) is not None


def test_salary_history_with_unknown_state_skips_silently():
    """Never guess whether a question is restricted when the candidate's
    jurisdiction isn't known — skip rather than assert something unverified."""
    assert check_salary_history_request("What is your current salary?", {}) is None
    assert check_salary_history_request("What is your current salary?", {"state": ""}) is None


def test_salary_history_outside_the_representative_list_does_not_warn():
    warning = check_salary_history_request("What was your prior salary?", {"state": "Texas"})
    assert warning is None


def test_salary_expectation_never_warns_even_in_a_banned_state():
    q = "What is your desired salary expectation for this role?"
    assert check_salary_history_request(q, {"state": "California"}) is None


def test_compensation_history_phrasing_is_detected():
    warning = check_salary_history_request("Please provide your compensation history.", {"state": "New York"})
    assert warning is not None


def test_empty_question_never_warns_regardless_of_state():
    assert check_salary_history_request("", {"state": "California"}) is None


# ── collect_job_compliance_warnings ──────────────────────────────────────────


def test_collect_returns_empty_for_resolutions_with_no_warnings():
    resolutions = [_FakeResolution(question="Are you authorized to work in the US?")]
    assert collect_job_compliance_warnings(resolutions) == []


def test_collect_flattens_one_warning_per_resolution():
    resolutions = [
        _FakeResolution(question="Are you a US citizen?", field_id="f1", compliance_warnings=["status warning"]),
        _FakeResolution(question="What was your prior salary?", field_id="f2", compliance_warnings=["salary warning"]),
    ]
    result = collect_job_compliance_warnings(resolutions)
    assert result == [
        {"question": "Are you a US citizen?", "message": "status warning", "fieldId": "f1"},
        {"question": "What was your prior salary?", "message": "salary warning", "fieldId": "f2"},
    ]


def test_collect_dedupes_the_same_question_and_message_across_resolutions():
    """The live executor calls resolve_answer twice for the same field in some
    paths (fill-time, then again for classification) — the same warning must
    not appear twice in the job record."""
    resolutions = [
        _FakeResolution(question="Are you a US citizen?", field_id="f1", compliance_warnings=["status warning"]),
        _FakeResolution(question="Are you a US citizen?", field_id="f1", compliance_warnings=["status warning"]),
    ]
    assert len(collect_job_compliance_warnings(resolutions)) == 1


def test_collect_keeps_distinct_messages_for_the_same_question():
    resolutions = [
        _FakeResolution(question="Are you a US citizen?", field_id="f1", compliance_warnings=["warning A", "warning B"]),
    ]
    result = collect_job_compliance_warnings(resolutions)
    assert len(result) == 2


def test_collect_ignores_resolutions_missing_expected_attributes():
    """Duck-typed on question/field_id/compliance_warnings — an object
    missing them contributes nothing rather than raising."""
    class _Empty:
        pass

    assert collect_job_compliance_warnings([_Empty()]) == []
