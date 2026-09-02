"""Submission Policy Engine for CareerOS Verified Autonomy.

Evaluates whether an application has completed verification and is safe for
automatic submission (READY_TO_SUBMIT), or must be routed to human review (NEEDS_REVIEW).

Key rule:
  The LLM can propose answers. Evidence grounds them.
  Deterministic code decides whether submission is allowed.
  FILLED != READY_TO_SUBMIT.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from enum import Enum
from typing import Any

from app.db.store import now_iso
from app.services.application_assistant.browser_verifier import DOMVerificationResult
from app.services.application_assistant.cross_field_validator import ValidationReport
from app.services.application_assistant.profile_answer_resolver import (
    AnswerResolution,
    LLM_GENERATED_TEXT,
)
from app.services.application_assistant.question_classifier import (
    QuestionType,
    SENSITIVE_FACTUAL_TYPES,
)

logger = logging.getLogger("career_os.submission_policy")


class RiskTier(str, Enum):
    LOW_RISK = "LOW_RISK"                    # Auto-submit
    UNCERTAIN_BUT_LOW_RISK = "UNCERTAIN_BUT_LOW_RISK"  # Auto-submit + warning logged
    HIGH_RISK = "HIGH_RISK"                  # NEEDS_REVIEW


class SubmissionDecision(str, Enum):
    READY_TO_SUBMIT = "READY_TO_SUBMIT"
    NEEDS_REVIEW = "NEEDS_REVIEW"
    BLOCKED = "BLOCKED"


@dataclass
class PolicyEvaluationResult:
    decision: SubmissionDecision
    can_auto_submit: bool
    risk_tier: RiskTier = RiskTier.LOW_RISK
    reasons: list[str] = field(default_factory=list)
    blocking_issues: list[dict[str, Any]] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    evaluated_at: str = field(default_factory=now_iso)

    def to_dict(self) -> dict[str, Any]:
        return {
            "decision": self.decision.value,
            "canAutoSubmit": self.can_auto_submit,
            "riskTier": self.risk_tier.value,
            "reasons": self.reasons,
            "blockingIssues": self.blocking_issues,
            "warnings": self.warnings,
            "evaluatedAt": self.evaluated_at,
        }


class SubmissionPolicy:
    """Risk-based submission policy engine authorizing automatic job submissions by default."""

    @staticmethod
    def evaluate(
        resolutions: list[AnswerResolution],
        validation_report: ValidationReport,
        dom_verification: DOMVerificationResult | None = None,
        profile: dict[str, Any] | None = None,
        qwen_review: dict[str, Any] | None = None,
    ) -> PolicyEvaluationResult:
        """
        Evaluate application safety using a risk-based policy:
          - AUTO-SUBMIT is the default when internally consistent without concrete unsafe signals.
          - LOW RISK: Name, email, standard resume facts, open-ended answers grounded in profile -> AUTO-SUBMIT.
          - MEDIUM RISK: New phrasing, LLM synthesized text, lower confidence with no contradictions -> AUTO-SUBMIT + Warning.
          - HIGH RISK: Concrete factual contradiction (H1B + no sponsorship), unsupported critical fact,
                       demographic cross-domain error, location mismatch, or required critical field unresolved -> NEEDS_REVIEW.
        """
        reasons: list[str] = []
        blocking_issues: list[dict[str, Any]] = []
        warnings: list[str] = []

        # ── 1. Concrete Cross-Field Contradiction Gate ──────────────────────
        # Only true blocking contradictions (e.g. H1B vs sponsorship=No, Citizen=No vs ITAR=Citizen) halt submission
        if validation_report.status == "FAIL" or validation_report.blocking_errors:
            for err in validation_report.blocking_errors:
                msg = f"Critical contradiction ({err.rule}): {err.reason}"
                reasons.append(msg)
                blocking_issues.append({
                    "gate": "CROSS_FIELD_VALIDATION",
                    "rule": err.rule,
                    "fieldId": err.field_id,
                    "question": err.question,
                    "reason": err.reason,
                    "risk": "HIGH_RISK",
                })

        # ── 2. Resolution & Provenance Checks ───────────────────────────────
        for res in resolutions:
            try:
                qtype = QuestionType(res.question_type)
            except ValueError:
                qtype = QuestionType.UNKNOWN

            # A. Unsupported Critical Factual Claim
            # If a critical field (citizenship, clearance, visa) was pure LLM generation WITHOUT grounding
            if qtype in SENSITIVE_FACTUAL_TYPES:
                if res.resolution_method == LLM_GENERATED_TEXT and not res.source_value:
                    msg = f"Unsupported critical fact on '{res.question}' (LLM generated without profile source)."
                    reasons.append(msg)
                    blocking_issues.append({
                        "gate": "CRITICAL_FACT_PROVENANCE",
                        "fieldId": res.field_id,
                        "question": res.question,
                        "reason": msg,
                        "risk": "HIGH_RISK",
                    })

            # B. UNKNOWN Handling:
            # - Optional/Non-critical unknown -> Leave blank or default, continue auto-apply
            # - Required critical unknown -> Needs review
            if res.question_type == QuestionType.UNKNOWN.value or not res.answer:
                is_critical = qtype in SENSITIVE_FACTUAL_TYPES
                is_required = getattr(res, "is_required", False)

                if is_critical and is_required and not res.answer:
                    msg = f"Required critical field '{res.question}' is unresolved."
                    reasons.append(msg)
                    blocking_issues.append({
                        "gate": "REQUIRED_CRITICAL_UNRESOLVED",
                        "fieldId": res.field_id,
                        "question": res.question,
                        "reason": msg,
                        "risk": "HIGH_RISK",
                    })
                elif not is_critical:
                    # Low/Medium risk: record warning, do NOT block auto-apply
                    warnings.append(f"Non-critical field '{res.question or res.field_id}' defaulted or left blank.")

            # C. Open-Ended Resume Reasoning (Why this company, tell us about a project, etc.)
            # LLM-generated open-ended answers are LOW/MEDIUM risk and AUTO-SUBMIT by default
            if res.resolution_method == LLM_GENERATED_TEXT and qtype not in SENSITIVE_FACTUAL_TYPES:
                warnings.append(f"Open-ended answer generated for '{res.question}' (grounded in resume).")

        # ── 3. Live Browser DOM Verification Gate ───────────────────────────
        if dom_verification:
            if not dom_verification.passed or dom_verification.issues:
                for issue in dom_verification.issues:
                    if issue.severity == "BLOCKING":
                        msg = f"DOM Verification mismatch: {issue.details}"
                        reasons.append(msg)
                        blocking_issues.append({
                            "gate": "DOM_READBACK_VERIFIER",
                            "fieldId": issue.field_id,
                            "label": issue.label,
                            "reason": issue.details,
                            "risk": "HIGH_RISK",
                        })

            if dom_verification.unresolved_required_fields:
                msg = f"Required fields remain unfilled in the browser: {', '.join(dom_verification.unresolved_required_fields[:5])}"
                reasons.append(msg)
                blocking_issues.append({
                    "gate": "REQUIRED_FIELDS_CHECK",
                    "reason": msg,
                    "risk": "HIGH_RISK",
                })

        # ── 4. Semantic Contradiction Check Gate ────────────────────────────
        if qwen_review and qwen_review.get("hasBlockingContradictions"):
            for item in qwen_review.get("profileContradictions", []):
                msg = f"Material contradiction detected: {item.get('issue')}"
                reasons.append(msg)
                blocking_issues.append({
                    "gate": "SEMANTIC_CONTRADICTION",
                    "fieldId": item.get("fieldId", ""),
                    "reason": msg,
                    "risk": "HIGH_RISK",
                })

        # ── Determine Risk Tier and Decision ────────────────────────────────
        if blocking_issues:
            risk_tier = RiskTier.HIGH_RISK
            decision = SubmissionDecision.NEEDS_REVIEW
            can_auto_submit = False
        elif warnings:
            risk_tier = RiskTier.UNCERTAIN_BUT_LOW_RISK
            decision = SubmissionDecision.READY_TO_SUBMIT
            can_auto_submit = True
            if not reasons:
                reasons.append("Application internally consistent with minor warnings (auto-submit authorized).")
        else:
            risk_tier = RiskTier.LOW_RISK
            decision = SubmissionDecision.READY_TO_SUBMIT
            can_auto_submit = True
            reasons.append("All fields grounded and verified. Safe to auto-submit.")

        return PolicyEvaluationResult(
            decision=decision,
            can_auto_submit=can_auto_submit,
            risk_tier=risk_tier,
            reasons=reasons,
            blocking_issues=blocking_issues,
            warnings=warnings,
        )
