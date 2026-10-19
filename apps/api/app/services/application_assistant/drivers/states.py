"""Canonical application-pipeline states.

The production state machine already lives in
``domain.AutopilotJobStatus`` + ``CheckpointStep`` and persists in
``aa_autopilot_job`` entity payloads (asyncio workers, browser runs, browser
restarts — survives process restarts via the entity store).

This module gives that machine its canonical, phase-2 name mapping
(DISCOVERED → … → CONFIRMED) without changing any production state value, so
UI and existing checkpoints stay untouched.
"""

from __future__ import annotations

from typing import Any

# AutopilotJobStatus (existing, persisted) → canonical pipeline state.
PIPELINE_BY_STATUS: dict[str, str] = {
    "DISCOVERED": "DISCOVERED",
    "SCORED": "ELIGIBLE",
    "QUEUED": "ELIGIBLE",
    "APPLYING": "PREPARING",
    "NEEDS_REVIEW": "REVIEW_REQUIRED",
    "MANUAL_REVIEW": "REVIEW_REQUIRED",
    "STAGED": "APPROVED",
    "SUBMITTED": "SUBMITTED",
    "SUBMISSION_UNKNOWN": "SUBMISSION_UNCERTAIN",
    "REJECTED": "FAILED",
    "FAILED": "FAILED",
    "SKIPPED": "BLOCKED",
    "INELIGIBLE": "BLOCKED",
}

_CHECKPOINT_REFINE: dict[str, str] = {
    "FORM_DISCOVERED": "PREPARING",
    "QUESTIONS_COMPLETED": "PREFILLED",
    "RESUME_UPLOADED": "PREFILLED",
    "PRE_SUBMISSION_CHECK": "VALIDATING",
    "SUBMITTING": "SUBMITTING",
    "VERIFYING_SUBMISSION": "CONFIRMING",
    "SUBMITTED": "CONFIRMED",
}


def map_pipeline_state(status: str, checkpoint_step: str = "") -> str:
    """Map an existing autopilot job state to the canonical pipeline.

    Unknown statuses pass through REVIEW_REQUIRED as the safe default for
    statuses that imply human action; anything else that is not in the table
    returns BLOCKED (conservative) rather than inventing a state.
    """

    if not status:
        return "DISCOVERED"
    mapped = PIPELINE_BY_STATUS.get(status.strip().upper())
    if mapped is None:
        return "BLOCKED"
    refine = _CHECKPOINT_REFINE.get((checkpoint_step or "").strip().upper())
    if refine:
        # Only refine forward within the same active family.
        if mapped in ("PREPARING", "APPROVED"):
            return refine
        if mapped == "ELIGIBLE" and refine == "PREPARING":
            return refine
        if mapped == "SUBMITTED" and refine in ("CONFIRMING", "CONFIRMED"):
            return refine
    return mapped


def pipeline_snapshot_from_autopilot_job(job: dict[str, Any]) -> dict[str, Any]:
    """Read-only view for dashboards/audits; never mutates the source record."""

    return {
        "id": job.get("id"),
        "company": job.get("companyName") or job.get("company") or "",
        "title": job.get("title") or "",
        "existingStatus": job.get("status"),
        "checkpoint": job.get("checkpointStep") or job.get("currentStep") or "",
        "pipelineState": map_pipeline_state(
            str(job.get("status") or ""),
            str(job.get("checkpointStep") or job.get("currentStep") or ""),
        ),
    }
