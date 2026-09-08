import json
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app.db.store import session_scope
from app.services.application_assistant.persistence import (
    list_autopilot_jobs,
    save_autopilot_job,
    list_discovered_jobs,
    get_active_autopilot_run,
)

with session_scope() as db:
    run = get_active_autopilot_run(db)
    print("Active run:", run.get("id") if run else "None")

    existing_jobs = list_autopilot_jobs(db)
    applied_urls = set()
    for j in existing_jobs:
        u = j.get("applyUrl") or j.get("listingUrl")
        if u:
            applied_urls.add(u.lower().rstrip("/"))

    discovered = list_discovered_jobs(db)

    # Pick top software engineering jobs from Affirm, Twilio, GitLab, Reddit, Smartsheet
    target_companies = ["affirm", "twilio", "gitlab", "reddit", "smartsheet", "robinhood"]
    candidates = []
    for dj in discovered:
        comp = (dj.get("company") or "").lower()
        title = (dj.get("title") or "").lower()
        url = dj.get("applicationUrl") or dj.get("listingUrl") or ""
        
        if comp in target_companies and "greenhouse.io" in url.lower():
            if url.lower().rstrip("/") not in applied_urls:
                # Target engineering / technical roles
                if any(kw in title for kw in ["software", "engineer", "developer", "backend", "fullstack", "frontend", "platform", "infrastructure"]):
                    candidates.append(dj)

    print(f"Total matching candidates found: {len(candidates)}")
    # Sort with Affirm first (since Affirm was 4/4 in batch 1!), then GitLab, Twilio, Reddit
    candidates.sort(key=lambda x: (
        0 if "affirm" in x.get("company", "").lower() else
        1 if "gitlab" in x.get("company", "").lower() else
        2 if "twilio" in x.get("company", "").lower() else
        3
    ))

    enqueued_count = 0
    for cand in candidates[:15]:
        import uuid
        job_id = f"apjob_{uuid.uuid4().hex[:8]}"
        job_payload = {
            "id": job_id,
            "company": cand.get("company"),
            "title": cand.get("title"),
            "applyUrl": cand.get("applicationUrl") or cand.get("listingUrl"),
            "listingUrl": cand.get("listingUrl"),
            "status": "QUEUED",
            "matchScore": 92.0,
            "source": "greenhouse_direct",
            "discoveredJobId": cand.get("id"),
        }
        save_autopilot_job(db, job_payload)
        applied_urls.add((cand.get("applicationUrl") or cand.get("listingUrl") or "").lower().rstrip("/"))
        enqueued_count += 1
        print(f"Enqueued: [{cand.get('company')}] {cand.get('title')} -> {cand.get('applicationUrl') or cand.get('listingUrl')}")

    print(f"\nSuccessfully enqueued {enqueued_count} high-priority engineering jobs!")
