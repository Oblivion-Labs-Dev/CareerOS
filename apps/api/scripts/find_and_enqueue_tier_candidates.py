import uuid
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app.db.store import session_scope
from app.services.application_assistant.persistence import (
    list_autopilot_jobs,
    list_discovered_jobs,
    save_autopilot_job,
)
from app.services.application_assistant.job_filter_ranker import role_location_priority_bonus

with session_scope() as db:
    all_autopilot = list_autopilot_jobs(db)
    applied_urls = set()
    for j in all_autopilot:
        for key in ("applyUrl", "listingUrl"):
            u = j.get(key)
            if u:
                applied_urls.add(u.lower().rstrip("/"))

    discovered = list_discovered_jobs(db)
    print(f"Total discovered jobs pool: {len(discovered)}")

    # Score and filter candidate jobs
    qualified = []
    for dj in discovered:
        url = dj.get("applicationUrl") or dj.get("listingUrl") or ""
        if not url:
            continue
        if url.lower().rstrip("/") in applied_urls:
            continue
        
        # Focus on greenhouse boards which our headless automation handles 100% reliably
        if "greenhouse.io" not in url.lower():
            continue

        title = dj.get("title") or ""
        company = dj.get("company") or ""
        loc = dj.get("location") or ""
        
        # Calculate bonus using our exact tier system
        bonus = role_location_priority_bonus(dj)
        if bonus <= 0.0:
            continue

        qualified.append({
            "bonus": bonus,
            "company": company,
            "title": title,
            "location": loc,
            "url": url,
            "discoveredJobId": dj.get("id"),
            "matchScore": dj.get("matchScore") or 88.0,
        })

    # Sort descending by bonus tier, then match score
    qualified.sort(key=lambda x: (x["bonus"], x["matchScore"]), reverse=True)

    print(f"Found {len(qualified)} qualified tier jobs on Greenhouse!")
    for idx, q in enumerate(qualified[:20]):
        tier_label = "Tier 1 (Sr SWE WA)" if q["bonus"] == 100.0 else \
                     "Tier 2 (Sr SWE US)" if q["bonus"] == 70.0 else \
                     "Tier 3 (Staff/Princ)" if q["bonus"] >= 30.0 else "Tier 4 (SWE)"
        print(f"#{idx+1} [{tier_label} - {q['bonus']}pts] [{q['company']}] {q['title']} | Loc: {q['location']}")

    # Enqueue top candidates that are not yet queued
    to_enqueue = qualified[:15]
    print(f"\nEnqueuing top {len(to_enqueue)} jobs into aa_autopilot_job queue...")
    
    enqueued_jobs = []
    for cand in to_enqueue:
        job_id = f"apjob_{uuid.uuid4().hex[:8]}"
        job_payload = {
            "id": job_id,
            "company": cand["company"],
            "title": cand["title"],
            "location": cand["location"],
            "applyUrl": cand["url"],
            "listingUrl": cand["url"],
            "status": "QUEUED",
            "matchScore": cand["matchScore"],
            "source": "greenhouse_direct",
            "discoveredJobId": cand["discoveredJobId"],
            "metadata": {
                "location": cand["location"],
                "priorityBonus": cand["bonus"],
            }
        }
        save_autopilot_job(db, job_payload)
        applied_urls.add(cand["url"].lower().rstrip("/"))
        enqueued_jobs.append(job_payload)
        print(f"  -> Enqueued {job_id}: [{cand['company']}] {cand['title']} (Bonus: {cand['bonus']})")

    print(f"\nSuccessfully enqueued {len(enqueued_jobs)} prioritized jobs!")
