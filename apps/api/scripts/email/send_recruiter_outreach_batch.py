#!/usr/bin/env python3
"""Send personalized recruiter outreach emails and persist campaign results."""

from __future__ import annotations

import argparse
import json
import random
import sys
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from app.config import settings  # noqa: E402
from app.services.gmail_sender import EmailAttachment, SendEmailPayload, build_gmail_sender  # noqa: E402

DEFAULT_EMAILS = Path(__file__).resolve().parent / "personalized_recruiter_emails.json"
DEFAULT_RESUME_PDF = Path(r"D:\Docs\Interview\Resume\Akshay_Borse_Resume.pdf")
DEFAULT_RESULTS = ROOT / "data" / "recruiter_outreach_campaigns.json"
DEFAULT_DELAY_SECONDS = 8.0
MIN_DELAY_SECONDS = 2.0
MAX_JITTER_SECONDS = 2.0
DEFAULT_RETRY_ATTEMPTS = 3
RETRY_BASE_DELAY_SECONDS = 15.0
PAUSE_ON_FAILURE_DELAY_SECONDS = 30.0

RESUMABLE_STATUSES = {"in_progress", "paused"}


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def load_campaigns(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    return json.loads(path.read_text(encoding="utf-8"))


def save_campaigns(path: Path, campaigns: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(campaigns, indent=2), encoding="utf-8")


def upsert_campaign(campaigns: list[dict[str, Any]], campaign: dict[str, Any]) -> list[dict[str, Any]]:
    for index, existing in enumerate(campaigns):
        if existing.get("id") == campaign.get("id"):
            campaigns[index] = campaign
            return campaigns
    campaigns.insert(0, campaign)
    return campaigns


def recalculate_summary(campaign: dict[str, Any]) -> None:
    results = campaign.get("results", [])
    sent = sum(1 for result in results if result.get("status") == "sent")
    failed = sum(1 for result in results if result.get("status") == "failed")
    pending = sum(1 for result in results if result.get("status") in {"pending", "retrying"})
    skipped = sum(1 for result in results if result.get("status") == "skipped")
    campaign["summary"] = {
        "total": len(results),
        "sent": sent,
        "failed": failed,
        "pending": pending,
        "skipped": skipped,
    }


def persist_campaign(results_path: Path, campaign: dict[str, Any]) -> None:
    campaigns = load_campaigns(results_path)
    recalculate_summary(campaign)
    campaigns = upsert_campaign(campaigns, campaign)
    save_campaigns(results_path, campaigns)


def pick_recipients(entries: list[dict[str, Any]], limit: int, one_per_company: bool) -> list[dict[str, Any]]:
    selected: list[dict[str, Any]] = []
    seen_companies: set[str] = set()
    for entry in entries:
        company = entry["company"]
        if one_per_company:
            if company in seen_companies:
                continue
            seen_companies.add(company)
        selected.append(entry)
        if len(selected) >= limit:
            break
    return selected


def index_entries_by_email(entries: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    return {entry["email"].lower(): entry for entry in entries}


def already_sent_emails(campaigns: list[dict[str, Any]]) -> set[str]:
    sent: set[str] = set()
    for campaign in campaigns:
        for result in campaign.get("results", []):
            if result.get("status") == "sent" and result.get("email"):
                sent.add(str(result["email"]).lower())
    return sent


def unique_entries_by_email(entries: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Keep the first occurrence of each email address (case-insensitive)."""
    selected: list[dict[str, Any]] = []
    seen: set[str] = set()
    for entry in entries:
        email = str(entry.get("email", "")).strip().lower()
        if not email or email in seen:
            continue
        seen.add(email)
        selected.append(entry)
    return selected


def mark_skipped(result: dict[str, Any], reason: str) -> None:
    result["status"] = "skipped"
    result["error"] = reason
    result["sentAt"] = None


def find_resumable_campaign(campaigns: list[dict[str, Any]], campaign_id: str | None) -> dict[str, Any] | None:
    if campaign_id:
        return next((campaign for campaign in campaigns if campaign.get("id") == campaign_id), None)
    for campaign in campaigns:
        if campaign.get("status") in RESUMABLE_STATUSES:
            return campaign
    return None


def build_result(recipient: dict[str, Any], status: str = "pending") -> dict[str, Any]:
    return {
        "id": str(uuid.uuid4()),
        "company": recipient["company"],
        "recruiterName": recipient["recruiterName"],
        "firstName": recipient.get("firstName", ""),
        "email": recipient["email"],
        "subject": recipient["subject"],
        "status": status,
        "messageId": None,
        "sentAt": None,
        "error": None,
        "attempts": 0,
    }


def create_campaign(
    recipients: list[dict[str, Any]],
    *,
    dry_run: bool,
    delay: float,
    jitter: float,
    no_throttle: bool,
    label: str | None = None,
) -> dict[str, Any]:
    campaign = {
        "id": str(uuid.uuid4()),
        "label": label or f"Outreach batch ({len(recipients)} recruiters)",
        "startedAt": utc_now(),
        "completedAt": None,
        "status": "in_progress",
        "dryRun": dry_run,
        "throttle": {
            "enabled": not no_throttle and not dry_run,
            "delaySeconds": delay,
            "jitterSeconds": jitter,
            "minDelaySeconds": MIN_DELAY_SECONDS,
        },
        "summary": {"total": len(recipients), "sent": 0, "failed": 0, "pending": len(recipients)},
        "results": [build_result(recipient) for recipient in recipients],
    }
    return campaign


def recipients_for_new_campaign(
    entries: list[dict[str, Any]],
    campaigns: list[dict[str, Any]],
    *,
    limit: int,
    one_per_company: bool,
    skip_already_sent: bool,
) -> list[dict[str, Any]]:
    pool = unique_entries_by_email(entries)
    if skip_already_sent:
        sent_emails = already_sent_emails(campaigns)
        pool = [entry for entry in pool if entry["email"].lower() not in sent_emails]
    if one_per_company:
        return pick_recipients(pool, limit, True)
    if limit > 0:
        return pool[:limit]
    return pool


def pending_recipients_from_campaign(
    campaign: dict[str, Any],
    entries_by_email: dict[str, dict[str, Any]],
    *,
    retry_failed: bool,
    already_sent: set[str] | None = None,
) -> list[tuple[dict[str, Any], dict[str, Any]]]:
    """Return pending work items, keeping only unique emails not already sent."""
    pending: list[tuple[dict[str, Any], dict[str, Any]]] = []
    seen_emails: set[str] = set(already_sent or set())
    for result in campaign.get("results", []):
        status = result.get("status")
        if status in {"sent", "skipped", "dry_run"}:
            continue
        if status == "failed" and not retry_failed:
            continue
        email = str(result.get("email", "")).strip().lower()
        if not email:
            mark_skipped(result, "Missing email address.")
            continue
        if email in seen_emails:
            mark_skipped(result, "Skipped duplicate email — already sent or queued once.")
            continue
        recipient = entries_by_email.get(email)
        if not recipient:
            result["status"] = "failed"
            result["error"] = "Recipient not found in personalized email list."
            continue
        if status in {"pending", "failed", "retrying"}:
            seen_emails.add(email)
            pending.append((result, recipient))
    return pending


def throttle_between_sends(delay_seconds: float, jitter_seconds: float) -> None:
    wait_seconds = max(MIN_DELAY_SECONDS, delay_seconds) + random.uniform(0, max(0.0, jitter_seconds))
    print(f"  Sleeping {wait_seconds:.1f}s before next send (Gmail throttle guard)...")
    time.sleep(wait_seconds)


def is_rate_limit_error(message: str) -> bool:
    lowered = message.lower()
    return any(
        token in lowered
        for token in (
            "rate",
            "limit",
            "too many",
            "421",
            "450",
            "452",
            "454",
            "throttl",
        )
    )


def send_with_retry(
    sender: Any,
    payload: SendEmailPayload,
    *,
    max_attempts: int,
    base_delay: float,
) -> dict[str, str]:
    last_error: Exception | None = None
    for attempt in range(1, max_attempts + 1):
        try:
            return sender.send(payload)
        except Exception as exc:  # noqa: BLE001
            last_error = exc
            if attempt >= max_attempts:
                break
            wait_seconds = base_delay * attempt
            if is_rate_limit_error(str(exc)):
                wait_seconds = max(wait_seconds, PAUSE_ON_FAILURE_DELAY_SECONDS * attempt)
            print(f"  Attempt {attempt}/{max_attempts} failed: {exc}")
            print(f"  Retrying in {wait_seconds:.0f}s...")
            time.sleep(wait_seconds)
    assert last_error is not None
    raise last_error


def finalize_campaign(campaign: dict[str, Any]) -> None:
    recalculate_summary(campaign)
    summary = campaign["summary"]
    if summary["pending"] > 0:
        campaign["status"] = "paused"
        campaign["completedAt"] = None
    elif summary["failed"] > 0:
        campaign["status"] = "completed_with_errors"
        campaign["completedAt"] = utc_now()
    else:
        campaign["status"] = "completed"
        campaign["completedAt"] = utc_now()


def main() -> int:
    parser = argparse.ArgumentParser(description="Send recruiter outreach batch and save results")
    parser.add_argument("--limit", type=int, default=5, help="Number of recruiters to email")
    parser.add_argument("--emails", type=Path, default=DEFAULT_EMAILS, help="Personalized emails JSON")
    parser.add_argument("--results", type=Path, default=DEFAULT_RESULTS, help="Campaign results JSON")
    parser.add_argument("--resume-pdf", type=Path, default=DEFAULT_RESUME_PDF, help="Resume PDF path")
    parser.add_argument(
        "--delay",
        type=float,
        default=DEFAULT_DELAY_SECONDS,
        help=f"Base seconds to wait between sends (default: {DEFAULT_DELAY_SECONDS})",
    )
    parser.add_argument(
        "--jitter",
        type=float,
        default=MAX_JITTER_SECONDS,
        help=f"Random extra seconds added to each wait (default: {MAX_JITTER_SECONDS})",
    )
    parser.add_argument(
        "--retries",
        type=int,
        default=DEFAULT_RETRY_ATTEMPTS,
        help=f"Retry attempts per recruiter before pausing (default: {DEFAULT_RETRY_ATTEMPTS})",
    )
    parser.add_argument(
        "--no-throttle",
        action="store_true",
        help="Send immediately with no delay between messages (not recommended)",
    )
    parser.add_argument(
        "--one-per-company",
        action="store_true",
        default=True,
        help="Pick at most one recruiter per company (default: true)",
    )
    parser.add_argument(
        "--allow-same-company",
        action="store_true",
        help="Allow multiple recruiters from the same company",
    )
    parser.add_argument(
        "--skip-already-sent",
        action="store_true",
        default=True,
        help="Skip recruiters already marked sent in previous campaigns (default: true)",
    )
    parser.add_argument(
        "--allow-already-sent",
        action="store_true",
        help="Allow re-sending to emails already marked sent in previous campaigns",
    )
    parser.add_argument(
        "--continue",
        dest="continue_campaign",
        action="store_true",
        help="Resume the latest paused/in-progress campaign",
    )
    parser.add_argument(
        "--campaign-id",
        help="Resume a specific campaign id",
    )
    parser.add_argument(
        "--retry-failed",
        action="store_true",
        help="When resuming, retry recruiters that previously failed",
    )
    parser.add_argument("--dry-run", action="store_true", help="Prepare campaign without sending")
    parser.add_argument("--label", help="Custom campaign label for the dashboard")
    args = parser.parse_args()

    one_per_company = not args.allow_same_company and args.one_per_company
    skip_already_sent = args.skip_already_sent and not args.allow_already_sent

    if not args.emails.exists():
        print(f"Missing personalized emails file: {args.emails}")
        return 1

    if not settings.gmail_user or not settings.gmail_app_password:
        print("Error: GMAIL_USER and GMAIL_APP_PASSWORD must be set in apps/api/.env")
        return 1

    entries = json.loads(args.emails.read_text(encoding="utf-8"))
    entries_by_email = index_entries_by_email(entries)
    campaigns = load_campaigns(args.results)
    sent_emails = already_sent_emails(campaigns) if skip_already_sent else set()

    campaign: dict[str, Any] | None = None
    work_items: list[tuple[dict[str, Any], dict[str, Any]]] = []

    if args.continue_campaign or args.campaign_id:
        campaign = find_resumable_campaign(campaigns, args.campaign_id)
        if not campaign:
            print("No resumable campaign found. Start a new batch or pass --campaign-id.")
            return 1
        work_items = pending_recipients_from_campaign(
            campaign,
            entries_by_email,
            retry_failed=args.retry_failed or True,
            already_sent=sent_emails,
        )
        if not work_items:
            finalize_campaign(campaign)
            persist_campaign(args.results, campaign)
            print(f"Campaign {campaign['id']} has no pending recruiters.")
            return 0
        campaign["status"] = "in_progress"
        persist_campaign(args.results, campaign)
        print(
            f"Resuming campaign {campaign['id']} "
            f"({len(work_items)} unique remaining; {len(sent_emails)} already-sent emails excluded)."
        )
    else:
        recipients = recipients_for_new_campaign(
            entries,
            campaigns,
            limit=args.limit,
            one_per_company=one_per_company,
            skip_already_sent=skip_already_sent,
        )
        if not recipients:
            print("No recipients selected.")
            return 1
        campaign = create_campaign(
            recipients,
            dry_run=args.dry_run,
            delay=args.delay,
            jitter=args.jitter,
            no_throttle=args.no_throttle,
            label=args.label,
        )
        work_items = [(result, recipient) for result, recipient in zip(campaign["results"], recipients, strict=True)]
        persist_campaign(args.results, campaign)
        print(f"Created campaign {campaign['id']} with {len(work_items)} unique recruiters.")

    sender = None
    attachments = None
    if not args.dry_run:
        if not args.resume_pdf.exists():
            print(f"Warning: Resume not found at {args.resume_pdf}; sending without attachment.")
        else:
            attachments = [
                EmailAttachment(
                    filename=args.resume_pdf.name,
                    path=str(args.resume_pdf),
                )
            ]
        sender = build_gmail_sender(settings.gmail_user, settings.gmail_app_password)
        print(f"Verifying Gmail SMTP for {settings.gmail_user}...")
        if not sender.verify_connection():
            print("Error: SMTP verification failed.")
            return 1
        if args.no_throttle:
            print("Warning: throttling disabled; Gmail may rate-limit large batches.")
        else:
            print(
                f"Throttle enabled: waiting ~{max(MIN_DELAY_SECONDS, args.delay)}-"
                f"{max(MIN_DELAY_SECONDS, args.delay) + max(0.0, args.jitter):.1f}s between sends."
            )

    total = len(work_items)
    paused = False
    session_sent: set[str] = set(sent_emails)

    for index, (result, recipient) in enumerate(work_items, start=1):
        email = str(recipient["email"]).strip().lower()
        print(
            f"\n[{index}/{total}] {recipient['recruiterName']} <{recipient['email']}> ({recipient['company']})"
        )

        if email in session_sent:
            mark_skipped(result, "Skipped duplicate email — already sent.")
            persist_campaign(args.results, campaign)
            print("  Skipped duplicate (already sent).")
            continue

        if args.dry_run:
            result["status"] = "dry_run"
            result["sentAt"] = utc_now()
            persist_campaign(args.results, campaign)
            continue

        result["status"] = "retrying"
        result["error"] = None
        persist_campaign(args.results, campaign)

        try:
            payload = SendEmailPayload(
                to=recipient["email"],
                subject=recipient["subject"],
                text=recipient["body"],
                attachments=attachments,
            )
            send_result = send_with_retry(
                sender,
                payload,
                max_attempts=max(1, args.retries),
                base_delay=RETRY_BASE_DELAY_SECONDS,
            )
            result["status"] = "sent"
            result["messageId"] = send_result.get("messageId") or None
            result["sentAt"] = utc_now()
            result["attempts"] = result.get("attempts", 0) + 1
            session_sent.add(email)
            print(f"  Sent. messageId={result['messageId']}")
        except Exception as exc:  # noqa: BLE001
            result["status"] = "failed"
            result["error"] = str(exc)
            result["attempts"] = result.get("attempts", 0) + max(1, args.retries)
            persist_campaign(args.results, campaign)
            print(f"  Failed after retries: {exc}")
            print("  Campaign paused. Fix the issue, then resume with:")
            print(f"    python scripts/email/send_recruiter_outreach_batch.py --continue --campaign-id {campaign['id']}")
            paused = True
            break

        persist_campaign(args.results, campaign)

        if not args.no_throttle and index < total:
            throttle_between_sends(args.delay, args.jitter)

    if paused:
        campaign["status"] = "paused"
        campaign["completedAt"] = None
    else:
        finalize_campaign(campaign)

    persist_campaign(args.results, campaign)

    print(f"\nCampaign saved to {args.results}")
    print(
        f"Summary: {campaign['summary']['sent']} sent, "
        f"{campaign['summary']['failed']} failed, "
        f"{campaign['summary']['pending']} pending, "
        f"{campaign['summary']['total']} total"
    )

    if paused:
        return 2
    return 0 if campaign["summary"]["failed"] == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
