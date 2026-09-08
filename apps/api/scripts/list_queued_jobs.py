import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app.db.store import session_scope
from app.services.application_assistant.persistence import list_autopilot_jobs

with session_scope() as db:
    jobs = list_autopilot_jobs(db)
    queued = [j for j in jobs if j.get("status") == "QUEUED"]
    print(f"Total QUEUED jobs: {len(queued)}")
    for j in queued:
        print(f"[{j.get('id')}] {j.get('company')} - {j.get('title')} | URL: {j.get('applyUrl') or j.get('listingUrl') or j.get('applicationUrl')}")
