#!/usr/bin/env python3
"""Fetch Gmail bounce / undelivered messages and extract invalid recipient emails.

By default merges into any existing bounce report so older results are not wiped.
Optionally scan Trash and filter by date.
"""

from __future__ import annotations

import argparse
import email
import imaplib
import json
import re
import sys
from datetime import UTC, date, datetime
from email.header import decode_header
from email.utils import parsedate_to_datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from app.config import settings  # noqa: E402

DEFAULT_OUTPUT = ROOT / "data" / "bounced_recruiter_emails.json"

BOUNCE_FROM_PATTERNS = (
    "mailer-daemon",
    "postmaster",
    "mail delivery subsystem",
)

BOUNCE_SUBJECT_PATTERNS = (
    "delivery status notification",
    "undelivered",
    "delivery failure",
    "mail delivery failed",
    "returned mail",
    "failure notice",
    "address not found",
    "delivery incomplete",
    "message blocked",
    "delivery has failed",
)

EMAIL_RE = re.compile(r"[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}")
FINAL_RECIPIENT_RE = re.compile(
    r"Final-Recipient:\s*rfc822;\s*([^\s;]+)",
    re.IGNORECASE,
)
FAILED_RECIPIENT_RE = re.compile(
    r"(?:wasn't delivered to|failed to these recipients|could not be delivered to|"
    r"Delivery has failed to these recipients or groups:|"
    r"The following address(?:es)? failed:|"
    r"Your message wasn't delivered to)\s*<?([A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,})>?",
    re.IGNORECASE,
)

IGNORE_EMAILS = {
    settings.gmail_user.lower() if settings.gmail_user else "",
    "mailer-daemon@googlemail.com",
    "noreply@google.com",
}

IGNORE_DOMAIN_SUFFIXES = (
    "@mail.gmail.com",
    "@mx.google.com",
    "@googlemail.com",
)

MAILBOXES = ('"[Gmail]/All Mail"', "INBOX")
TRASH_MAILBOXES = ('"[Gmail]/Trash"', '"[Gmail]/Bin"')


def is_plausible_failed_recipient(address: str) -> bool:
    lowered = address.lower().strip()
    if not lowered or lowered in IGNORE_EMAILS:
        return False
    if any(lowered.endswith(suffix) for suffix in IGNORE_DOMAIN_SUFFIXES):
        return False
    local, _, domain = lowered.partition("@")
    if not local or not domain or "." not in domain:
        return False
    if len(local) < 3:
        return False
    return True


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


def message_body(msg: email.message.Message) -> str:
    chunks: list[str] = []
    if msg.is_multipart():
        for part in msg.walk():
            content_type = part.get_content_type()
            if content_type not in {"text/plain", "text/html", "message/delivery-status"}:
                continue
            payload = part.get_payload(decode=True)
            if not payload:
                continue
            charset = part.get_content_charset() or "utf-8"
            chunks.append(payload.decode(charset, errors="replace"))
    else:
        payload = msg.get_payload(decode=True)
        if payload:
            charset = msg.get_content_charset() or "utf-8"
            chunks.append(payload.decode(charset, errors="replace"))
    return "\n".join(chunks)


def looks_like_bounce(subject: str, from_header: str) -> bool:
    subject_lower = subject.lower()
    from_lower = from_header.lower()
    if any(token in from_lower for token in BOUNCE_FROM_PATTERNS):
        return True
    return any(token in subject_lower for token in BOUNCE_SUBJECT_PATTERNS)


def extract_failed_addresses(subject: str, body: str) -> list[str]:
    found: list[str] = []
    for match in FINAL_RECIPIENT_RE.findall(body):
        found.append(match.strip().lower())
    for match in FAILED_RECIPIENT_RE.findall(body):
        found.append(match.strip().lower())

    if not found:
        for match in EMAIL_RE.findall(body):
            lowered = match.lower()
            if is_plausible_failed_recipient(lowered):
                found.append(lowered)

    deduped: list[str] = []
    seen: set[str] = set()
    for address in found:
        if address in seen or not is_plausible_failed_recipient(address):
            continue
        seen.add(address)
        deduped.append(address)
    return deduped[:3]


def imap_date(value: date) -> str:
    return value.strftime("%d-%b-%Y")


def parse_message_date(raw: str | None) -> datetime | None:
    if not raw:
        return None
    try:
        dt = parsedate_to_datetime(raw)
    except (TypeError, ValueError, OverflowError):
        return None
    if dt.tzinfo is None:
        return dt.replace(tzinfo=UTC)
    return dt


def select_mailbox(client: imaplib.IMAP4_SSL, names: tuple[str, ...]) -> str | None:
    for mailbox in names:
        status, _ = client._simple_command("SELECT", mailbox)
        if status == "OK":
            client.state = "SELECTED"
            return mailbox
    return None


def search_bounce_uids(
    client: imaplib.IMAP4_SSL,
    *,
    limit: int,
    since: date | None = None,
    before: date | None = None,
) -> list[str]:
    date_prefix = ""
    if since:
        date_prefix += f"SINCE {imap_date(since)} "
    if before:
        date_prefix += f"BEFORE {imap_date(before)} "
    queries = [
        f'({date_prefix}FROM "mailer-daemon@googlemail.com")'.replace("  ", " "),
        f'({date_prefix}FROM "Mail Delivery Subsystem")'.replace("  ", " "),
        f'({date_prefix}SUBJECT "Delivery Status Notification")'.replace("  ", " "),
        f'({date_prefix}SUBJECT "Undelivered Mail Returned to Sender")'.replace("  ", " "),
        f'({date_prefix}SUBJECT "Mail Delivery Failed")'.replace("  ", " "),
        f'({date_prefix}SUBJECT "Address not found")'.replace("  ", " "),
        f'({date_prefix}SUBJECT "Delivery incomplete")'.replace("  ", " "),
    ]
    uid_set: set[str] = set()
    for query in queries:
        status, data = client.uid("search", None, query.strip())
        if status == "OK" and data and data[0]:
            uid_set.update(data[0].decode().split())
    ordered = sorted(uid_set, key=int, reverse=True)
    return ordered[:limit]


def collect_from_mailbox(
    client: imaplib.IMAP4_SSL,
    mailbox_names: tuple[str, ...],
    *,
    limit: int,
    since: date | None,
    before: date | None,
    source_label: str,
) -> tuple[list[dict], dict[str, dict]]:
    selected = select_mailbox(client, mailbox_names)
    if not selected:
        print(f"Skipping unavailable mailbox group: {mailbox_names}")
        return [], {}

    uids = search_bounce_uids(client, limit=limit, since=since, before=before)
    print(f"Found {len(uids)} bounce-related messages in {selected}")

    bounces: list[dict] = []
    invalid_map: dict[str, dict] = {}

    for uid in uids:
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
        bounce_dt = parse_message_date(msg.get("Date"))
        if since and bounce_dt and bounce_dt.astimezone().date() < since:
            continue
        if before and bounce_dt and bounce_dt.astimezone().date() >= before:
            continue
        body = message_body(msg)
        failed = extract_failed_addresses(subject, body)
        if not failed:
            continue
        date_value = bounce_dt.isoformat() if bounce_dt else None
        entry = {
            "uid": uid,
            "mailbox": selected,
            "source": source_label,
            "subject": subject,
            "from": from_header,
            "date": date_value,
            "failedEmails": failed,
            "snippet": body[:400].replace("\r", " ").replace("\n", " "),
        }
        bounces.append(entry)
        for address in failed:
            invalid_map.setdefault(
                address,
                {
                    "email": address,
                    "firstSeenAt": date_value,
                    "subjects": [],
                    "count": 0,
                    "sources": [],
                },
            )
            record = invalid_map[address]
            record["count"] += 1
            if date_value and (not record["firstSeenAt"] or date_value < record["firstSeenAt"]):
                record["firstSeenAt"] = date_value
            if subject not in record["subjects"]:
                record["subjects"].append(subject)
            if source_label not in record["sources"]:
                record["sources"].append(source_label)

    return bounces, invalid_map


def merge_invalid_maps(base: dict[str, dict], incoming: dict[str, dict]) -> dict[str, dict]:
    for email_addr, item in incoming.items():
        if email_addr not in base:
            base[email_addr] = item
            continue
        existing = base[email_addr]
        existing["count"] = max(existing.get("count", 0), item.get("count", 0))
        if item.get("firstSeenAt") and (
            not existing.get("firstSeenAt") or item["firstSeenAt"] < existing["firstSeenAt"]
        ):
            existing["firstSeenAt"] = item["firstSeenAt"]
        for subject in item.get("subjects", []):
            if subject not in existing.setdefault("subjects", []):
                existing["subjects"].append(subject)
        for source in item.get("sources", []):
            if source not in existing.setdefault("sources", []):
                existing["sources"].append(source)
    return base


def load_existing(path: Path) -> dict:
    if not path.exists():
        return {"invalidEmails": [], "messages": []}
    return json.loads(path.read_text(encoding="utf-8"))


def main() -> int:
    parser = argparse.ArgumentParser(description="Fetch Gmail bounce messages (merge by default)")
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--limit", type=int, default=800)
    parser.add_argument("--since", help="Only messages on/after YYYY-MM-DD")
    parser.add_argument("--before", help="Only messages before YYYY-MM-DD")
    parser.add_argument("--include-trash", action="store_true", help="Also scan Gmail Trash/Bin")
    parser.add_argument(
        "--replace",
        action="store_true",
        help="Overwrite existing bounce report instead of merging",
    )
    args = parser.parse_args()

    since = date.fromisoformat(args.since) if args.since else None
    before = date.fromisoformat(args.before) if args.before else None

    if not settings.gmail_user or not settings.gmail_app_password:
        print("Error: GMAIL_USER and GMAIL_APP_PASSWORD must be set in apps/api/.env")
        return 1

    client = imaplib.IMAP4_SSL("imap.gmail.com")
    client.login(settings.gmail_user, settings.gmail_app_password)

    bounces, invalid_map = collect_from_mailbox(
        client,
        MAILBOXES,
        limit=args.limit,
        since=since,
        before=before,
        source_label="gmail",
    )

    if args.include_trash:
        trash_bounces, trash_map = collect_from_mailbox(
            client,
            TRASH_MAILBOXES,
            limit=args.limit,
            since=since,
            before=before,
            source_label="gmail-trash",
        )
        bounces.extend(trash_bounces)
        invalid_map = merge_invalid_maps(invalid_map, trash_map)

    client.logout()

    existing = {} if args.replace else load_existing(args.output)
    existing_invalid = {
        item["email"].lower(): dict(item)
        for item in existing.get("invalidEmails", [])
        if item.get("email")
    }
    existing_messages = existing.get("messages", []) if not args.replace else []

    merged_invalid = merge_invalid_maps(existing_invalid, invalid_map)
    # Deduplicate messages by uid+mailbox when possible
    seen_msg: set[str] = set()
    merged_messages: list[dict] = []
    for msg in existing_messages + bounces:
        key = f"{msg.get('mailbox','')}:{msg.get('uid')}:{msg.get('date')}:{','.join(msg.get('failedEmails') or [])}"
        if key in seen_msg:
            continue
        seen_msg.add(key)
        merged_messages.append(msg)

    payload = {
        "generatedAt": datetime.now(UTC).isoformat(),
        "bounceMessages": len(merged_messages),
        "invalidEmailCount": len(merged_invalid),
        "invalidEmails": sorted(merged_invalid.values(), key=lambda item: item["email"]),
        "messages": merged_messages,
        "lastFetch": {
            "since": since.isoformat() if since else None,
            "before": before.isoformat() if before else None,
            "includeTrash": args.include_trash,
            "replaced": args.replace,
            "newMessagesThisFetch": len(bounces),
            "newInvalidThisFetch": len(invalid_map),
        },
    }

    try:
        from app.services.bounce_classifier import (  # noqa: WPS433
            classify_bounce_message,
            enrich_invalid_email_records,
        )

        classified_messages = []
        for message in payload["messages"]:
            enriched_message = dict(message)
            enriched_message.update(classify_bounce_message(message))
            classified_messages.append(enriched_message)
        payload["messages"] = classified_messages
        payload["invalidEmails"] = enrich_invalid_email_records(
            payload["invalidEmails"],
            classified_messages,
        )
        from collections import Counter

        payload["categoryCounts"] = dict(
            Counter(item.get("bounceCategory") or "other" for item in payload["invalidEmails"])
        )
    except Exception as exc:  # noqa: BLE001
        print(f"Warning: bounce classification skipped: {exc}")

    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(payload, indent=2), encoding="utf-8")

    print(f"Saved bounce report to {args.output}")
    print(f"Invalid emails total (merged): {len(payload['invalidEmails'])}")
    print(f"New invalid from this fetch: {len(invalid_map)}")
    if payload.get("categoryCounts"):
        print(f"Categories: {payload['categoryCounts']}")
    for item in payload["invalidEmails"][:20]:
        label = item.get("bounceCategoryLabel") or "bounce"
        print(f"  - {item['email']} [{label}] ({item.get('count', 1)})")
    if len(payload["invalidEmails"]) > 20:
        print(f"  ... and {len(payload['invalidEmails']) - 20} more")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
