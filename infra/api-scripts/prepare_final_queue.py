import sqlite3
import json
import re

conn = sqlite3.connect('data/career_os.db')
cur = conn.cursor()

cur.execute("SELECT id, payload FROM entities WHERE entity_type = 'aa_autopilot_job'")
all_jobs = [(r[0], json.loads(r[1])) for r in cur.fetchall()]

def is_senior_swe(title: str) -> bool:
    t = title.lower()
    # Must be senior / sr / lead / staff
    is_senior = any(w in t for w in ["senior", "sr.", "sr ", "lead"])
    is_eng = any(w in t for w in ["software", "developer", "engineer", "swe", "frontend", "backend", "fullstack", "platform", "infrastructure", "systems"])
    not_eng = any(w in t for w in ["product manager", "recruiter", "sales", "account", "designer", "counsel", "attorney"])
    return is_senior and is_eng and not not_eng

def get_tier(job: dict) -> int:
    loc = (job.get('location') or '').lower()
    # Tier 1: WA (Seattle / Bellevue)
    if any(w in loc for w in ['seattle', 'bellevue', 'wa', 'washington']):
        return 1
    # Tier 2: US / Remote US
    non_us = ['canada', 'uk', 'london', 'germany', 'berlin', 'india', 'australia', 'singapore', 'brazil', 'france', 'spain', 'ireland', 'japan']
    if any(nu in loc for nu in non_us):
        return 99
    return 2

eligible_jobs = []
for j_id, j in all_jobs:
    title = j.get('title') or ''
    if not is_senior_swe(title):
        continue
    status = j.get('status')
    if status in ('SUBMITTED', 'INELIGIBLE', 'CANCELLED'):
        continue
    tier = get_tier(j)
    if tier < 90:
        eligible_jobs.append((tier, j_id, j))

# Sort: Tier 1 (WA) first, then Tier 2 (US)
eligible_jobs.sort(key=lambda x: x[0])

print(f"Total eligible Senior SWE jobs to queue: {len(eligible_jobs)}")

# Reset status of eligible jobs to QUEUED
reset_count = 0
for tier, j_id, j in eligible_jobs:
    j['status'] = 'QUEUED'
    j['failureReason'] = None
    j['reviewReason'] = None
    j['lastError'] = None
    # ensure priority
    j['priority'] = 100 if tier == 1 else 50
    cur.execute("UPDATE entities SET payload = ? WHERE id = ?", (json.dumps(j), j_id))
    reset_count += 1
    print(f"Tier {tier} | Company: {j.get('company')} | Title: {j.get('title')} | Loc: {j.get('location')}")

conn.commit()
conn.close()
print(f"\nSuccessfully queued {reset_count} Senior SWE jobs.")
