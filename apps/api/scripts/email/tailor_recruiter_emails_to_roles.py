#!/usr/bin/env python3
"""Tailor generated recruiter emails to each company's top 3 recent open roles that fit the resume.

Run after generate_personalized_recruiter_emails.py / generate_csv_recruiter_emails.py,
then send the output with send_recruiter_outreach_batch.py --emails <output>.
No model calls: roles come from the scraped jobs in the local DB and, with --live,
from the company's public Greenhouse/Lever/Ashby board when the DB has none.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from app.services.recruiter_outreach_roles import (  # noqa: E402
    DEFAULT_MAX_AGE_DAYS,
    DEFAULT_MIN_SCORE,
    fetch_live_board_jobs,
    load_open_jobs,
    tailor_emails,
)

HERE = Path(__file__).resolve().parent
DEFAULT_INPUT = HERE / "personalized_recruiter_emails.json"
DEFAULT_DB = ROOT / "data" / "career_os.db"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--emails", type=Path, default=DEFAULT_INPUT, help="Generated emails JSON")
    parser.add_argument("--output", type=Path, help="Defaults to <emails>_tailored.json")
    parser.add_argument("--db", type=Path, default=DEFAULT_DB, help="CareerOS SQLite DB with scraped jobs")
    parser.add_argument("--min-score", type=float, default=DEFAULT_MIN_SCORE,
                        help="Lowest resume match score for a role to be mentioned")
    parser.add_argument("--max-age-days", type=int, default=DEFAULT_MAX_AGE_DAYS,
                        help="Skip postings with a known date older than this")
    parser.add_argument("--live", action="store_true",
                        help="Look up the public ATS board for companies with no jobs in the DB")
    parser.add_argument("--limit", type=int, default=0, help="Only tailor the first N emails (0 = all)")
    parser.add_argument("--show", type=int, default=0, help="Print the first N tailored emails")
    args = parser.parse_args()
    for stream in (sys.stdout, sys.stderr):
        stream.reconfigure(errors="replace")

    if not args.emails.exists():
        print(f"Missing emails file: {args.emails}", file=sys.stderr)
        return 1
    output = args.output or args.emails.with_name(f"{args.emails.stem}_tailored.json")

    emails = json.loads(args.emails.read_text(encoding="utf-8"))
    if args.limit:
        emails = emails[: args.limit]
    live = (lambda company, email: fetch_live_board_jobs(company, email, args.max_age_days)) if args.live else None
    tailored, unmatched = tailor_emails(emails, load_open_jobs(args.db), args.min_score,
                                        args.max_age_days, live)
    output.write_text(json.dumps(tailored, indent=2, ensure_ascii=False), encoding="utf-8")

    matched = sum(1 for e in tailored if e.get("roleMatched"))
    print(f"Tailored {matched}/{len(tailored)} emails to open roles -> {output}")
    for email in tailored:
        if email.get("roleSource", "").startswith("live board lookup failed"):
            print(f"WARNING {email['company']}: {email['roleSource']}", file=sys.stderr)
    if unmatched:
        print(f"No fitting open role (kept original email) for {len(unmatched)} companies: "
              + ", ".join(sorted(set(unmatched))))
    for email in tailored[: args.show]:
        print(f"\n--- {email['email']} | {email['subject']}\n{email['body']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
