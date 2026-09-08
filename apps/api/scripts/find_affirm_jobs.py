import json
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app.db.store import session_scope
from app.services.application_assistant.persistence import list_discovered_jobs, list_autopilot_jobs

with session_scope() as db:
    discovered = list_discovered_jobs(db)
    existing_jobs = list_autopilot_jobs(db)
    
    # Track existing job IDs and URLs
    applied_urls = set()
    for j in existing_jobs:
        u = j.get("applyUrl") or j.get("listingUrl")
        if u:
            applied_urls.add(u.lower().rstrip("/"))

    print(f"Total discovered jobs: {len(discovered)}")
    
    by_company = {}
    for dj in discovered:
        comp = dj.get("company", "Unknown")
        by_company[comp] = by_company.get(comp, 0) + 1
        
    print("\nDiscovered jobs by company:")
    for comp, count in sorted(by_company.items(), key=lambda x: x[1], reverse=True)[:15]:
        print(f"  {comp}: {count}")

    # Let's inspect Affirm specifically
    affirm_jobs = [dj for dj in discovered if dj.get("company", "").lower() == "affirm"]
    print(f"\nTotal Affirm discovered jobs: {len(affirm_jobs)}")
    unapplied_affirm = []
    for aj in affirm_jobs:
        u = (aj.get("applicationUrl") or aj.get("listingUrl") or "").lower().rstrip("/")
        if u and u not in applied_urls:
            unapplied_affirm.append(aj)
    print(f"Unapplied Affirm jobs: {len(unapplied_affirm)}")
    for aj in unapplied_affirm[:10]:
        print(f"  ID: {aj.get('id')} | Title: {aj.get('title')} | URL: {aj.get('applicationUrl') or aj.get('listingUrl')}")

