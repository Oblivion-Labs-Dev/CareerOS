import uuid
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app.db.store import session_scope, get_kv
from app.services.application_assistant.persistence import (
    list_autopilot_jobs,
    list_discovered_jobs,
    save_autopilot_job,
)
from app.services.application_assistant.job_filter_ranker import role_location_priority_bonus, evaluate_hard_filters

with session_scope() as db:
    profile = get_kv(db, "profile") or {}
    all_autopilot = list_autopilot_jobs(db)
    
    # Remove any ITAR/defense jobs we enqueued earlier that will get blocked
    itar_companies = {"spacex", "anduril", "anduril industries"}
    removed_count = 0
    for j in all_autopilot:
        if j.get("status") == "QUEUED" and (j.get("company") or "").lower() in itar_companies:
            j["status"] = "CANCELLED"
            save_autopilot_job(db, j)
            removed_count += 1
    if removed_count:
        print(f"Cancelled {removed_count} queued ITAR jobs (SpaceX/Anduril) due to visa sponsorship requirement.")

    applied_urls = set()
    for j in all_autopilot:
        if j.get("status") in ("SUBMITTED", "APPLIED", "IN_PROGRESS", "QUEUED"):
            for key in ("applyUrl", "listingUrl", "applicationUrl"):
                u = j.get(key)
                if u:
                    applied_urls.add(u.lower().rstrip("/"))

    discovered = list_discovered_jobs(db)
    qualified = []

    for dj in discovered:
        url = dj.get("applicationUrl") or dj.get("listingUrl") or ""
        if not url or url.lower().rstrip("/") in applied_urls:
            continue
        if "greenhouse.io" not in url.lower():
            continue

        comp = (dj.get("company") or "").lower()
        if any(c in comp for c in itar_companies):
            continue

        # Run hard filters
        passed, reason = evaluate_hard_filters(dj, profile, all_autopilot, {})
        if not passed:
            continue

        bonus = role_location_priority_bonus(dj)
        if bonus <= 0.0:
            continue

        qualified.append({
            "bonus": bonus,
            "company": dj.get("company"),
            "title": dj.get("title"),
            "location": dj.get("location"),
            "url": url,
            "discoveredJobId": dj.get("id"),
            "matchScore": dj.get("matchScore") or 88.0,
        })

    # Sort strictly by priority bonus (Tier 1 -> Tier 2 -> Tier 3 -> Tier 4), then matchScore
    qualified.sort(key=lambda x: (x["bonus"], x["matchScore"]), reverse=True)

    print(f"\nDiscovered {len(qualified)} fully-qualified non-defense Greenhouse jobs!")
    for idx, q in enumerate(qualified[:25]):
        tier_label = "Tier 1 (Sr SWE WA)" if q["bonus"] == 100.0 else \
                     "Tier 2 (Sr SWE US)" if q["bonus"] == 70.0 else \
                     "Tier 3 (Staff/Princ)" if q["bonus"] >= 30.0 else "Tier 4 (SWE)"
        print(f"#{idx+1} [{tier_label} - {q['bonus']}pts] [{q['company']}] {q['title']} | Loc: {q['location']}")

    # Enqueue top 15
    to_enqueue = qualified[:15]
    print(f"\nEnqueuing {len(to_enqueue)} jobs into aa_autopilot_job queue...")
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
            "metadata": {
                "location": cand["location"],
                "priorityBonus": cand["bonus"],
            }
        }
        save_autopilot_job(db, payload)
        applied_urls.add(cand["url"].lower().rstrip("/"))
        print(f"  + Enqueued {job_id}: [{cand['company']}] {cand['title']} (Tier Bonus: {cand['bonus']})")

    print("\nQueue updated successfully!")
