"""Unit and Integration Tests for CareerOS Autonomous Subsystem & Self-Healing Pipeline."""

import os
import tempfile
import pytest

from app.services.application_assistant.failure_taxonomy import FailureContext, FailureType, create_failure_signature
from app.services.application_assistant.submission_guard import SubmissionBlockedError, assert_submission_permitted, validate_action_allowed
from app.services.application_assistant.worktree_manager import WorktreeManager
from app.services.application_assistant.validation_runner import ValidationRunner


def test_failure_taxonomy_and_signature():
    fc = FailureContext(
        failure_id="fail_123",
        job_id="job_456",
        run_id="run_789",
        application_url="https://example.com/apply",
        failure_type=FailureType.SELECTOR_CHANGED,
        error_message="Could not click button with selector #submit-btn-0x99",
        ats_type="workday",
        adapter_name="WorkdayAdapter",
        selector_attempts=["#submit-btn-0x99", ".continue-btn"],
    )
    sig1 = create_failure_signature(fc)
    assert len(sig1) == 16

    # Normalized error message produces identical signature
    fc2 = FailureContext(
        failure_id="fail_124",
        job_id="job_457",
        run_id="run_789",
        application_url="https://example.com/apply",
        failure_type=FailureType.SELECTOR_CHANGED,
        error_message="Could not click button with selector #submit-btn-0x100",
        ats_type="workday",
        adapter_name="WorkdayAdapter",
        selector_attempts=["#submit-btn-0x99", ".continue-btn"],
    )
    sig2 = create_failure_signature(fc2)
    assert sig1 == sig2


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


def test_worktree_manager_initialization():
    wt_manager = WorktreeManager()
    assert wt_manager.repo_root.exists()
    head = wt_manager.get_head_commit()
    assert head is not None


def test_validation_runner_gates():
    vr = ValidationRunner()
    fc = FailureContext(
        failure_id="test_val_1",
        job_id="j1",
        run_id="r1",
        application_url="https://example.com",
        failure_type=FailureType.ELEMENT_NOT_FOUND,
        error_message="Element not found",
    )
    # Check syntax verification gate
    with tempfile.TemporaryDirectory() as tmp_dir:
        class FakeWorktree:
            path = tmp_dir
        res = vr.validate(FakeWorktree(), fc)
        assert res is not None
