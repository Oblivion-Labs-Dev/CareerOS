#!/usr/bin/env python3
"""Refresh Oracle + DocuSign target company jobs and store in CareerOS."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.db.store import init_db, session_scope  # noqa: E402
from app.services.target_company_jobs import (  # noqa: E402
    filter_jobs,
    format_whatsapp,
    merge_oracle_seed_entries,
    refresh_and_store,
)


def main() -> int:
    parser = argparse.ArgumentParser(description="Refresh Oracle and DocuSign target jobs")
    parser.add_argument("--no-verify-oracle", action="store_true", help="Skip live URL checks for Oracle")
    parser.add_argument("--merge-oracle-json", type=Path, help="Merge Oracle seed entries from JSON file")
    parser.add_argument("--whatsapp", action="store_true", help="Print WhatsApp-formatted output")
    parser.add_argument("--company", default="all", choices=["all", "Oracle", "DocuSign"])
    parser.add_argument("--location", default="all", choices=["all", "remote", "washington"])
    args = parser.parse_args()

    init_db()
    if args.merge_oracle_json:
        entries = json.loads(args.merge_oracle_json.read_text(encoding="utf-8"))
        merge_oracle_seed_entries(entries if isinstance(entries, list) else entries.get("jobs", []))

    with session_scope() as db:
        snapshot = refresh_and_store(db, verify_oracle=not args.no_verify_oracle)

    companies = snapshot.get("companies") or {}
    print(
        f"Refreshed at {snapshot.get('refreshedAt')} · "
        f"Oracle {companies.get('Oracle', {}).get('active', 0)}/{companies.get('Oracle', {}).get('total', 0)} active · "
        f"DocuSign {companies.get('DocuSign', {}).get('total', 0)}"
    )

    if args.whatsapp:
        jobs = filter_jobs(snapshot.get("jobs") or [], company=args.company, location=args.location, active_only=True)
        print()
        print(format_whatsapp(jobs, title=f"Target jobs · {args.company} · {args.location}"))

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
