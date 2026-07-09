#!/usr/bin/env python3
"""Fetch Gmail bounce / undelivered messages and extract invalid recipient emails."""

from __future__ import annotations

import email
import imaplib
import json
import re
import sys
from datetime import datetime, timezone
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


def search_bounce_uids(client: imaplib.IMAP4_SSL, limit: int) -> list[str]:
    queries = [
        '(FROM "mailer-daemon@googlemail.com")',
        '(FROM "Mail Delivery Subsystem")',
        '(SUBJECT "Delivery Status Notification")',
        '(SUBJECT "Undelivered Mail Returned to Sender")',
        '(SUBJECT "Mail Delivery Failed")',
        '(SUBJECT "Address not found")',
        '(SUBJECT "Delivery incomplete")',
    ]
    uid_set: set[str] = set()
    for query in queries:
        status, data = client.uid("search", None, query)
        if status == "OK" and data and data[0]:
            uid_set.update(data[0].decode().split())
    ordered = sorted(uid_set, key=int, reverse=True)
    return ordered[:limit]


def open_mailbox(client: imaplib.IMAP4_SSL) -> None:
    for mailbox in ('"[Gmail]/All Mail"', "INBOX"):
        status, _ = client._simple_command("SELECT", mailbox)
        if status == "OK":
            client.state = "SELECTED"
            return
    raise RuntimeError("Unable to open Gmail mailbox.")


def main() -> int:
    output_path = Path(sys.argv[1]) if len(sys.argv) > 1 else DEFAULT_OUTPUT
    limit = int(sys.argv[2]) if len(sys.argv) > 2 else 500

    if not settings.gmail_user or not settings.gmail_app_password:
        print("Error: GMAIL_USER and GMAIL_APP_PASSWORD must be set in apps/api/.env")
        return 1

    client = imaplib.IMAP4_SSL("imap.gmail.com")
    client.login(settings.gmail_user, settings.gmail_app_password)
    open_mailbox(client)

    uids = search_bounce_uids(client, limit=limit)
    print(f"Found {len(uids)} bounce-related messages")

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
        body = message_body(msg)
        failed = extract_failed_addresses(subject, body)
        if not failed:
            continue
        date_raw = msg.get("Date")
        try:
            date_value = parsedate_to_datetime(date_raw).isoformat() if date_raw else None
        except (TypeError, ValueError, OverflowError):
            date_value = None

        entry = {
            "uid": uid,
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
                },
            )
            record = invalid_map[address]
            record["count"] += 1
            if date_value and (not record["firstSeenAt"] or date_value > record["firstSeenAt"]):
                record["firstSeenAt"] = date_value
            if subject not in record["subjects"]:
                record["subjects"].append(subject)

    client.logout()

    payload = {
        "generatedAt": datetime.now(timezone.utc).isoformat(),
        "bounceMessages": len(bounces),
        "invalidEmailCount": len(invalid_map),
        "invalidEmails": sorted(invalid_map.values(), key=lambda item: item["email"]),
        "messages": bounces,
    }
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")

    print(f"Saved bounce report to {output_path}")
    print(f"Invalid emails detected: {len(invalid_map)}")
    for item in payload["invalidEmails"][:20]:
        print(f"  - {item['email']} ({item['count']} bounce(s))")
    if len(invalid_map) > 20:
        print(f"  ... and {len(invalid_map) - 20} more")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
