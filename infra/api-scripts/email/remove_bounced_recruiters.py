#!/usr/bin/env python3
"""Remove bounced recruiter emails from outreach lists."""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
DEFAULT_BOUNCES = ROOT / "data" / "bounced_recruiter_emails.json"
DEFAULT_CSV_EMAILS = Path(__file__).resolve().parent / "personalized_csv_recruiter_emails.json"
DEFAULT_ORIG_EMAILS = Path(__file__).resolve().parent / "personalized_recruiter_emails.json"
DEFAULT_OUTPUT = Path(__file__).resolve().parent / "personalized_csv_recruiter_emails_cleaned.json"
DEFAULT_REPORT = ROOT / "data" / "bounced_recruiter_summary.json"


def load_bounced_emails(path: Path) -> set[str]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    return {item["email"].lower() for item in payload.get("invalidEmails", [])}


def main() -> int:
    bounces_path = Path(sys.argv[1]) if len(sys.argv) > 1 else DEFAULT_BOUNCES
    source_path = Path(sys.argv[2]) if len(sys.argv) > 2 else DEFAULT_CSV_EMAILS
    output_path = Path(sys.argv[3]) if len(sys.argv) > 3 else DEFAULT_OUTPUT

    if not bounces_path.exists():
        print(f"Bounce report not found: {bounces_path}")
        print("Run: python scripts/email/fetch_bounced_emails.py")
        return 1
    if not source_path.exists():
        print(f"Source list not found: {source_path}")
        return 1

    bounced = load_bounced_emails(bounces_path)
    recruiters = json.loads(source_path.read_text(encoding="utf-8"))

    kept: list[dict] = []
    removed: list[dict] = []
    for entry in recruiters:
        email = str(entry.get("email", "")).lower()
        if email in bounced:
            removed.append(entry)
        else:
            kept.append(entry)

    output_path.write_text(json.dumps(kept, indent=2), encoding="utf-8")

    orig_removed = 0
    if DEFAULT_ORIG_EMAILS.exists():
        orig = json.loads(DEFAULT_ORIG_EMAILS.read_text(encoding="utf-8"))
        orig_removed = sum(1 for entry in orig if str(entry.get("email", "")).lower() in bounced)

    report = {
        "sourceList": str(source_path),
        "cleanedList": str(output_path),
        "originalCount": len(recruiters),
        "removedCount": len(removed),
        "remainingCount": len(kept),
        "bouncedInOriginal64List": orig_removed,
        "removedEmails": sorted({str(entry.get("email", "")).lower() for entry in removed}),
    }
    DEFAULT_REPORT.parent.mkdir(parents=True, exist_ok=True)
    DEFAULT_REPORT.write_text(json.dumps(report, indent=2), encoding="utf-8")

    print(f"Removed {len(removed)} bounced emails from {len(recruiters)} total")
    print(f"Clean list saved to {output_path}")
    print(f"Summary saved to {DEFAULT_REPORT}")
    print(f"Remaining valid targets: {len(kept)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
