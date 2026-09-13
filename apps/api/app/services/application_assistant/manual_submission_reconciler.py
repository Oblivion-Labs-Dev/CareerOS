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


def _legacy_key(company: Any, sent_at: Any) -> str:
    """Identifies a confirmation email without its UID.

    Jobs marked before UIDs were recorded carry only the employer and the
    email's timestamp, which together still pick out one email. Without this
    every one of those emails would look unspent on the next run and be
    credited to a second job all over again.
    """
    stamp = sent_at.isoformat() if isinstance(sent_at, datetime) else str(sent_at or "")
    return f"legacy:{_normalise(company)}|{stamp}"


def _spent_confirmations(jobs: list[dict[str, Any]]) -> set[str]:
    """Confirmation emails already credited to some job.

    The in-run `consumed` set only ever protected a single call. The reconciler
    runs repeatedly, and each fresh run started with an empty set, so the same
    email was free to mark a second job, then a third. Reading back what earlier
    runs recorded is what makes "one email, one application" actually hold.
    """
    spent: set[str] = set()
    for job in jobs:
        if job.get("submissionSource") != "email-detected":
            continue
        evidence = job.get("submissionEvidence") or {}
        uid = str(evidence.get("confirmationUid") or "")
        if uid:
            spent.add(uid)
        else:
            # Only rows written before UIDs were recorded need the coarser key.
            # Applying it to every row would make two genuine confirmations that
            # happen to share a timestamp look like one.
            spent.add(_legacy_key(job.get("company"), job.get("submittedAt")))
    return spent


def _title_in_subject(title: Any, subject: str) -> bool:
    """Whether the subject names this specific role.

    Only a handful of employers put the role in the subject ("We've received
    your application for Senior CIAM Software Engineer at Affirm"), but when one
    does, the email belongs to exactly one open application and should not be
    spent on a sibling posting at the same company.
    """
    title_words = _significant_title_words(str(title or ""))
    if len(title_words) < 2:
        return False
    subject_words = _significant_title_words(subject)
    return title_words.issubset(subject_words)


_TITLE_STOPWORDS = frozenset({
    "the", "and", "for", "at", "of", "to", "a", "an", "in", "on",
    "thank", "thanks", "you", "your", "applying", "application", "received",
    "we", "ve", "have", "interest", "joining", "position", "role",
})


def _significant_title_words(text: str) -> set[str]:
    words = re.findall(r"[a-z0-9]+", (text or "").lower())
    return {w for w in words if w not in _TITLE_STOPWORDS and len(w) > 1}


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
        all_jobs = list_autopilot_jobs(session)
        candidates = [
            job for job in all_jobs
            if job.get("status") in RECONCILABLE_STATUSES and job.get("company")
        ]
        candidates.sort(key=lambda j: str(j.get("updatedAt") or ""), reverse=True)
        if not candidates:
            return {"success": True, "checked": 0, "marked": 0, "jobs": []}

        # Emails already spent on an earlier run of this reconciler. Without
        # this the `consumed` set below only held for the length of one call,
        # so the next run re-spent the same email on the next open job at that
        # employer: one "Thank you for applying to Coinbase" marked fifteen
        # Coinbase jobs submitted across fifteen runs, ServiceNow twelve —
        # including jobs whose last checkpoint was FAILED or SKIPPED.
        already_spent = _spent_confirmations(all_jobs)

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
        # Seeded from what previous runs already spent, so the guard holds
        # across calls and not merely within one.
        consumed: set[str] = set(already_spent)

        claimed: set[str] = set()

        def _eligible(job: dict[str, Any], haystack: str, sent_at: datetime) -> bool:
            if job["id"] in claimed:
                return False
            company_key = _normalise(job.get("company"))
            if not company_key:
                return False
            if company_key not in haystack:
                return False
            # Anchor on when the job entered the queue, not on updatedAt.
            # updatedAt moves for any bookkeeping write — a status correction, a
            # re-run of this very reconciler — and using it made every
            # confirmation look "too old" the moment anything touched the row.
            attempted_at = _parse_date(
                job.get("queuedAt") or job.get("discoveredAt") or job.get("updatedAt")
            )
            # An old confirmation for the same employer is not evidence for
            # this attempt. Allow a little slack for clock skew only.
            if attempted_at and sent_at < attempted_at - timedelta(minutes=10):
                return False
            return True

        def _mark(job: dict[str, Any], subject: str, sent_at: datetime, uid: str, matched_on: str) -> None:
            job["previousStatus"] = job.get("status")
            job["status"] = "SUBMITTED"
            job["submittedAt"] = sent_at.isoformat()
            job["submissionSource"] = "email-detected"
            job["hasPersistentBlock"] = False
            evidence = dict(job.get("submissionEvidence") or {})
            evidence["confirmationText"] = subject[:200]
            evidence["confirmationSource"] = "gmail"
            # Recorded so a later run can see this email is already spent.
            evidence["confirmationUid"] = uid
            evidence["confirmationMatchedOn"] = matched_on
            job["submissionEvidence"] = evidence
            job["updatedAt"] = now_iso()
            save_autopilot_job(session, job)
            if uid:
                consumed.add(uid)
            else:
                consumed.add(_legacy_key(job.get("company"), sent_at))
            claimed.add(job["id"])
            marked.append({"id": job["id"], "company": job.get("company", ""), "subject": subject[:90]})
            logger.info(
                "Marked %s (%s) submitted from its confirmation email, matched on %s",
                job.get("company"), job.get("title", ""), matched_on,
            )

        # Iterate emails, not jobs: an email is the scarce thing here, and each
        # one may be spent at most once. Title-bearing subjects are resolved
        # first, because they name the single application they belong to; only
        # what is left over is matched on the employer alone.
        usable: list[tuple[str, str, datetime, str]] = []
        for thread in threads:
            uid = str(thread.get("uid") or "")
            if uid and uid in consumed:
                continue
            subject = str(thread.get("subject") or "")
            if not CONFIRMATION_PATTERN.search(subject):
                continue
            sent_at = _parse_date(thread.get("date"))
            if sent_at is None or sent_at < cutoff:
                continue
            haystack = _normalise(f"{subject} {thread.get('fromName') or ''}")
            usable.append((subject, haystack, sent_at, uid))

        for pass_name in ("title", "company"):
            for subject, haystack, sent_at, uid in usable:
                if uid and uid in consumed:
                    continue
                matches = [job for job in candidates if _eligible(job, haystack, sent_at)]
                # Drop any whose employer already has this exact email spent on
                # an older row that predates confirmationUid.
                matches = [
                    job for job in matches
                    if _legacy_key(job.get("company"), sent_at) not in consumed
                ]
                if not matches:
                    continue
                if pass_name == "title":
                    matches = [job for job in matches if _title_in_subject(job.get("title"), subject)]
                    if len(matches) != 1:
                        # Either the subject names no role, or it names one that
                        # fits several open jobs. Leave it for the company pass.
                        continue
                elif pass_name == "company":
                    # Company-only match: at most ONE job gets credit. Pick the
                    # most recently attempted (the likeliest to be the one the
                    # candidate just submitted manually). Without this cap the
                    # same email marked every open job at the same employer.
                    matches.sort(
                        key=lambda j: str(j.get("updatedAt") or j.get("queuedAt") or ""),
                        reverse=True,
                    )
                    matches = matches[:1]
                _mark(matches[0], subject, sent_at, uid, pass_name)

        return {"success": True, "checked": len(candidates), "marked": len(marked), "jobs": marked}

    if db is not None:
        return _run(db)
    with session_scope() as owned:
        return _run(owned)
