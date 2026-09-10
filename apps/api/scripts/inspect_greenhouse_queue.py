import sqlite3
import json

conn = sqlite3.connect("data/career_os.db")
cur = conn.cursor()

cur.execute("""
    SELECT id, payload FROM entities
    WHERE entity_type = 'aa_autopilot_job' AND json_extract(payload, '$.status') = 'QUEUED'
""")
rows = cur.fetchall()

print(f"Total QUEUED jobs: {len(rows)}")

greenhouse_jobs = []
other_jobs = []

for r_id, p_str in rows:
    j = json.loads(p_str)
    url = (j.get("applyUrl") or j.get("listingUrl") or "").lower()
    title = (j.get("title") or "").lower()
    loc = (j.get("location") or "").lower()
    comp = (j.get("company") or "").lower()
    
    # Check if Greenhouse
    is_gh = "greenhouse.io" in url
    
    # Priority
    prio = j.get("priority", 0)
    
    if is_gh:
        greenhouse_jobs.append((r_id, j, prio))
    else:
        other_jobs.append((r_id, j, prio))

print(f"Greenhouse jobs: {len(greenhouse_jobs)}")
print(f"Other ATS jobs: {len(other_jobs)}")

# Sort Greenhouse jobs: priority 100 first, then 50
greenhouse_jobs.sort(key=lambda x: x[2], reverse=True)

print("\n--- TOP 25 GREENHOUSE QUEUED JOBS ---")
for r_id, j, prio in greenhouse_jobs[:25]:
    url = j.get("applyUrl") or j.get("listingUrl")
    print(f"[{prio}] {j.get('company')} | {j.get('title')} | Loc: {j.get('location')} | Score: {j.get('matchScore')} | {url[:60]}")

conn.close()
