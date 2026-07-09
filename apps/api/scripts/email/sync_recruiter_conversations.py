#!/usr/bin/env python3
"""CLI: sync recruiter Gmail threads into CareerOS data JSON."""

from __future__ import annotations

import json
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from app.config import settings  # noqa: E402
from app.services.gmail_imap import GmailImapClient  # noqa: E402

OUTPUT_PATH = ROOT / "data" / "recruiter_conversations.json"


def main() -> int:
    if not settings.gmail_user or not settings.gmail_app_password:
        print("Error: GMAIL_USER and GMAIL_APP_PASSWORD must be set in apps/api/.env")
        return 1

    client = GmailImapClient(settings.gmail_user, settings.gmail_app_password)
    print(f"Connecting to Gmail IMAP for {settings.gmail_user}...")
    uids = client.search_recruiter_uids(limit=150)
    print(f"Found {len(uids)} matching messages. Syncing up to 150...")

    conversations = client.fetch_threads(limit=150)
    OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT_PATH.write_text(json.dumps(conversations, indent=2), encoding="utf-8")
    print(f"Saved {len(conversations)} conversations to {OUTPUT_PATH}")
    time.sleep(0.1)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
