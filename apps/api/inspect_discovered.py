import sys
sys.stdout.reconfigure(encoding='utf-8')
sys.path.insert(0, 'd:/1 - Projects/Projects/CareerOS/CareerOS/apps/api')
from app.db.store import session_scope, list_entities
from app.services.application_assistant.persistence import list_discovered_jobs

with session_scope() as db:
    raw = list_discovered_jobs(db, active_only=False, exclude_demo=False)
    print("TOTAL DISCOVERED JOBS:", len(raw))
    for r in raw:
        print(f"  {r.get('id')} | {r.get('company')} | {r.get('title')} | active={r.get('active')} | url={r.get('applicationUrl') or r.get('listingUrl')}")
