"""Check queue, filter for Senior SWE US roles, and prepare for 10-app run."""
import sys, io, uuid
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
sys.path.insert(0, r"d:\1 - Projects\Projects\CareerOS\CareerOS\apps\api")
from app.db.store import session_scope, get_kv
from app.services.application_assistant.persistence import (
    list_autopilot_jobs, list_discovered_jobs, save_autopilot_job,
)
from app.services.application_assistant.job_filter_ranker import (
    role_location_priority_bonus, evaluate_hard_filters,
)

ITAR_COMPANIES = {"spacex", "anduril", "anduril industries", "lockheed", "northrop", "raytheon", "l3harris", "bae systems", "general dynamics", "palantir defense"}

with session_scope() as db:
    profile = get_kv(db, "profile") or {}
    all_jobs = list_autopilot_jobs(db)
    
    # Current queue status
    queued = [j for j in all_jobs if j.get("status") == "QUEUED"]
    submitted = [j for j in all_jobs if j.get("status") == "SUBMITTED"]
    print(f"Current state: {len(submitted)} SUBMITTED, {len(queued)} QUEUED")
    
    # Filter queued to only Senior SWE (Tier 1 or Tier 2)
    senior_queued = []
    non_senior_queued = []
    for j in queued:
        bonus = role_location_priority_bonus(j)
        title_l = (j.get("title") or "").lower()
        is_senior_swe = bonus >= 70.0 and any(k in title_l for k in ("senior", "sr.", "sr "))
        if is_senior_swe:
            senior_queued.append((bonus, j))
        else:
            non_senior_queued.append(j)
    
    senior_queued.sort(key=lambda x: x[0], reverse=True)
    print(f"\nSenior SWE in queue: {len(senior_queued)}")
    for bonus, j in senior_queued:
        tier = "Tier 1 WA" if bonus == 100.0 else "Tier 2 US"
        print(f"  [{tier}] [{j.get('company')}] {j.get('title')} | {j.get('location', 'N/A')}")
    
    # Cancel non-Senior-SWE queued jobs for this run
    cancelled = 0
    for j in non_senior_queued:
        j["status"] = "SKIPPED"
        save_autopilot_job(db, j)
        cancelled += 1
    if cancelled:
        print(f"\nSkipped {cancelled} non-Senior-SWE jobs from queue")
    
    # If we need more Senior SWE, discover from pool
    needed = max(0, 12 - len(senior_queued))  # 12 to have buffer
    if needed > 0:
        print(f"\nNeed {needed} more Senior SWE jobs, scanning discovered pool...")
        
        applied_urls = set()
        for j in all_jobs:
            for key in ("applyUrl", "listingUrl", "applicationUrl"):
                u = j.get(key)
                if u:
                    applied_urls.add(u.lower().rstrip("/"))
        
        discovered = list_discovered_jobs(db)
        candidates = []
        
        for dj in discovered:
            url = dj.get("applicationUrl") or dj.get("listingUrl") or ""
            if not url or url.lower().rstrip("/") in applied_urls:
                continue
            if "greenhouse.io" not in url.lower():
                continue
            
            comp = (dj.get("company") or "").lower()
            if any(c in comp for c in ITAR_COMPANIES):
                continue
            
            bonus = role_location_priority_bonus(dj)
            title_l = (dj.get("title") or "").lower()
            
            # Only Senior SWE roles (Tier 1 or Tier 2)
            is_senior_swe = bonus >= 70.0 and any(k in title_l for k in ("senior", "sr.", "sr "))
            if not is_senior_swe:
                continue
            
            # Run hard filters
            passed, reason = evaluate_hard_filters(dj, profile, all_jobs, {})
            if not passed:
                continue
            
            candidates.append({
                "bonus": bonus,
                "company": dj.get("company"),
                "title": dj.get("title"),
                "location": dj.get("location"),
                "url": url,
                "discoveredJobId": dj.get("id"),
                "matchScore": dj.get("matchScore") or 88.0,
            })
        
        # Sort: Tier 1 (WA) first, then Tier 2 (US)
        candidates.sort(key=lambda x: (x["bonus"], x["matchScore"]), reverse=True)
        
        print(f"Found {len(candidates)} qualified Senior SWE Greenhouse jobs")
        for idx, c in enumerate(candidates[:20]):
            tier = "Tier 1 WA" if c["bonus"] == 100.0 else "Tier 2 US"
            print(f"  #{idx+1} [{tier}] [{c['company']}] {c['title']} | {c['location']}")
        
        # Enqueue top candidates
        to_enqueue = candidates[:needed]
        for cand in to_enqueue:
            job_id = f"apjob_{uuid.uuid4().hex[:8]}"
            payload = {
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
                "metadata": {"location": cand["location"], "priorityBonus": cand["bonus"]},
            }
            save_autopilot_job(db, payload)
            applied_urls.add(cand["url"].lower().rstrip("/"))
            print(f"  + Enqueued {job_id}: [{cand['company']}] {cand['title']}")
        
        print(f"\nEnqueued {len(to_enqueue)} new Senior SWE jobs")
    
    # Final queue count
    all_jobs2 = list_autopilot_jobs(db)
    final_queued = [j for j in all_jobs2 if j.get("status") == "QUEUED"]
    final_sr = [(role_location_priority_bonus(j), j) for j in final_queued]
    final_sr.sort(key=lambda x: x[0], reverse=True)
    print(f"\n=== FINAL QUEUE: {len(final_sr)} Senior SWE jobs ready ===")
    for bonus, j in final_sr[:15]:
        tier = "Tier 1 WA" if bonus == 100.0 else "Tier 2 US" if bonus >= 70.0 else f"Other ({bonus})"
        print(f"  [{tier}] [{j.get('company')}] {j.get('title')} | {j.get('location', 'N/A')}")
