import sqlite3
import json

conn = sqlite3.connect("apps/api/data/career_os.db")
cur = conn.cursor()
cur.execute("SELECT id, payload FROM entities WHERE entity_type = 'aa_autopilot_job'")
rows = cur.fetchall()

email_detected = []
for jid, pl in rows:
    p = json.loads(pl)
    if p.get('status') == 'SUBMITTED' and p.get('submissionSource') == 'email-detected':
        email_detected.append((jid, p))

print(f"Total email-detected: {len(email_detected)}")

from collections import defaultdict
grouped = defaultdict(list)
for jid, p in email_detected:
    comp = p.get('company', '').lower()
    ev = p.get('submissionEvidence') or {}
    uid = ev.get('confirmationUid') or ev.get('confirmationText')
    grouped[(comp, uid)].append((jid, p))

legit_kept = 0
reverted_count = 0

for (comp, uid), jobs in grouped.items():
    # Sort jobs by: exact title match in confirmationText first, then oldest submittedAt / createdAt
    def sort_key(item):
        jid, p = item
        ev = p.get('submissionEvidence') or {}
        ct = (ev.get('confirmationText') or '').lower()
        title = (p.get('title') or '').lower()
        title_match = title in ct if title else False
        return (1 if title_match else 0, p.get('submittedAt') or '')
    
    sorted_jobs = sorted(jobs, key=sort_key, reverse=True)
    # The first one is kept as legitimate
    kept_jid, kept_p = sorted_jobs[0]
    legit_kept += 1
    # The others are duplicates that reused the same email
    for rej_jid, rej_p in sorted_jobs[1:]:
        reverted_count += 1

print(f"Total unique email confirmations (kept): {legit_kept}")
print(f"Total duplicate false submissions to revert: {reverted_count}")

conn.close()
