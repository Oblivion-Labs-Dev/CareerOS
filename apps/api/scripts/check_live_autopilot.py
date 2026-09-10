import sqlite3
import json
from collections import Counter

conn = sqlite3.connect('data/career_os.db')
cur = conn.cursor()

cur.execute("SELECT DISTINCT entity_type FROM entities")
print("Entity types:", [r[0] for r in cur.fetchall()])

cur.execute("SELECT id, entity_type, payload FROM entities WHERE entity_type LIKE '%profile%' OR entity_type LIKE '%user%'")
for r in cur.fetchall():
    print(f"Profile entity: {r[0]} | Type: {r[1]}")



# Check jobs
cur.execute("SELECT id, payload FROM entities WHERE entity_type = 'aa_autopilot_job'")
jobs = [json.loads(r[1]) for r in cur.fetchall()]
counts = Counter(j.get('status') for j in jobs)
print("\n=== JOB COUNTS ===")
for st, cnt in sorted(counts.items(), key=lambda x: -x[1]):
    print(f"{st}: {cnt}")

print("\n=== RECENT SUBMITTED JOBS ===")
submitted = [j for j in jobs if j.get('status') == 'SUBMITTED']
submitted.sort(key=lambda j: j.get('updatedAt') or '', reverse=True)
for s in submitted[:10]:
    print(f"Company: {s.get('company')} | Title: {s.get('title')} | Loc: {s.get('location')} | Resume: {s.get('resumeFilename')} | TailoringFailed: {s.get('tailoringFailed')}")

print("\n=== QUEUED JOBS (Top 10) ===")
queued = [j for j in jobs if j.get('status') in ('QUEUED', 'APPLYING')]
for q in queued[:10]:
    print(f"ID: {q.get('id')} | Company: {q.get('company')} | Title: {q.get('title')} | Loc: {q.get('location')}")
