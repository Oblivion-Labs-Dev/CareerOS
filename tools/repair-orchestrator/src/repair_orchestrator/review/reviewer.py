from __future__ import annotations

from typing import Any

from repair_orchestrator.models import ReviewResult, RiskLevel
from repair_orchestrator.security.guardrails import requires_human_review


def review_patch(task: dict[str, Any], validation: dict[str, Any] | None = None) -> ReviewResult:
    """Independent mock reviewer — separate from coding agent."""
    changed_files = task.get("changedFiles") or task.get("suspectedSourceFiles") or []
    if isinstance(changed_files, str):
        changed_files = [changed_files]

    validation_passed = bool((validation or task.get("validation") or {}).get("passed"))
    component = str(task.get("component") or "")

    findings: list[str] = []
    required_actions: list[str] = []
    risk: RiskLevel = "low"

    if not validation_passed:
        return ReviewResult(
            decision="reject",
            confidence=0.95,
            summary="Validation failed; patch cannot be approved.",
            findings=["Deterministic validation did not pass."],
            requiredActions=["Fix failing validation commands and retry."],
            riskLevel="medium",
        )

    if requires_human_review(
        component,
        changed_files,
        extra_context=" ".join(
            [
                str(task.get("patchSummary") or ""),
                str(task.get("exceptionMessage") or ""),
                str(task.get("title") or ""),
            ]
        ),
    ):
        risk = "high"
        findings.append("Change touches a category that requires human review.")
        required_actions.append("Obtain human approval before merge.")
        return ReviewResult(
            decision="human_review",
            confidence=0.85,
            summary="Patch appears reasonable but requires human review due to sensitive scope.",
            findings=findings,
            requiredActions=required_actions,
            riskLevel=risk,
        )

    patch_summary = str(task.get("patchSummary") or "")
    if not patch_summary and not changed_files:
        return ReviewResult(
            decision="needs_changes",
            confidence=0.7,
            summary="No patch artifacts were recorded.",
            findings=["Missing diff summary and changed files."],
            requiredActions=["Re-run coding agent with recorded diff."],
            riskLevel="medium",
        )

    findings.append("Patch scope is limited and validation passed.")
    return ReviewResult(
        decision="approve",
        confidence=0.8,
        summary="Independent reviewer approves the patch for human merge review.",
        findings=findings,
        requiredActions=["Manual PR creation and merge approval still required."],
        riskLevel=risk,
    )
