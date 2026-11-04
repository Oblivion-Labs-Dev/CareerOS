import sqlite3
import json
from collections import Counter

conn = sqlite3.connect("apps/api/data/career_os.db")
cur = conn.cursor()

print("=== AUTOPILOT JOBS STATUS BREAKDOWN ===")
cur.execute("SELECT payload FROM entities WHERE entity_type = 'aa_autopilot_job'")
rows = cur.fetchall()

status_counts = Counter()
needs_review_reasons = Counter()
submitted_jobs = []

for r in rows:
    p = json.loads(r[0])
    st = p.get("status")
    status_counts[st] += 1
    if st in ("NEEDS_REVIEW", "STAGED"):
        reason = p.get("failureReason") or p.get("skipReason") or p.get("lastError") or "Unknown"
        # shorten reason
        short_reason = reason.split("\n")[0][:120]
        needs_review_reasons[short_reason] += 1
    elif st == "SUBMITTED":
        submitted_jobs.append(p)

print(f"Total aa_autopilot_jobs: {len(rows)}")
for st, cnt in status_counts.most_common():
    print(f"  {st}: {cnt}")

print("\n=== TOP REASONS FOR NEEDS_REVIEW / STAGED (Total: " + str(status_counts.get("NEEDS_REVIEW", 0) + status_counts.get("STAGED", 0)) + ") ===")
for rsn, cnt in needs_review_reasons.most_common(15):
    print(f"  [{cnt}x] {rsn}")

print(f"\n=== SUBMITTED JOBS AUDIT (Total: {len(submitted_jobs)}) ===")
# Check receipts, confirmation URLs, timestamps
has_receipt = 0
has_confirmation_url = 0
receipt_prefixes = Counter()
created_dates = Counter()

for j in submitted_jobs:
    rcpt = j.get("submissionReceipt") or j.get("receiptId") or j.get("confirmationId")
    curl = j.get("confirmationUrl")
    ts = (j.get("submittedAt") or j.get("updatedAt") or j.get("createdAt") or "")[:10]
    created_dates[ts] += 1
    if rcpt:
        has_receipt += 1
        prefix = str(rcpt)[:10]
        receipt_prefixes[prefix] += 1
    if curl:
        has_confirmation_url += 1

print(f"Submitted with receipt ID: {has_receipt}/{len(submitted_jobs)}")
print(f"Submitted with confirmation URL: {has_confirmation_url}/{len(submitted_jobs)}")
print("\nSubmissions by Date:")
for dt, cnt in sorted(created_dates.items(), reverse=True)[:10]:
    print(f"  {dt}: {cnt}")

print("\nSample Receipts:")
for pr, cnt in receipt_prefixes.most_common(5):
    print(f"  prefix '{pr}': {cnt}")

# Check sample 5 submitted jobs
print("\nSample 5 submitted jobs:")
for j in submitted_jobs[:5]:
    comp = j.get("company") or j.get("companyName")
    title = j.get("title") or j.get("jobTitle")
    print(f"  - {comp} | {title} | submittedAt: {j.get('submittedAt')} | receipt: {j.get('submissionReceipt')} | confUrl: {j.get('confirmationUrl')}")
