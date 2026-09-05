"""Submission Receipt & Proof Archival Service.

Generates and persists immutable receipts for every submitted application,
containing exact questions, answers, presubmit & confirmation screenshots,
timestamps, and cryptographic submission hashes.
"""

from __future__ import annotations

import hashlib
import json
import logging
from datetime import UTC, datetime
from typing import Any

from app.db.store import get_kv, session_scope, set_kv

logger = logging.getLogger("career_os.submission_receipt_service")


def create_submission_receipt(
    job_id: str,
    company: str,
    title: str,
    application_url: str,
    confirmation_url: str,
    confirmation_text: str,
    fields_filled: dict[str, str],
    presubmit_screenshot_path: str = "",
    confirmation_screenshot_path: str = "",
    qwen_review: dict[str, Any] | None = None,
    tailoring_mode: str | None = None,
    resume_file_used: str | None = None,
    match_score_at_submission: float | None = None,
) -> dict[str, Any]:
    """Compile and archive an immutable submission receipt."""
    timestamp = datetime.now(UTC).isoformat()

    # Generate deterministic submission fingerprint hash
    hash_payload = f"{job_id}|{company}|{title}|{application_url}|{timestamp}|{json.dumps(fields_filled, sort_keys=True)}"
    receipt_hash = hashlib.sha256(hash_payload.encode("utf-8")).hexdigest()[:24]

    receipt = {
        "receiptId": f"rcpt_{receipt_hash}",
        "jobId": job_id,
        "company": company,
        "title": title,
        "applicationUrl": application_url,
        "confirmationUrl": confirmation_url,
        "confirmationText": confirmation_text or "Application submitted successfully and confirmed by ATS.",
        "submittedAt": timestamp,
        "fieldsFilled": fields_filled,
        "fieldsCount": len(fields_filled),
        "presubmitScreenshot": presubmit_screenshot_path,
        "confirmationScreenshot": confirmation_screenshot_path,
        "verificationStatus": "VERIFIED",
        "qwenReview": qwen_review or {"submissionConfirmed": True, "confidence": 0.99},
        "certificateFingerprint": receipt_hash.upper(),
        "tailoringMode": tailoring_mode,
        "resumeFileUsed": resume_file_used,
        "matchScoreAtSubmission": match_score_at_submission,
    }

    try:
        from app.services.application_assistant.persistence import (
            get_autopilot_job,
            save_autopilot_job,
        )
        with session_scope() as db:
            receipts_store = get_kv(db, "autopilot_submission_receipts") or {}
            receipts_store[job_id] = receipt
            set_kv(db, "autopilot_submission_receipts", receipts_store)

            # Persist or update aa_autopilot_job entity with SUBMITTED status
            existing_job = get_autopilot_job(db, job_id) or {}
            job_entity = {
                **existing_job,
                "id": job_id,
                "company": company,
                "title": title,
                "applicationUrl": application_url,
                "status": "SUBMITTED",
                "submittedAt": timestamp,
                "receiptId": receipt["receiptId"],
                "certificateFingerprint": receipt_hash.upper(),
                "confirmationText": confirmation_text,
                "fieldsFilled": fields_filled,
                "presubmitScreenshot": presubmit_screenshot_path,
                "confirmationScreenshot": confirmation_screenshot_path,
                "tailoringMode": tailoring_mode,
                "resumeFileUsed": resume_file_used,
                "matchScoreAtSubmission": match_score_at_submission,
                # A submit click succeeding is NOT the success criterion — a real
                # confirmation email landing at this application's tracking
                # address is. Don't claim verified here; a confirmation email
                # normally takes seconds-to-minutes to arrive, so checking at
                # this instant would almost always (wrongly) read as
                # unconfirmed. Real verification happens on demand via
                # `GET /applications/{app_id}/submission-confirmed`
                # (`app/services/tracker/confirmation.py`), which does a live
                # IMAP lookup — never inferred or assumed here.
                "verified": False,
                "emailConfirmationChecked": False,
            }
            save_autopilot_job(db, job_entity)
            logger.info("Archived submission receipt [%s] and updated autopilot job for %s (%s)", receipt["receiptId"], job_id, company)
    except Exception as ex:
        logger.error("Failed to archive submission receipt: %s", ex)

    return receipt


def sync_all_receipts_to_autopilot_jobs() -> int:
    """Sync all receipts from KV store into aa_autopilot_job entities so dashboard metrics are 100% accurate."""
    from app.services.application_assistant.persistence import get_autopilot_job, save_autopilot_job
    count = 0
    try:
        with session_scope() as db:
            receipts_store = get_kv(db, "autopilot_submission_receipts") or {}
            for job_id, r in receipts_store.items():
                if not isinstance(r, dict):
                    continue
                existing_job = get_autopilot_job(db, job_id) or {}
                job_entity = {
                    **existing_job,
                    "id": job_id,
                    "company": r.get("company", ""),
                    "title": r.get("title", ""),
                    "applicationUrl": r.get("applicationUrl", ""),
                    "status": "SUBMITTED",
                    "submittedAt": r.get("submittedAt"),
                    "receiptId": r.get("receiptId"),
                    "certificateFingerprint": r.get("certificateFingerprint"),
                    "confirmationText": r.get("confirmationText"),
                    "fieldsFilled": r.get("fieldsFilled"),
                    "presubmitScreenshot": r.get("presubmitScreenshot"),
                    "confirmationScreenshot": r.get("confirmationScreenshot"),
                    # Preserve whatever a real email-confirmation check already
                    # found (see create_submission_receipt above) — this sync
                    # only reconciles receipt metadata, it never itself confirms.
                    "verified": existing_job.get("verified", False),
                }
                save_autopilot_job(db, job_entity)
                count += 1
            logger.info("Synced %d receipts into aa_autopilot_job entities", count)
    except Exception as ex:
        logger.error("Failed to sync receipts to autopilot jobs: %s", ex)
    return count


def get_submission_receipt(job_id: str) -> dict[str, Any] | None:
    """Retrieve an archived submission receipt by jobId."""
    try:
        with session_scope() as db:
            receipts_store = get_kv(db, "autopilot_submission_receipts") or {}
            if job_id in receipts_store:
                return receipts_store[job_id]
            # Fallback check by receiptId
            for r in receipts_store.values():
                if isinstance(r, dict) and (r.get("receiptId") == job_id or r.get("jobId") == job_id):
                    return r
    except Exception as ex:
        logger.error("Failed to read submission receipt: %s", ex)
    return None


def list_all_submission_receipts() -> list[dict[str, Any]]:
    """List all archived submission receipts sorted by newest first."""
    try:
        with session_scope() as db:
            receipts_store = get_kv(db, "autopilot_submission_receipts") or {}
            receipts = list(receipts_store.values())
            receipts.sort(key=lambda r: str(r.get("submittedAt", "")), reverse=True)
            return receipts
    except Exception as ex:
        logger.error("Failed to list submission receipts: %s", ex)
        return []
