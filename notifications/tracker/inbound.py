"""Inbound Recruiter Email Sync & Status Routing Service.

Parses incoming emails from recruiters, ATS notifications, and interview scheduling
links, automatically updating the job application status in CareerOS.
"""

from __future__ import annotations

import logging
import re
from datetime import datetime, timezone
from typing import Any

from app.db.store import get_kv, set_kv, session_scope

logger = logging.getLogger("career_os.inbound_email_tracker")

# Regex heuristics for email classification
INTERVIEW_PATTERNS = [
    r"interview",
    r"schedule a (?:time|chat|call|conversation)",
    r"calendly\.com",
    r"goodtime\.io",
    r"next steps? in our process",
    r"speaking with (?:the team|our engineers|our recruiter)",
    r"coding assessment",
    r"hackerrank",
    r"codesignal",
    r"take-home",
]

REJECTION_PATTERNS = [
    r"unfortunately",
    r"not moving forward",
    r"pursue other candidates",
    r"decided to move forward with other",
    r"impressive background.*not a match",
    r"position has been filled",
    r"at this time, we will not be",
]

CONFIRMATION_PATTERNS = [
    r"application received",
    r"thank you for applying",
    r"we have received your application",
    r"application submitted successfully",
    r"thanks for your interest in",
]


def classify_inbound_email(subject: str, body: str) -> dict[str, Any]:
    """Classify incoming email text into event type and confidence."""
    text = f"{subject}\n{body}".lower()

    # 1. Check Interview / Next Steps
    for pat in INTERVIEW_PATTERNS:
        if re.search(pat, text, re.IGNORECASE):
            return {
                "eventType": "INTERVIEW_INVITE",
                "status": "INTERVIEWING",
                "confidence": 0.95,
                "reason": f"Matched interview keyword pattern: '{pat}'",
            }

    # 2. Check Rejection
    for pat in REJECTION_PATTERNS:
        if re.search(pat, text, re.IGNORECASE):
            return {
                "eventType": "REJECTION",
                "status": "REJECTED",
                "confidence": 0.96,
                "reason": f"Matched rejection pattern: '{pat}'",
            }

    # 3. Check Submission Confirmation
    for pat in CONFIRMATION_PATTERNS:
        if re.search(pat, text, re.IGNORECASE):
            return {
                "eventType": "SUBMISSION_CONFIRMED",
                "status": "APPLIED",
                "confidence": 0.99,
                "reason": "Official ATS receipt confirmation email",
            }

    return {
        "eventType": "GENERAL_UPDATE",
        "status": "PENDING",
        "confidence": 0.5,
        "reason": "General correspondence or notification",
    }


def process_inbound_email(
    sender: str,
    subject: str,
    body: str,
    received_at: str | None = None,
) -> dict[str, Any]:
    """Process an incoming email, match it to an existing application, and record status update."""
    classification = classify_inbound_email(subject, body)
    timestamp = received_at or datetime.now(timezone.utc).isoformat()

    matched_job_id = None
    matched_company = None

    # Match sender domain or subject to an applied job
    try:
        with session_scope() as db:
            queue = get_kv(db, "autopilot_job_queue") or []
            subject_low = subject.lower()
            body_low = body.lower()
            sender_low = sender.lower()

            for job in queue:
                comp = str(job.get("company", "")).lower()
                title = str(job.get("title", "")).lower()

                if comp and (comp in subject_low or comp in sender_low or comp in body_low):
                    matched_job_id = job.get("id")
                    matched_company = job.get("company")
                    # Update status if interview or rejection
                    if classification["status"] in ("INTERVIEWING", "REJECTED"):
                        job["status"] = classification["status"]
                        job["lastActivity"] = f"Email: {classification['eventType']} ({timestamp[:10]})"
                    break

            if matched_job_id:
                set_kv(db, "autopilot_job_queue", queue)
                logger.info("Matched inbound email from %s to job %s (%s) -> %s", sender, matched_job_id, matched_company, classification["status"])
    except Exception as ex:
        logger.error("Error processing inbound email: %s", ex)

    record = {
        "id": f"email_{datetime.now(timezone.utc).strftime('%Y%m%d%H%M%S')}_{hash(sender + subject) % 10000}",
        "sender": sender,
        "subject": subject,
        "receivedAt": timestamp,
        "classification": classification,
        "matchedJobId": matched_job_id,
        "matchedCompany": matched_company,
    }

    # Append to email activity log
    try:
        with session_scope() as db:
            email_log = get_kv(db, "inbound_email_activity") or []
            email_log.insert(0, record)
            set_kv(db, "inbound_email_activity", email_log[:100])
    except Exception as ex:
        logger.warning("Failed to store email log: %s", ex)

    return record
