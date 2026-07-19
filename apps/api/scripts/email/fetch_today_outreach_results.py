#!/usr/bin/env python3
"""Fetch today's recruiter outreach sends from Gmail Sent and cross-reference bounces."""

from __future__ import annotations

import email
import imaplib
import json
import re
import sys
from datetime import date, datetime, timezone
from email.header import decode_header
from email.utils import getaddresses, parsedate_to_datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from app.config import settings  # noqa: E402

from fetch_bounced_emails import (  # noqa: E402
    BOUNCE_FROM_PATTERNS,
    BOUNCE_SUBJECT_PATTERNS,
    extract_failed_addresses,
    looks_like_bounce,
    message_body,
)

DEFAULT_OUTPUT = ROOT / "data" / "today_outreach_results.json"
OUTREACH_SUBJECT_PREFIX = "Senior Software Engineer at Microsoft | Interested in Opportunities"
SENT_MAILBOXES = ('"[Gmail]/Sent Mail"', '"[Gmail]/All Mail"', "INBOX")
BOUNCE_MAILBOXES = ('"[Gmail]/All Mail"', "INBOX")


def decode_header_value(value: str | None) -> str:
    if not value:
        return ""
    parts: list[str] = []
    for chunk, encoding in decode_header(value):
        if isinstance(chunk, bytes):
            parts.append(chunk.decode(encoding or "utf-8", errors="replace"))
        else:
            parts.append(str(chunk))
    return "".join(parts)


def parse_message_date(raw: str | None) -> datetime | None:
    if not raw:
        return None
    try:
        dt = parsedate_to_datetime(raw)
    except (TypeError, ValueError, OverflowError):
        return None
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt


def is_same_local_day(dt: datetime | None, target: date) -> bool:
    if dt is None:
        return False
    local = dt.astimezone()
    return local.date() == target


def imap_date(value: date) -> str:
    return value.strftime("%d-%b-%Y")


def select_mailbox(client: imaplib.IMAP4_SSL, names: tuple[str, ...]) -> str:
    for mailbox in names:
        status, _ = client._simple_command("SELECT", mailbox)
        if status == "OK":
            client.state = "SELECTED"
            return mailbox
    raise RuntimeError(f"Unable to open mailbox: {names}")


def search_uids(client: imaplib.IMAP4_SSL, query: str) -> list[str]:
    status, data = client.uid("search", None, query)
    if status != "OK" or not data or not data[0]:
        return []
    return sorted(data[0].decode().split(), key=int, reverse=True)


def extract_recipients(msg: email.message.Message) -> list[str]:
    recipients: list[str] = []
    for header in ("To", "Cc", "Bcc"):
        for _, address in getaddresses([msg.get(header, "")]):
            lowered = address.strip().lower()
            if lowered and "@" in lowered:
                recipients.append(lowered)
    return recipients


def fetch_sent_outreach(client: imaplib.IMAP4_SSL, target_day: date) -> list[dict]:
    select_mailbox(client, SENT_MAILBOXES)
    since = imap_date(target_day)
    before = imap_date(date.fromordinal(target_day.toordinal() + 1))
    query = f'(SINCE {since} BEFORE {before} SUBJECT "{OUTREACH_SUBJECT_PREFIX}")'
    uids = search_uids(client, query)
    print(f"Found {len(uids)} sent messages matching outreach subject for {target_day.isoformat()}")

    results: list[dict] = []
    for uid in uids:
        status, data = client.uid("fetch", uid, "(RFC822)")
        if status != "OK" or not data or not data[0]:
            continue
        raw = data[0][1]
        if not isinstance(raw, (bytes, bytearray)):
            continue
        msg = email.message_from_bytes(raw)
        sent_at = parse_message_date(msg.get("Date"))
        if not is_same_local_day(sent_at, target_day):
            continue
        subject = decode_header_value(msg.get("Subject"))
        if OUTREACH_SUBJECT_PREFIX not in subject:
            continue
        recipients = extract_recipients(msg)
        company_match = re.search(r"Interested in Opportunities at (.+)$", subject)
        results.append(
            {
                "uid": uid,
                "subject": subject,
                "recipients": recipients,
                "recipient": recipients[0] if recipients else None,
                "company": company_match.group(1).strip() if company_match else None,
                "sentAt": sent_at.isoformat() if sent_at else None,
                "deliveryStatus": "sent",
            }
        )
    return results


def fetch_today_bounces(client: imaplib.IMAP4_SSL, target_day: date, limit: int = 800) -> dict[str, dict]:
    select_mailbox(client, BOUNCE_MAILBOXES)
    since = imap_date(target_day)
    before = imap_date(date.fromordinal(target_day.toordinal() + 1))
    queries = [
        f'(SINCE {since} BEFORE {before} FROM "mailer-daemon@googlemail.com")',
        f'(SINCE {since} BEFORE {before} SUBJECT "Delivery Status Notification")',
        f'(SINCE {since} BEFORE {before} SUBJECT "Address not found")',
        f'(SINCE {since} BEFORE {before} SUBJECT "Mail Delivery Failed")',
    ]
    uid_set: set[str] = set()
    for query in queries:
        uid_set.update(search_uids(client, query))
    ordered = sorted(uid_set, key=int, reverse=True)[:limit]
    print(f"Scanning {len(ordered)} bounce-related messages for {target_day.isoformat()}")

    bounced: dict[str, dict] = {}
    for uid in ordered:
        status, data = client.uid("fetch", uid, "(RFC822)")
        if status != "OK" or not data or not data[0]:
            continue
        raw = data[0][1]
        if not isinstance(raw, (bytes, bytearray)):
            continue
        msg = email.message_from_bytes(raw)
        subject = decode_header_value(msg.get("Subject"))
        from_header = decode_header_value(msg.get("From"))
        if not looks_like_bounce(subject, from_header):
            continue
        bounce_at = parse_message_date(msg.get("Date"))
        if not is_same_local_day(bounce_at, target_day):
            continue
        body = message_body(msg)
        failed = extract_failed_addresses(subject, body)
        for address in failed:
            bounced.setdefault(
                address,
                {
                    "email": address,
                    "bounceAt": bounce_at.isoformat() if bounce_at else None,
                    "subject": subject,
                    "snippet": body[:240].replace("\r", " ").replace("\n", " "),
                },
            )
    return bounced


def main() -> int:
    target_day = date.fromisoformat(sys.argv[1]) if len(sys.argv) > 1 else datetime.now().date()
    output_path = Path(sys.argv[2]) if len(sys.argv) > 2 else DEFAULT_OUTPUT

    if not settings.gmail_user or not settings.gmail_app_password:
        print("Error: GMAIL_USER and GMAIL_APP_PASSWORD must be set in apps/api/.env")
        return 1

    client = imaplib.IMAP4_SSL("imap.gmail.com")
    client.login(settings.gmail_user, settings.gmail_app_password)

    sent = fetch_sent_outreach(client, target_day)
    bounced = fetch_today_bounces(client, target_day)
    client.logout()

    for item in sent:
        recipient = item.get("recipient")
        if recipient and recipient in bounced:
            item["deliveryStatus"] = "bounced"
            item["bounce"] = bounced[recipient]
        else:
            item["deliveryStatus"] = "delivered"

    delivered = sum(1 for item in sent if item["deliveryStatus"] == "delivered")
    bounced_count = sum(1 for item in sent if item["deliveryStatus"] == "bounced")

    payload = {
        "generatedAt": datetime.now(timezone.utc).isoformat(),
        "date": target_day.isoformat(),
        "gmailUser": settings.gmail_user,
        "summary": {
            "sent": len(sent),
            "delivered": delivered,
            "bounced": bounced_count,
            "bounceRatePct": round((bounced_count / len(sent) * 100), 1) if sent else 0.0,
        },
        "messages": sent,
        "bouncedNotInSentList": sorted(
            [addr for addr in bounced if addr not in {item.get("recipient") for item in sent}],
        ),
    }

    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")

    print(f"\nSaved report to {output_path}")
    print(f"Sent today: {payload['summary']['sent']}")
    print(f"Delivered:  {payload['summary']['delivered']}")
    print(f"Bounced:    {payload['summary']['bounced']} ({payload['summary']['bounceRatePct']}%)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
