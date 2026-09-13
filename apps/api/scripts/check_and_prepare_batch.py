import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app.db.store import session_scope
from app.services.application_assistant.persistence import (
    list_autopilot_jobs,
    list_discovered_jobs,
    save_autopilot_job,
    get_active_autopilot_run,
)
from app.services.application_assistant.job_filter_ranker import role_location_priority_bonus

with session_scope() as db:
    run = get_active_autopilot_run(db)
    print("Active run:", run.get("id") if run else "None", "Status:", run.get("status") if run else "None")
    
    all_jobs = list_autopilot_jobs(db)
    queued_jobs = [j for j in all_jobs if j.get("status") == "QUEUED"]
    submitted_jobs = [j for j in all_jobs if j.get("status") == "SUBMITTED"]
    print(f"Total autopilot jobs in DB: {len(all_jobs)}")
    print(f"Currently SUBMITTED: {len(submitted_jobs)}")
    print(f"Currently QUEUED: {len(queued_jobs)}")

    # Sort queued according to priority rule
    queued_jobs.sort(
        key=lambda j: (
            role_location_priority_bonus(j),
            (j.get("matchScore") or 0.0) >= 80.0,
            (j.get("matchScore") or 0.0),
            j.get("queuedAt") or "",
        ),
        reverse=True,
    )

    print("\n--- Current Top 15 in Queue ---")
    for idx, q in enumerate(queued_jobs[:15]):
        bonus = role_location_priority_bonus(q)
        print(f"#{idx+1} [{bonus:.1f} pts] [{q.get('company')}] {q.get('title')} | Loc: {q.get('location')} | URL: {q.get('applicationUrl')}")

    # Inspect discovered jobs to see if we need more Senior SWE WA / Senior SWE US candidates
    discovered = list_discovered_jobs(db)
    print(f"\nTotal discovered jobs in pool: {len(discovered)}")
    
    applied_urls = set()
    for j in all_jobs:
        u = j.get("applyUrl") or j.get("listingUrl")
        if u:
            applied_urls.add(u.lower().rstrip("/"))

    available_discovered = []
    for dj in discovered:
        u = dj.get("applicationUrl") or dj.get("listingUrl") or ""
        if u and u.lower().rstrip("/") not in applied_urls:
            bonus = role_location_priority_bonus(dj)
            available_discovered.append((bonus, dj))

    available_discovered.sort(key=lambda x: (x[0], x[1].get("matchScore") or 0.0), reverse=True)
    print("\n--- Top Available Discovered Candidates (Not yet enqueued) ---")
    for bonus, dj in available_discovered[:15]:
        print(f"[{bonus:.1f} pts] [{dj.get('company')}] {dj.get('title')} | Loc: {dj.get('location')} | URL: {dj.get('applicationUrl') or dj.get('listingUrl')}")
