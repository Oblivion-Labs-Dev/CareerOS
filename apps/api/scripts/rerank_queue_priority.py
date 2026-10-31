import sys, time
sys.stdout.reconfigure(encoding="utf-8", errors="replace")
from app.db.store import session_scope
from app.services.application_assistant.persistence import list_autopilot_jobs, save_autopilot_job
from app.services.application_assistant.domain import AutopilotJobStatus
from app.services.application_assistant.job_filter_ranker import (
    queue_priority_score,
    role_application_tier,
)

t0 = time.time()
with session_scope() as db:
    queued = [j for j in list_autopilot_jobs(db) if j.get("status") == AutopilotJobStatus.QUEUED.value]
print("queued rows:", len(queued))
ordered = sorted(queued, key=queue_priority_score, reverse=True)

changed = 0
with session_scope() as db:
    for position, job in enumerate(ordered):
        priority = queue_priority_score(job)
        if job.get("queuePriority") == priority and job.get("queuePosition") == position:
            continue
        job["queuePriority"] = priority
        job["queuePosition"] = position
        save_autopilot_job(db, job)
        changed += 1
print(f"updated {changed} rows in {round(time.time()-t0,1)}s")

tier_names = {3.0: "AI/ML engineering", 2.0: "Forward Deployed", 1.0: "Senior SWE", 0.0: "other"}
from collections import Counter
top_mix = Counter(tier_names[role_application_tier(j)] for j in ordered[:100])
print("\ntop-100 tier mix:", dict(top_mix))
print("first 10:")
for j in ordered[:10]:
    print(f"  {tier_names[role_application_tier(j)]:<17} {j.get('company'):<22} {j.get('title')[:55]}")
