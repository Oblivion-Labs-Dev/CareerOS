"""Unit tests verifying that persistent high-risk contradictions permanently block submission."""

import pytest
from app.services.application_assistant.submission_policy import (
    SubmissionPolicy,
    RiskTier,
    SubmissionDecision,
    HIGH_RISK_CONTRADICTION_DOMAINS,
)
from app.services.application_assistant.cross_field_validator import ValidationReport
from app.services.application_assistant.profile_answer_resolver import AnswerResolution


def test_no_contradictions_allows_submission_when_valid():
    report = ValidationReport(status="PASS", blocking_errors=[], warnings=[])
    res = AnswerResolution(
        field_id="first_name",
        question="First Name",
        question_type="FIRST_NAME",
        answer="Akshay",
        confidence=1.0,
    )
    result = SubmissionPolicy.evaluate(
        resolutions=[res],
        validation_report=report,
        blocking_contradictions=[],
    )
    assert result.decision == SubmissionDecision.READY_TO_SUBMIT
    assert result.can_auto_submit is True
    assert result.risk_tier == RiskTier.LOW_RISK
    assert len(result.blocking_issues) == 0


def test_persistent_contradiction_forces_high_risk_and_needs_review():
    report = ValidationReport(status="PASS", blocking_errors=[], warnings=[])
    res = AnswerResolution(
        field_id="gender",
        question="Gender",
        question_type="GENDER",
        answer="Female",
        confidence=1.0,
    )
    blocking_contradictions = [
        {
            "domain": "demographics",
            "rule": "GENDER_IDENTITY_CONTRADICTION",
            "fieldId": "gender",
            "question": "Gender",
            "reason": "Profile gender 'Male' contradicts form answer 'Female'",
            "answer": "Female",
        }
    ]

    result = SubmissionPolicy.evaluate(
        resolutions=[res],
        validation_report=report,
        blocking_contradictions=blocking_contradictions,
    )
    assert result.decision == SubmissionDecision.NEEDS_REVIEW
    assert result.can_auto_submit is False
    assert result.risk_tier == RiskTier.HIGH_RISK
    assert any("persistent block" in r.lower() for r in result.reasons)
    assert any("gender" in r.lower() for r in result.reasons)


def test_visa_contradiction_permanently_blocks():
    report = ValidationReport(status="PASS", blocking_errors=[], warnings=[])
    res = AnswerResolution(
        field_id="sponsorship",
        question="Will you now or in the future require sponsorship?",
        question_type="SPONSORSHIP_REQUIRED",
        answer="No",
        confidence=1.0,
    )
    blocking_contradictions = [
        {
            "domain": "visa_work_auth",
            "rule": "WORK_AUTH_INCONSISTENCY",
            "fieldId": "sponsorship",
            "question": "Will you now or in the future require sponsorship?",
            "reason": "Intended answer 'Yes' conflicts with live DOM value 'No'",
            "answer": "No",
        }
    ]

    result = SubmissionPolicy.evaluate(
        resolutions=[res],
        validation_report=report,
        blocking_contradictions=blocking_contradictions,
    )
    assert result.decision == SubmissionDecision.NEEDS_REVIEW
    assert result.can_auto_submit is False
    assert result.risk_tier == RiskTier.HIGH_RISK
    assert any("visa_work_auth" in r.lower() for r in result.reasons)
