"""Sync manually-submitted job applications from Gmail into the tracker.

CareerOS's own Autopilot submissions are already tracked as `aa_autopilot_job`
entities. This module covers the other half of a job search — applications the
user submitted themselves, outside CareerOS entirely — by scanning the inbox
for ATS "thank you for applying" confirmation emails and turning genuinely new
ones into `application` entities so the Dashboard's pipeline and analytics
reflect the full picture, not just what Autopilot itself did.

Company/role extraction is deliberately conservative: if a subject line
doesn't match a recognizable "applying to <Company>" pattern, we fall back to
a cleaned sender display name rather than guessing a role title outright.
"""

from __future__ import annotations

import re
from datetime import datetime
from typing import Any

from sqlalchemy.orm import Session

from app.config import settings
from app.db.store import list_entities, new_id, now_iso, upsert_entity
from app.services.gmail_imap import GmailImapClient

ENTITY_TYPE = "application"
SOURCE_TAG = "gmail_manual"

# Same phrasing as the "applied" category in tracker/classification.py, used
# here as literal Gmail SUBJECT search terms (IMAP SUBJECT search is a
# case-insensitive substring match).
APPLIED_SUBJECT_TERMS = (
    "thank you for applying",
    "application received",
    "we have received your application",
    "successfully submitted",
    "thanks for your interest in",
    "application has been received",
    "thank you for your application",
    "we've received your application",
)

# Sender/company display-name noise to strip when falling back to the "From"
# header for a company name (e.g. "Stripe Careers <no-reply@stripe.com>").
_NAME_SUFFIX_PAT = re.compile(
    r"\s*[-|@]?\s*(careers?|talent\s*acquisition|recruiting( team)?|hr team|hiring team|no-?reply|jobs?"
    r"|icims|greenhouse|workday|lever|ashby|smartrecruiters|taleo|workable|bamboohr|jobvite)\s*$",
    re.IGNORECASE,
)

_SUBJECT_COMPANY_PATS = [
    re.compile(r"applying to\s+(.+?)(?:[!.]|\s*$)", re.IGNORECASE),
    re.compile(r"application to\s+(.+?)(?:[!.]|\s*$)", re.IGNORECASE),
    re.compile(r"interest in\s+(.+?)(?:[!.]|\s*$)", re.IGNORECASE),
    re.compile(r"your application (?:with|at)\s+(.+?)(?:[!.]|\s*$)", re.IGNORECASE),
]

# Trailing filler a subject-line match can drag in past the actual company
# name (e.g. "Application to Acme successfully submitted", or a personalized
# ", <FirstName>!" greeting tacked onto the end).
_TRAILING_FILLER_PAT = re.compile(
    r"\s*(successfully submitted|has been received|was received|received)\s*$",
    re.IGNORECASE,
)
# A trailing ", <Name>" is a personalized greeting, not part of the company —
# except for genuine corporate suffixes, which must be kept.
_TRAILING_GREETING_PAT = re.compile(
    r",\s*(?!(?:Inc|LLC|Ltd|Corp|Co|Company|Group|Labs|Technologies|Holdings)\b)[A-Z][a-z]+$"
)

# Standalone ATS platform names — never valid as the employer itself, only
# ever seen here as a fallback sender name on a generic, company-less subject.
_ATS_PLATFORM_NAMES = {
    "workday", "greenhouse", "lever", "ashby", "icims", "smartrecruiters",
    "taleo", "workable", "bamboohr", "jobvite", "successfactors",
}


def _clean_company_candidate(candidate: str) -> str | None:
    cleaned = candidate.strip().strip("\"'")
    cleaned = _TRAILING_FILLER_PAT.sub("", cleaned).strip()
    cleaned = _TRAILING_GREETING_PAT.sub("", cleaned).strip()
    cleaned = _NAME_SUFFIX_PAT.sub("", cleaned).strip()
    if not cleaned or len(cleaned) > 80:
        return None
    if _normalize_company_key(cleaned) in _ATS_PLATFORM_NAMES:
        return None
    return cleaned


def _extract_company(subject: str, from_name: str) -> str | None:
    for pat in _SUBJECT_COMPANY_PATS:
        m = pat.search(subject or "")
        if m:
            cleaned = _clean_company_candidate(m.group(1))
            if cleaned:
                return cleaned
    cleaned = _clean_company_candidate(from_name or "")
    return cleaned


def _normalize_company_key(name: str) -> str:
    return re.sub(r"[^a-z0-9]", "", name.lower())


def _existing_autopilot_companies(db: Session) -> set[str]:
    """Companies already tracked via Autopilot — skip these to avoid double-counting
    a submission CareerOS itself made, which sends the same kind of confirmation email."""
    companies = set()
    for job in list_entities(db, "aa_autopilot_job"):
        company = job.get("company") or job.get("companyName")
        if company:
            companies.add(_normalize_company_key(str(company)))
    return companies


def sync_gmail_applications(db: Session, limit: int = 100) -> dict[str, Any]:
    """Scan Gmail for application-confirmation emails and track genuinely new ones.

    Idempotent: each tracked application is keyed by its Gmail UID, so re-running
    this only adds emails it hasn't seen before.
    """
    if not settings.gmail_user or not settings.gmail_app_password:
        return {"success": False, "reason": "Gmail isn't configured (GMAIL_USER / GMAIL_APP_PASSWORD)", "added": 0, "skipped": 0}

    client = GmailImapClient(settings.gmail_user, settings.gmail_app_password)

    try:
        gmail_client = client._connect()  # noqa: SLF001 — reusing the shared connect/mailbox helpers below
    except Exception as exc:
        return {"success": False, "reason": f"IMAP login failed: {exc}", "added": 0, "skipped": 0}

    try:
        client._open_mailbox(gmail_client)  # noqa: SLF001
        uid_set: set[str] = set()
        for term in APPLIED_SUBJECT_TERMS:
            try:
                status, data = gmail_client.uid("search", None, f'(SUBJECT "{term}")')
                if status == "OK" and data and data[0]:
                    uid_set.update(data[0].decode().split())
            except Exception:
                continue
        uids = sorted(uid_set, key=int)[-limit:][::-1]
    finally:
        try:
            gmail_client.logout()
        except Exception:
            pass

    if not uids:
        return {"success": True, "added": 0, "skipped": 0, "checked": 0}

    threads = client._fetch_uids(uids, include_body=False)  # noqa: SLF001 — headers are enough; body isn't needed for company/role extraction

    already_tracked = {a.get("id") for a in list_entities(db, ENTITY_TYPE)}
    autopilot_companies = _existing_autopilot_companies(db)

    added = 0
    skipped = 0
    for thread in threads:
        uid = thread.get("uid")
        entity_id = f"gmail_{uid}"
        if entity_id in already_tracked:
            continue

        company = _extract_company(thread.get("subject", ""), thread.get("fromName", ""))
        if not company:
            skipped += 1
            continue

        if _normalize_company_key(company) in autopilot_companies:
            # Already tracked as an Autopilot submission — this is that
            # submission's own confirmation email, not a separate manual one.
            skipped += 1
            continue

        submitted_at = thread.get("date") or now_iso()
        upsert_entity(
            db,
            ENTITY_TYPE,
            {
                "id": entity_id,
                "companyName": company,
                "roleTitle": "Unknown role",
                "status": "submitted",
                "source": SOURCE_TAG,
                "submittedAt": submitted_at,
                "createdAt": submitted_at,
                "updatedAt": now_iso(),
                "notes": thread.get("subject", ""),
            },
        )
        added += 1

    return {"success": True, "added": added, "skipped": skipped, "checked": len(threads)}
