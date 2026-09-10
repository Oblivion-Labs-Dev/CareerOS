"""Read-only, evidence-qualified application journey. Never changes submission state."""
from pathlib import Path
from typing import Any

from app.db.store import get_entity, get_kv, session_scope
from app.services.application_assistant.persistence import get_autopilot_job, get_application_draft

SCREENSHOTS = Path(__file__).resolve().parents[3] / "data" / "application_assistant" / "screenshots"
DEFAULT_CONFIRMATION = "Application submitted successfully and confirmed by ATS."


def evidence_path(value: str) -> Path | None:
    if not value:
        return None
    candidate = Path(value).resolve()
    root = SCREENSHOTS.resolve()
    if not candidate.is_relative_to(root) or candidate.suffix.lower() not in {".png", ".jpg", ".jpeg", ".webp"}:
        return None
    return candidate if candidate.is_file() else None


def assess_receipt(job: dict, receipt: dict | None) -> dict:
    if receipt and receipt.get("jobId") != job["id"]:
        receipt = None
    review = (receipt or {}).get("qwenReview") or {}
    text = str((receipt or {}).get("confirmationText") or "").strip()
    confirmed = bool(receipt and review != {"submissionConfirmed": True, "confidence": 0.99} and review.get("submissionConfirmed") is True and text and text != DEFAULT_CONFIRMATION)
    if confirmed:
        return {"state": "confirmed", "label": "ATS confirmation recorded", "explanation": "The archived browser review recorded acceptance with specific confirmation text. Employer response is tracked separately."}
    if job.get("status") in {"NEEDS_REVIEW", "STAGED", "FAILED", "INELIGIBLE", "SKIPPED"}:
        return {"state": "review", "label": "Needs review", "explanation": job.get("ineligibilityDetail") or job.get("skipReason") or job.get("lastError") or "Review the recorded application outcome before taking another action."}
    if job.get("status") == "SUBMITTED":
        return {"state": "uncertain", "label": "Submission not independently confirmed", "explanation": "This application is marked submitted, but a specific archived ATS confirmation is missing. Do not resubmit without checking first."}
    return {"state": "pending", "label": "Not submitted", "explanation": "No confirmed submission is recorded for this application."}


def get_application_journey(job_id: str) -> dict[str, Any] | None:
    with session_scope() as db:
        job = get_autopilot_job(db, job_id)
        if not job:
            return None
        receipt = (get_kv(db, "autopilot_submission_receipts") or {}).get(job_id)
        if receipt and receipt.get("jobId") != job_id:
            receipt = None
        # Explicit identifiers only: never join applications by company name.
        app_id = job.get("applicationId")
        tracker = get_entity(db, "application", app_id) if app_id else None
        draft = get_application_draft(db, app_id) if app_id else None
    events = []
    if job.get("queuedAt"):
        events.append({"title": "Added to application queue", "at": job["queuedAt"], "detail": "Autopilot job record", "source": "application"})
    for checkpoint in job.get("checkpointHistory") or []:
        events.append({"title": checkpoint.get("step") or "Activity", "at": checkpoint.get("timestamp"), "detail": checkpoint.get("details") or "", "source": "automation"})
    if receipt:
        events.append({"title": "Submission receipt archived", "at": receipt.get("submittedAt"), "detail": receipt.get("receiptId"), "source": "receipt"})
    elif job.get("submittedAt"):
        events.append({"title": "Marked submitted", "at": job["submittedAt"], "detail": "No archived receipt linked", "source": "application"})
    if tracker:
        events.append({"title": f"Pipeline: {tracker.get('status') or 'Unknown'}", "at": tracker.get("updatedAt"), "detail": "Linked by application ID", "source": "pipeline"})
    email = (draft or {}).get("emailConfirmation")
    if email:
        events.append({"title": "Tracking-address email recorded", "at": email.get("checkedAt"), "detail": email.get("matchedThreadSubject") or "Email on linked application", "source": "email"})
    events.sort(key=lambda event: event.get("at") or "")
    evidence = []
    for key, label in (("presubmitScreenshot", "Before submission"), ("confirmationScreenshot", "Confirmation page")):
        if receipt and evidence_path(str(receipt.get(key) or "")):
            evidence.append({"kind": key, "label": label, "url": f"/api/backend/application-assistant/jobs/{job_id}/journey/evidence/{key}"})
    return {"jobId": job_id, "assessment": assess_receipt(job, receipt), "events": events,
            "receipt": {key: receipt.get(key) for key in ("receiptId", "submittedAt", "confirmationText", "confirmationUrl", "resumeFileUsed", "tailoringMode", "fieldVerificationStatus", "fieldsCount")} if receipt else None,
            "evidence": evidence, "linkedPipeline": tracker.get("status") if tracker else None,
            "linkedEmail": bool(email), "nextAction": "Review the confirmation evidence and linked responses before applying again." if job.get("status") == "SUBMITTED" else "Review this application's status, resume, and any unanswered questions."}
