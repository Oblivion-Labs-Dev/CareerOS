import sqlite3
import json
from collections import Counter

conn = sqlite3.connect("apps/api/data/career_os.db")
cur = conn.cursor()
cur.execute("SELECT id, payload FROM entities WHERE entity_type = 'aa_autopilot_job'")
rows = cur.fetchall()

non_email = []
for jid, pl in rows:
    p = json.loads(pl)
    if p.get('status') == 'SUBMITTED' and p.get('submissionSource') != 'email-detected':
        non_email.append((jid, p))

has_receipt = 0
no_receipt = 0
receipt_types = Counter()

for jid, p in non_email:
    ev = p.get('submissionEvidence') or {}
    rec = ev.get('receipt') or p.get('submissionReceipt')
    if rec:
        has_receipt += 1
        receipt_types['valid_receipt'] += 1
    elif ev.get('confirmationUrl') or ev.get('confirmationText'):
        has_receipt += 1
        receipt_types['url_or_text'] += 1
    else:
        no_receipt += 1

print(f"Total non-email: {len(non_email)}")
print(f"Has receipt/confirmation: {has_receipt}")
print(f"No receipt/confirmation: {no_receipt}")
print("Receipt types breakdown:", receipt_types)

for jid, p in non_email:
    ev = p.get('submissionEvidence') or {}
    rec = ev.get('receipt') or p.get('submissionReceipt')
    if not rec and not ev.get('confirmationUrl'):
        print(f"No receipt row: {jid} | {p.get('company')} | {p.get('title')} | ev={ev}")

conn.close()
