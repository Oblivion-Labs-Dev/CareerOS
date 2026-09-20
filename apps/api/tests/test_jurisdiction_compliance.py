"""Jurisdiction-aware warnings on the employer's own form question — see the
module docstring in jurisdiction_compliance.py for what these do and do not
claim. Warn-only: none of these ever block or auto-answer anything.
"""

from __future__ import annotations

from app.services.application_assistant.jurisdiction_compliance import (
    check_immigration_status_screening,
    check_salary_history_request,
)


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
