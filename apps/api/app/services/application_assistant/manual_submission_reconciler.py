"""Mark an application submitted when its confirmation email arrives.

Applications the automation cannot finish — a CAPTCHA-guarded board, a question
only the candidate can answer — are completed by hand. Requiring the user to
then come back and press "Mark submitted" means the list is only as accurate as
their memory, and it is the kind of bookkeeping people stop doing.

Employers do not send webhooks, but every ATS sends the candidate a confirmation
email, and CareerOS already reads that inbox. So the confirmation itself is the
signal: when a "Thank you for applying to X" lands for a job still sitting in
manual review, that job is submitted, and it says so on its own.

Deliberately conservative, because marking a job submitted hides it from the
list the user works through — a false positive costs them an application they
never sent:

* only jobs the user could plausibly have just submitted are considered
  (MANUAL_REVIEW, NEEDS_REVIEW, FAILED) — never a queued job the automation
  still intends to try;
* the company on the email has to match the company on the job;
* the email has to be newer than the job's last attempt, so an old confirmation
  from a previous application to the same employer proves nothing;
* security-code and "we received your resume" style mails are ignored — only
  wording that states the application itself arrived counts.
"""

from __future__ import annotations

import logging
import re
from datetime import datetime, timedelta, timezone
from typing import Any

from sqlalchemy.orm import Session

from app.db.store import now_iso, session_scope
from app.services.application_assistant.persistence import (
    list_autopilot_jobs,
    save_autopilot_job,
)

logger = logging.getLogger("career_os.manual_submission_reconciler")

RECONCILABLE_STATUSES = ("MANUAL_REVIEW", "NEEDS_REVIEW", "FAILED")

# Wording that means the application itself was received. A Greenhouse security
# code is sent *before* the submission completes, so it must never count.
CONFIRMATION_PATTERN = re.compile(
    r"thank you for applying"
    r"|thanks for applying"
    r"|we.{0,3}ve received your application"
    r"|received your application"
    r"|application (?:was |has been )?received"
    r"|thank you for your interest in joining",
    re.IGNORECASE,
)

SEARCH_TERMS = (
    "Thank you for applying",
    "Thanks for applying",
    "received your application",
    "Thank you for your interest",
)


def _normalise(name: str) -> str:
    """Company names as they compare: lowercase, alphanumeric only.

    Boards spell the same employer several ways ("Doordashusa", "DoorDash USA"),
    so punctuation and spacing cannot be part of the comparison.
    """
    return re.sub(r"[^a-z0-9]+", "", (name or "").lower())


def _parse_date(value: Any) -> datetime | None:
    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=timezone.utc)
    text = str(value or "").strip()
    if not text:
        return None
    try:
        from email.utils import parsedate_to_datetime

        parsed = parsedate_to_datetime(text)
        return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)
    except Exception:
        pass
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
        return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)
    except Exception:
        return None


def _fetch_confirmations(limit: int) -> list[dict[str, Any]]:
    """Recent confirmation emails as {company-ish subject, from, date}."""
    from app.config import settings
    from app.services.gmail_imap import GmailImapClient

    if not getattr(settings, "gmail_user", "") or not getattr(settings, "gmail_app_password", ""):
        return []

    client = GmailImapClient(settings.gmail_user, settings.gmail_app_password)
    connection = client._connect()  # noqa: SLF001 — reusing the shared helpers
    try:
        client._open_mailbox(connection)  # noqa: SLF001
        uids: set[str] = set()
        for term in SEARCH_TERMS:
            try:
                status, data = connection.uid("search", None, f'(SUBJECT "{term}")')
                if status == "OK" and data and data[0]:
                    uids.update(data[0].decode().split())
            except Exception:
                continue
        ordered = sorted(uids, key=int)[-limit:]
    finally:
        try:
            connection.logout()
        except Exception:
            pass

    if not ordered:
        return []
    return client._fetch_uids(ordered, include_body=False)  # noqa: SLF001


def reconcile_manual_submissions(
    db: Session | None = None, *, limit: int = 120, window_days: int = 21
) -> dict[str, Any]:
    """Mark manually-completed applications submitted from their confirmation email."""
    def _run(session: Session) -> dict[str, Any]:
        candidates = [
            job for job in list_autopilot_jobs(session)
            if job.get("status") in RECONCILABLE_STATUSES and job.get("company")
        ]
        candidates.sort(key=lambda j: str(j.get("updatedAt") or ""), reverse=True)
        if not candidates:
            return {"success": True, "checked": 0, "marked": 0, "jobs": []}

        try:
            threads = _fetch_confirmations(limit)
        except Exception as exc:  # noqa: BLE001
            logger.warning("Could not read the inbox: %s", exc)
            return {"success": False, "reason": str(exc), "checked": len(candidates), "marked": 0, "jobs": []}

        cutoff = datetime.now(timezone.utc) - timedelta(days=window_days)
        marked: list[dict[str, str]] = []
        # One confirmation email confirms exactly one application. Most subjects
        # name only the employer ("Thank you for applying to Robinhood"), so
        # without this a single email marked every open Robinhood job as
        # submitted — six applications the candidate had not actually sent.
        consumed: set[str] = set()

        for job in candidates:
            company_key = _normalise(job.get("company"))
            if not company_key:
                continue
            # Anchor on when the job entered the queue, not on updatedAt.
            # updatedAt moves for any bookkeeping write — a status correction, a
            # re-run of this very reconciler — and using it made every
            # confirmation look "too old" the moment anything touched the row.
            attempted_at = _parse_date(
                job.get("queuedAt") or job.get("discoveredAt") or job.get("updatedAt")
            )

            for thread in threads:
                uid = str(thread.get("uid") or "")
                if uid and uid in consumed:
                    continue
                subject = str(thread.get("subject") or "")
                if not CONFIRMATION_PATTERN.search(subject):
                    continue
                haystack = _normalise(f"{subject} {thread.get('fromName') or ''}")
                if company_key not in haystack:
                    continue
                sent_at = _parse_date(thread.get("date"))
                if sent_at is None or sent_at < cutoff:
                    continue
                # An old confirmation for the same employer is not evidence for
                # this attempt. Allow a little slack for clock skew only.
                if attempted_at and sent_at < attempted_at - timedelta(minutes=10):
                    continue

                job["previousStatus"] = job.get("status")
                job["status"] = "SUBMITTED"
                job["submittedAt"] = sent_at.isoformat()
                job["submissionSource"] = "email-detected"
                job["hasPersistentBlock"] = False
                evidence = dict(job.get("submissionEvidence") or {})
                evidence["confirmationText"] = subject[:200]
                evidence["confirmationSource"] = "gmail"
                job["submissionEvidence"] = evidence
                job["updatedAt"] = now_iso()
                save_autopilot_job(session, job)
                if uid:
                    consumed.add(uid)
                marked.append({"id": job["id"], "company": job.get("company", ""), "subject": subject[:90]})
                logger.info("Marked %s submitted from its confirmation email", job.get("company"))
                break

        return {"success": True, "checked": len(candidates), "marked": len(marked), "jobs": marked}

    if db is not None:
        return _run(db)
    with session_scope() as owned:
        return _run(owned)
