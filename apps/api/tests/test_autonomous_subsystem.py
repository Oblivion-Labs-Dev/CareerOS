"""Submission guard: real submits stay blocked unless explicitly allowed."""

import pytest

from app.services.application_assistant.submission_guard import SubmissionBlockedError, assert_submission_permitted, validate_action_allowed


def test_submission_guard_security_boundary(monkeypatch):
    # Default environment (ALLOW_REAL_SUBMISSION unset or false)
    monkeypatch.delenv("ALLOW_REAL_SUBMISSION", raising=False)
    monkeypatch.delenv("DRY_RUN_REPAIR", raising=False)

    with pytest.raises(SubmissionBlockedError):
        assert_submission_permitted("TestContext")

    ok, reason = validate_action_allowed("final_submit")
    assert not ok
    assert "ALLOW_REAL_SUBMISSION" in reason

    # Active DRY_RUN_REPAIR mode
    monkeypatch.setenv("ALLOW_REAL_SUBMISSION", "true")
    monkeypatch.setenv("DRY_RUN_REPAIR", "true")
    with pytest.raises(SubmissionBlockedError):
        assert_submission_permitted("RepairTestContext")

    # Production submission mode
    monkeypatch.setenv("ALLOW_REAL_SUBMISSION", "true")
    monkeypatch.setenv("DRY_RUN_REPAIR", "false")
    assert_submission_permitted("ProductionContext")  # should not raise
    ok, _ = validate_action_allowed("final_submit")
    assert ok
