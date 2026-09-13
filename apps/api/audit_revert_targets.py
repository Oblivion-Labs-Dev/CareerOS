import sqlite3
import json
from collections import Counter

conn = sqlite3.connect("apps/api/data/career_os.db")
cur = conn.cursor()
cur.execute("SELECT id, payload FROM entities WHERE entity_type = 'aa_autopilot_job'")
rows = cur.fetchall()

submitted = []
for jid, pl in rows:
    p = json.loads(pl)
    if p.get('status') == 'SUBMITTED':
        submitted.append((jid, p))

print(f"Total SUBMITTED before: {len(submitted)}")

email_detected = [item for item in submitted if item[1].get('submissionSource') == 'email-detected']
print(f"Email detected: {len(email_detected)}")

from collections import defaultdict
grouped = defaultdict(list)
for jid, p in email_detected:
    comp = (p.get('company') or '').strip().lower()
    ev = p.get('submissionEvidence') or {}
    uid = ev.get('confirmationUid') or ev.get('confirmationText')
    grouped[(comp, uid)].append((jid, p))

reverted_jobs = []
kept_jobs = []

for (comp, uid), jobs in grouped.items():
    def sort_key(item):
        jid, p = item
        ev = p.get('submissionEvidence') or {}
        ct = (ev.get('confirmationText') or '').lower()
        title = (p.get('title') or '').lower()
        title_match = title in ct if title else False
        return (1 if title_match else 0, p.get('submittedAt') or '')
    
    sorted_jobs = sorted(jobs, key=sort_key, reverse=True)
    kept_jobs.append(sorted_jobs[0])
    for rej_jid, rej_p in sorted_jobs[1:]:
        reverted_jobs.append((rej_jid, rej_p))

print(f"Kept: {len(kept_jobs)}")
print(f"Reverted: {len(reverted_jobs)}")

# Let's inspect what previousStatus is for reverted jobs
prev_stats = Counter()
for jid, p in reverted_jobs:
    prev = p.get('previousStatus') or 'NEEDS_REVIEW'
    prev_stats[prev] += 1
print("Reverted jobs target previous statuses:", prev_stats)

conn.close()
