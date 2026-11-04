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

print(f"Unique (company, confirmation): {len(grouped)}")
for (comp, uid), jobs in sorted(grouped.items(), key=lambda x: len(x[1]), reverse=True):
    print(f"Comp: {comp} | Conf: {uid} | Count: {len(jobs)}")
    for jid, p in jobs[:3]:
        prev = p.get('previousStatus')
        skip = p.get('skipReason')
        fail = p.get('failureReason')
        print(f"   [{jid}] Title: {p.get('title')} | PrevStatus: {prev} | Skip: {skip[:60] if skip else None} | Fail: {fail[:60] if fail else None}")

conn.close()
