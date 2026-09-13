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

print(f"Total SUBMITTED: {len(submitted)}")
sources = Counter()
email_detected = []
for jid, p in submitted:
    src = p.get('submissionSource') or (p.get('submissionEvidence') or {}).get('source') or 'unknown'
    sources[src] += 1
    if src == 'email-detected':
        email_detected.append((jid, p))

print("Sources breakdown:", sources)
print(f"Email detected count: {len(email_detected)}")

by_company = {}
for jid, p in email_detected:
    comp = p.get('company') or 'Unknown'
    by_company.setdefault(comp, []).append((jid, p))

print("\nEmail detected by company:")
for comp, jobs in sorted(by_company.items(), key=lambda x: len(x[1]), reverse=True)[:25]:
    print(f"  {comp}: {len(jobs)} jobs")

conn.close()
