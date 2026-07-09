#!/usr/bin/env python3
"""CLI: list recent recruiter-related Gmail threads. Migrated from Arsenal scripts/email/fetch_recruiter_threads.mjs."""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from app.config import settings  # noqa: E402
from app.services.gmail_imap import GmailImapClient  # noqa: E402


def main() -> int:
    if not settings.gmail_user or not settings.gmail_app_password:
        print("Error: GMAIL_USER and GMAIL_APP_PASSWORD must be set in apps/api/.env")
        return 1

    client = GmailImapClient(settings.gmail_user, settings.gmail_app_password)
    print(f"Connecting to Gmail IMAP for {settings.gmail_user}...")
    threads = client.fetch_threads(limit=10)

    if not threads:
        print("No matching recruiter/outreach messages found.")
        return 0

    print("\n--- LATEST RECRUITER / OUTREACH CONVERSATIONS ---")
    for item in threads:
        from_label = item["fromName"] or item["fromAddress"] or "Unknown"
        if item["fromName"] and item["fromAddress"]:
            from_label = f'{item["fromName"]} <{item["fromAddress"]}>'
        print(f'\n• Subject: {item["subject"]}')
        print(f'  From:    {from_label}')
        print(f'  Date:    {item["date"]}')
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
