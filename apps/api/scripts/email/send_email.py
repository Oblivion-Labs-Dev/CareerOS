#!/usr/bin/env python3
"""CLI: send a Gmail message. Migrated from Arsenal scripts/email/send-email.mjs."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
DEFAULT_RESUME_PATH = Path(r"D:\Docs\Interview\Resume\Akshay_Borse_Resume.pdf")
sys.path.insert(0, str(ROOT))

from app.config import settings  # noqa: E402
from app.services.gmail_sender import EmailAttachment, SendEmailPayload, build_gmail_sender  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description="Send an email via Gmail SMTP")
    parser.add_argument("to", help="Recipient email address")
    parser.add_argument("subject", nargs="?", default="Hello from CareerOS Email")
    parser.add_argument("body", nargs="?", default="This email was sent using the CareerOS Gmail integration.")
    parser.add_argument("--html", action="store_true", help="Treat body as HTML")
    parser.add_argument("--no-resume", action="store_true", help="Send without attaching the default resume PDF")
    args = parser.parse_args()

    if not settings.gmail_user or not settings.gmail_app_password:
        print("Error: GMAIL_USER and GMAIL_APP_PASSWORD must be set in apps/api/.env")
        print("\nSetup:")
        print("1. Enable 2-Step Verification in Google Account settings.")
        print("2. Create a Gmail App Password (Mail / Other).")
        print("3. Add GMAIL_USER and GMAIL_APP_PASSWORD to apps/api/.env")
        return 1

    sender = build_gmail_sender(settings.gmail_user, settings.gmail_app_password)
    print(f"Verifying Gmail SMTP for {settings.gmail_user}...")
    if not sender.verify_connection():
        print("Error: SMTP verification failed. Check credentials.")
        return 1

    attachments: list[EmailAttachment] | None = None
    if not args.no_resume:
        if not DEFAULT_RESUME_PATH.exists():
            print(f"Warning: Resume not found at {DEFAULT_RESUME_PATH}; sending without attachment.")
        else:
            attachments = [
                EmailAttachment(
                    filename=DEFAULT_RESUME_PATH.name,
                    path=str(DEFAULT_RESUME_PATH),
                )
            ]

    payload = SendEmailPayload(
        to=args.to,
        subject=args.subject,
        text=None if args.html else args.body,
        html=args.body if args.html else None,
        attachments=attachments,
    )
    print(f"Sending email to {args.to}...")
    result = sender.send(payload)
    print(f"Success! Message-ID: {result['messageId']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
