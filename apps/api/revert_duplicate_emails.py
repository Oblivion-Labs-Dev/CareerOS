"""Revert duplicate email-detected submissions.

One confirmation email should credit exactly one application. Historical runs
of the reconciler matched the same email to multiple jobs at the same company
(e.g. 16 Coinbase jobs all stamped from one email). This script keeps the
single best match per (company, confirmationUid/confirmationText) and reverts
the rest to their previous status.

DRY RUN by default. Pass --apply to commit.
"""
import sqlite3
import json
import sys
from collections import defaultdict

sys.stdout.reconfigure(encoding='utf-8')

db_path = "d:/1 - Projects/Projects/CareerOS/CareerOS/apps/api/data/career_os.db"
apply_mode = "--apply" in sys.argv

conn = sqlite3.connect(db_path)
cur = conn.cursor()
cur.execute("SELECT id, payload FROM entities WHERE entity_type = 'aa_autopilot_job'")
rows = cur.fetchall()

# Group email-detected jobs by (normalised_company, confirmation_key)
groups: dict[str, list[tuple[str, dict]]] = defaultdict(list)
non_email = 0
email_detected = 0

for jid, pl in rows:
    p = json.loads(pl)
    if p.get("submissionSource") != "email-detected":
        non_email += 1
        continue
    email_detected += 1
    company = (p.get("company") or "").lower().strip()
    evidence = p.get("submissionEvidence") or {}
    uid = str(evidence.get("confirmationUid") or "")
    text = str(evidence.get("confirmationText") or "")[:120]
    key = uid if uid else f"text:{company}:{text}"
    groups[key].append((jid, p))

print(f"Total autopilot jobs: {len(rows)}")
print(f"Non-email submissions: {non_email}")
print(f"Email-detected submissions: {email_detected}")
print(f"Unique confirmation keys: {len(groups)}")

to_revert: list[tuple[str, dict]] = []
to_keep: list[tuple[str, dict]] = []

for key, jobs in groups.items():
    if len(jobs) <= 1:
        to_keep.append(jobs[0])
        continue
    # Keep the single best match: prefer title-matched, then oldest submittedAt
    def sort_key(item):
        _, p = item
        ev = p.get("submissionEvidence") or {}
        matched_on = ev.get("confirmationMatchedOn") or ""
        title_priority = 0 if matched_on == "title" else 1
        submitted_at = p.get("submittedAt") or ""
        return (title_priority, submitted_at)

    sorted_jobs = sorted(jobs, key=sort_key)
    to_keep.append(sorted_jobs[0])
    to_revert.extend(sorted_jobs[1:])

print(f"\nJobs to KEEP as email-detected: {len(to_keep)}")
print(f"Jobs to REVERT (duplicate credits): {len(to_revert)}")

# Show some examples
print("\nSample reverts:")
for jid, p in to_revert[:10]:
    prev = p.get("previousStatus") or "NEEDS_REVIEW"
    print(f"  {jid} ({p.get('company')}) [{p.get('title')[:50]}] -> revert to {prev}")

if apply_mode:
    print("\n=== APPLYING CHANGES ===")
    reverted = 0
    for jid, p in to_revert:
        prev = p.get("previousStatus") or "NEEDS_REVIEW"
        p["status"] = prev
        p["submissionSource"] = None
        p["submittedAt"] = None
        p["hasPersistentBlock"] = False
        payload_str = json.dumps(p, ensure_ascii=False)
        cur.execute("UPDATE entities SET payload = ? WHERE id = ?", (payload_str, jid))
        reverted += 1
    conn.commit()
    print(f"Reverted {reverted} duplicate email-detected jobs")

    # Verify
    cur.execute("SELECT payload FROM entities WHERE entity_type = 'aa_autopilot_job'")
    final_count = 0
    for (pl,) in cur.fetchall():
        p = json.loads(pl)
        if p.get("status") == "SUBMITTED":
            final_count += 1
    print(f"New SUBMITTED count: {final_count}")
else:
    print("\n** DRY RUN ** — pass --apply to commit changes")

conn.close()
