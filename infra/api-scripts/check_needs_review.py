import sqlite3
import json

conn = sqlite3.connect('data/career_os.db')
cur = conn.cursor()

cur.execute("SELECT id, payload FROM entities WHERE entity_type = 'aa_autopilot_job'")
jobs = [json.loads(r[1]) for r in cur.fetchall()]

needs_review = [j for j in jobs if j.get('status') == 'NEEDS_REVIEW']
print(f"Total NEEDS_REVIEW: {len(needs_review)}")
for j in needs_review:
    print(f"ID: {j.get('id')} | Company: {j.get('company')} | Title: {j.get('title')} | Loc: {j.get('location')}")
    print(f"  Reason: {j.get('failureReason') or j.get('reviewReason') or j.get('lastError')}")
    if j.get('tailoredResume'):
        print(f"  TailoredResume: {j.get('tailoredResume').get('pdfPath')}")
    print()
