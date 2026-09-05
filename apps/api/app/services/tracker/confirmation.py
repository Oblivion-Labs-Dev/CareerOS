"""Verify a submission actually landed, by checking for a real confirmation
email at the application's tracking address — not just that the browser
automation reported success.

This is the success criterion the product should hold itself to: a form
submit that returns "ok" but never gets a real ATS confirmation email isn't
actually a successful application.
"""

from __future__ import annotations

from typing import Any

from sqlalchemy.orm import Session

from app.config import settings
from app.db.store import now_iso
from app.services.application_assistant.persistence import get_application_draft, update_application_draft
from app.services.gmail_imap import GmailImapClient


def check_submission_confirmed(db: Session, application_id: str) -> dict[str, Any]:
    """Look for a real inbox message at this application's tracking address.

    Returns {checked, confirmed, trackingEmail, matches: [...], reason}.
    `reason` explains a `checked: False` result (no tracking email on this
    draft, or Gmail isn't configured) so callers can tell "not confirmed yet"
    apart from "can't check."
    """
    draft = get_application_draft(db, application_id)
    if not draft:
        return {"checked": False, "confirmed": False, "reason": "Application not found"}

    tracking_email = draft.get("trackingEmail")
    if not tracking_email:
        return {"checked": False, "confirmed": False, "reason": "This application has no tracking email (predates the feature, or Gmail isn't configured)"}

    if not settings.gmail_user or not settings.gmail_app_password:
        return {"checked": False, "confirmed": False, "trackingEmail": tracking_email, "reason": "Gmail isn't configured (GMAIL_USER / GMAIL_APP_PASSWORD)"}

    client = GmailImapClient(settings.gmail_user, settings.gmail_app_password)
    try:
        messages = client.fetch_by_recipient(tracking_email, limit=10, include_body=True)
    except Exception as exc:
        return {"checked": False, "confirmed": False, "trackingEmail": tracking_email, "reason": f"IMAP lookup failed: {exc}"}

    matches = [
        {
            "fromName": m.get("fromName"),
            "fromAddress": m.get("fromAddress"),
            "subject": m.get("subject"),
            "date": m.get("date"),
            "snippet": (m.get("snippet") or "")[:200],
        }
        for m in messages
    ]
    result = {
        "checked": True,
        "confirmed": bool(matches),
        "trackingEmail": tracking_email,
        "matches": matches,
        "reason": "" if matches else "No message has arrived at the tracking address yet",
    }

    # Persist a positive result onto the draft so it doesn't need re-checking
    # on every read; never persist a negative one, since "not found yet" can
    # always still arrive later — the absence of confirmation is not itself a
    # fact worth freezing in place.
    if matches:
        try:
            update_application_draft(db, application_id, {
                "emailConfirmation": {
                    "confirmed": True,
                    "matchedThreadSubject": matches[0].get("subject"),
                    "matchedThreadFrom": matches[0].get("fromAddress"),
                    "checkedAt": now_iso(),
                },
            })
        except Exception:
            pass  # Persistence is a convenience cache; the live check result above is still returned either way.

    return result
