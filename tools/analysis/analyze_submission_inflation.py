import sqlite3
import json
from collections import Counter

conn = sqlite3.connect("apps/api/data/career_os.db")
cur = conn.cursor()

print("=== INSPECTING EMAIL-DETECTED JOBS ===")
cur.execute("SELECT payload FROM entities WHERE entity_type = 'aa_autopilot_job'")
email_detected = []
direct_submitted = []

for r in cur.fetchall():
    p = json.loads(r[0])
    if p.get("status") == "SUBMITTED":
        if p.get("submissionSource") == "email-detected":
            email_detected.append(p)
        else:
            direct_submitted.append(p)

print(f"Total email-detected SUBMITTED: {len(email_detected)}")
print(f"Total direct/other SUBMITTED: {len(direct_submitted)}")

# Check unique confirmation texts / UIDs among email-detected
uids = Counter()
texts = Counter()
for j in email_detected:
    ev = j.get("submissionEvidence") or {}
    uids[str(ev.get("confirmationUid"))] += 1
    texts[str(ev.get("confirmationText"))] += 1

print(f"\nUnique confirmation UIDs: {len(uids)}")
print(f"Unique confirmation texts: {len(texts)}")
print("Top confirmation texts:")
for t, c in texts.most_common(10):
    print(f"  [{c}x] {t}")

print("\n=== INSPECTING DIRECT-AUTOPILOT-NO-RECEIPT (Total: " + str(len(direct_submitted)) + ") ===")
direct_runs = Counter()
for j in direct_submitted:
    run_id = j.get("lastAttemptRunId") or "no-run"
    direct_runs[run_id] += 1

print("By lastAttemptRunId:")
for rid, c in direct_runs.most_common(10):
    print(f"  [{c}x] {rid}")
