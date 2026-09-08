import json
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app.db.store import session_scope
from app.services.application_assistant.persistence import list_discovered_jobs, list_autopilot_jobs

with session_scope() as db:
    discovered = list_discovered_jobs(db)
    existing_jobs = list_autopilot_jobs(db)
    
    applied_urls = set()
    for j in existing_jobs:
        u = j.get("applyUrl") or j.get("listingUrl")
        if u:
            applied_urls.add(u.lower().rstrip("/"))

    greenhouse_jobs = []
    for dj in discovered:
        url = dj.get("applicationUrl") or dj.get("listingUrl") or ""
        comp = dj.get("company", "")
        # Skip Anduril because of citizenship filter
        if "anduril" in comp.lower():
            continue
        if "job-boards.greenhouse.io" in url.lower() or "boards.greenhouse.io" in url.lower():
            if url.lower().rstrip("/") not in applied_urls:
                greenhouse_jobs.append(dj)

    print(f"Total unapplied Greenhouse jobs (non-Anduril): {len(greenhouse_jobs)}")
    by_comp = {}
    for j in greenhouse_jobs:
        c = j.get("company", "Unknown")
        by_comp[c] = by_comp.get(c, 0) + 1
    
    for c, cnt in sorted(by_comp.items(), key=lambda x: x[1], reverse=True):
        print(f"  {c}: {cnt}")

    print("\nSample unapplied jobs:")
    for j in greenhouse_jobs[:15]:
        print(f"  [{j.get('company')}] {j.get('title')} -> {j.get('applicationUrl') or j.get('listingUrl')}")
