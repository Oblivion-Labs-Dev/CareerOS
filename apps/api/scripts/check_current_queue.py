import sqlite3
import json

conn = sqlite3.connect("data/career_os.db")
cur = conn.cursor()

cur.execute("""
    SELECT id, payload FROM entities
    WHERE entity_type = 'aa_autopilot_job'
""")
all_jobs = cur.fetchall()

print(f"Total autopilot jobs in DB: {len(all_jobs)}")

# Status breakdown
status_counts = {}
for r_id, p_str in all_jobs:
    j = json.loads(p_str)
    s = j.get("status", "UNKNOWN")
    status_counts[s] = status_counts.get(s, 0) + 1

print("Status counts:", status_counts)

# Examine QUEUED jobs
queued_jobs = []
for r_id, p_str in all_jobs:
    j = json.loads(p_str)
    if j.get("status") == "QUEUED":
        queued_jobs.append((r_id, j))

print(f"\nQUEUED jobs count: {len(queued_jobs)}")
for r_id, j in queued_jobs[:15]:
    print(f"  {r_id} | {j.get('company')} | {j.get('title')} | Loc: {j.get('location')} | Prio: {j.get('priority')} | Score: {j.get('matchScore')}")

conn.close()
