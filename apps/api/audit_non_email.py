import sqlite3
import json

conn = sqlite3.connect("apps/api/data/career_os.db")
cur = conn.cursor()
cur.execute("SELECT id, payload FROM entities WHERE entity_type = 'aa_autopilot_job'")
rows = cur.fetchall()

non_email = []
for jid, pl in rows:
    p = json.loads(pl)
    if p.get('status') == 'SUBMITTED' and p.get('submissionSource') != 'email-detected':
        non_email.append((jid, p))

print(f"Non-email submitted count: {len(non_email)}")
for jid, p in non_email[:15]:
    ev = p.get('submissionEvidence') or {}
    print(f"JID: {jid} | Comp: {p.get('company')} | Title: {p.get('title')} | Source: {p.get('submissionSource')} | Evidence: {ev}")

conn.close()
