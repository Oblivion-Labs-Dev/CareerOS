"""FastAPI routes for the notifications service — Gmail I/O and the application
tracker's Gmail sync.

Routes moved out of routers/api.py (Step 4). Paths and behaviour are unchanged;
main.py includes this router alongside the legacy ones. The cached-JSON reads
resolve against apps/api/data, the unchanged data location (this module sits at
the repo root, so the path is built from there rather than relative to a
routers/ file).
"""

import json
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from sqlalchemy.orm import Session

from app.config import settings
from notifications.gmail.imap import GmailImapClient
from notifications.gmail.sender import SendEmailPayload, build_gmail_sender
from notifications.outreach import load_campaigns
from notifications.tracker import inbox as tracker_inbox
from shared.auth_guards import require_gmail_configured, require_protected_action_auth
from shared.deps import db_session

router = APIRouter()

# apps/api/data, resolved from the repo root (unchanged by the refactor).
_DATA_DIR = Path(__file__).resolve().parents[1] / "apps" / "api" / "data"


# ── Outreach-campaign delivery stats (cached JSON) ─────────────────────────────

def _load_bounced_email_details() -> tuple[dict[str, dict[str, Any]], int, dict[str, int]]:
    path = _DATA_DIR / "bounced_recruiter_emails.json"
    if not path.exists():
        return {}, 0, {}
    payload = json.loads(path.read_text(encoding="utf-8"))
    details: dict[str, dict[str, Any]] = {}
    for item in payload.get("invalidEmails", []):
        email = str(item.get("email", "")).lower()
        if not email:
            continue
        details[email] = {
            "bounceCategory": item.get("bounceCategory") or "other",
            "bounceCategoryLabel": item.get("bounceCategoryLabel") or "Other bounce",
            "bounceReason": item.get("bounceReason") or "Delivery failed",
        }
    category_counts = {
        str(key): int(value)
        for key, value in (payload.get("categoryCounts") or {}).items()
        if key
    }
    return details, int(payload.get("bounceMessages", 0) or 0), category_counts


def _load_bounced_email_set() -> tuple[set[str], int]:
    details, bounce_messages, _ = _load_bounced_email_details()
    return set(details), bounce_messages


def _compute_delivery_stats(
    results: list[dict[str, Any]],
    bounce_details: dict[str, dict[str, Any]],
) -> dict[str, Any]:
    sent = [result for result in results if result.get("status") == "sent"]
    failed = [result for result in results if result.get("status") == "failed"]
    bounced_sent = [result for result in sent if str(result.get("email", "")).lower() in bounce_details]
    category_counts: dict[str, int] = {}
    for result in bounced_sent:
        email = str(result.get("email", "")).lower()
        category = bounce_details.get(email, {}).get("bounceCategory") or "other"
        category_counts[category] = category_counts.get(category, 0) + 1
    return {
        "delivered": len(sent) - len(bounced_sent),
        "bounced": len(bounced_sent),
        "undelivered": len(bounced_sent) + len(failed),
        "invalid": category_counts.get("invalid_address", 0),
        "notDelivered": category_counts.get("not_delivered", 0),
        "mailboxFull": category_counts.get("mailbox_full", 0),
        "mailboxUnavailable": category_counts.get("mailbox_unavailable", 0),
        "messageBlocked": category_counts.get("message_blocked", 0),
        "temporaryFailure": category_counts.get("temporary_failure", 0),
        "otherBounce": category_counts.get("other", 0),
        "bounceCategories": category_counts,
        "sendFailed": len(failed),
        "pending": len([result for result in results if result.get("status") in {"pending", "retrying", "paused"}]),
    }


def _enrich_outreach_result(
    result: dict[str, Any],
    bounce_details: dict[str, dict[str, Any]],
) -> dict[str, Any]:
    enriched = dict(result)
    email = str(enriched.get("email", "")).lower()
    status = enriched.get("status")
    detail = bounce_details.get(email)
    if status == "sent" and detail:
        category = detail.get("bounceCategory") or "other"
        enriched["deliveryStatus"] = category if category != "other" else "bounced"
        enriched["bounceCategory"] = category
        enriched["bounceCategoryLabel"] = detail.get("bounceCategoryLabel") or "Bounced"
        enriched["bounceReason"] = detail.get("bounceReason") or "Delivery failed"
        enriched["error"] = detail.get("bounceReason") or enriched.get("error")
    elif status == "sent":
        enriched["deliveryStatus"] = "delivered"
        enriched["bounceCategory"] = "delivered"
        enriched["bounceCategoryLabel"] = "Delivered"
    elif status == "failed":
        enriched["deliveryStatus"] = "failed"
        enriched["bounceCategory"] = "send_failed"
        enriched["bounceCategoryLabel"] = "Send failed"
        # keep original SMTP error under error
    else:
        enriched["deliveryStatus"] = "pending"
        enriched["bounceCategory"] = "pending"
        enriched["bounceCategoryLabel"] = "Pending"
    return enriched


def _prepare_outreach_campaign(
    campaign: dict[str, Any],
    bounce_details: dict[str, dict[str, Any]],
    bounce_messages: int,
    recent_limit: int,
) -> dict[str, Any]:
    prepared = dict(campaign)
    results = list(prepared.get("results") or [])
    prepared["deliveryStats"] = {
        **_compute_delivery_stats(results, bounce_details),
        "bounceMessages": bounce_messages,
    }
    recent = sorted(
        results,
        key=lambda result: str(result.get("sentAt") or ""),
        reverse=True,
    )[:recent_limit]
    prepared["results"] = [_enrich_outreach_result(result, bounce_details) for result in recent]
    prepared["recentLimit"] = recent_limit
    prepared["resultsTotal"] = len(results)
    return prepared


# ── Application tracker (pipeline / summary) ───────────────────────────────────
#
# Moved verbatim out of routers/api.py; these live in the tracker subservice.
# Paths and behaviour are unchanged.

@router.get("/tracker/summary")
def get_tracker_summary(db: Session = Depends(db_session)) -> dict[str, Any]:
    from app.db.store import tracker_summary
    from notifications.tracker.outcomes import dashboard_outcomes

    return {**tracker_summary(db), "outcomes": dashboard_outcomes(db)}


@router.get("/tracker/pipeline")
def get_tracker_pipeline(db: Session = Depends(db_session)) -> dict[str, Any]:
    """Kanban view of the post-apply funnel: Applied -> Ghosted -> Interviewing -> Rejected -> Offer."""
    from notifications.tracker import pipeline as tracker_pipeline

    return tracker_pipeline.build_pipeline(db)


# ── Gmail / recruiter email ────────────────────────────────────────────────────

@router.post("/tracker/sync-gmail")
def sync_gmail_tracker(db: Session = Depends(db_session)) -> dict[str, Any]:
    """Scan Gmail for application-confirmation emails from jobs applied to
    outside CareerOS, and track genuinely new ones alongside Autopilot's own."""
    from notifications.tracker.gmail_applications import sync_gmail_applications

    return sync_gmail_applications(db)


@router.get("/email/verify")
def verify_gmail_connection() -> dict[str, Any]:
    if not settings.gmail_user or not settings.gmail_app_password:
        return {
            "success": False,
            "configured": False,
            "user": None,
            "message": "Gmail is not configured. Set GMAIL_USER and GMAIL_APP_PASSWORD in apps/api/.env",
        }
    sender = build_gmail_sender(settings.gmail_user, settings.gmail_app_password)
    return {
        "success": sender.verify_connection(),
        "configured": True,
        "user": settings.gmail_user,
    }


@router.post("/email/send")
def send_email(payload: SendEmailPayload, request: Request) -> dict[str, Any]:
    require_protected_action_auth(request)
    user, app_password = require_gmail_configured()
    sender = build_gmail_sender(user, app_password)
    try:
        result = sender.send(payload)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc
    return {"success": True, **result}


@router.get("/email/recruiter-threads")
def list_recruiter_threads(limit: int = Query(default=10, ge=1, le=150)) -> dict[str, Any]:
    user, app_password = require_gmail_configured()
    client = GmailImapClient(user, app_password)
    threads = client.fetch_threads(limit=limit)
    return {"success": True, "threads": threads, "count": len(threads)}


@router.get("/email/recruiter-threads/classified")
async def list_classified_recruiter_threads(
    limit: int = Query(default=20, ge=1, le=100), db: Session = Depends(db_session)
) -> dict[str, Any]:
    """Inbox view: recruiter threads auto-tagged Verification/Rejection/Interview/Assessment/
    Reminder/Offer/Applied (rule-based, cached per IMAP UID; LLM fallback only when ambiguous
    and OPENROUTER_API_KEY is set)."""
    user, app_password = require_gmail_configured()
    client = GmailImapClient(user, app_password)
    threads = await tracker_inbox.fetch_and_classify_threads(db, client, limit=limit)
    counts: dict[str, int] = {}
    for thread in threads:
        category = thread.get("category") or "uncategorized"
        counts[category] = counts.get(category, 0) + 1
    return {"success": True, "threads": threads, "count": len(threads), "categoryCounts": counts}


@router.get("/email/recruiter-conversations")
def get_cached_recruiter_conversations() -> dict[str, Any]:
    path = _DATA_DIR / "recruiter_conversations.json"
    if not path.exists():
        return {"success": True, "conversations": [], "count": 0, "source": "cache-missing"}
    conversations = json.loads(path.read_text(encoding="utf-8"))
    return {"success": True, "conversations": conversations, "count": len(conversations), "source": str(path)}


@router.get("/email/outreach-campaigns")
def get_recruiter_outreach_campaigns(
    limit: int = Query(default=20, ge=1, le=100),
    recent_limit: int = Query(default=10, ge=1, le=100),
) -> dict[str, Any]:
    path = _DATA_DIR / "recruiter_outreach_campaigns.json"
    if not path.exists():
        return {"success": True, "campaigns": [], "count": 0, "source": "cache-missing"}
    loaded = load_campaigns(path)
    raw_campaigns = loaded.campaigns
    bounce_details, bounce_messages, _ = _load_bounced_email_details()
    full_campaigns = raw_campaigns[:limit]
    campaigns = [
        _prepare_outreach_campaign(campaign, bounce_details, bounce_messages, recent_limit)
        for campaign in full_campaigns
    ]
    all_full_results = [result for campaign in full_campaigns for result in (campaign.get("results") or [])]
    aggregate_stats = {
        **_compute_delivery_stats(all_full_results, bounce_details),
        "bounceMessages": bounce_messages,
    }
    return {
        "success": True,
        "campaigns": campaigns,
        "count": len(campaigns),
        "aggregateDeliveryStats": aggregate_stats,
        "source": str(path),
        "recovered": loaded.recovered,
        "warning": loaded.warning,
        "discardedIncompleteItems": loaded.discarded_incomplete_items,
    }
