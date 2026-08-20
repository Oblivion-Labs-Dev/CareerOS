import sys
sys.path.insert(0, "d:/1 - Projects/Projects/CareerOS/CareerOS/apps/api")
from app.db.store import session_scope
from app.services.application_assistant.persistence import list_autopilot_jobs, list_entities, ENTITY_AUTOPILOT_RUN

with session_scope() as db:
    jobs = list_autopilot_jobs(db)
    print(f"Total autopilot jobs in DB: {len(jobs)}")
    for j in jobs:
        print(f"[{j.get('status')}] {j.get('company')} - {j.get('title')}")
        print(f"  ErrorType: {j.get('lastErrorType')}")
        print(f"  ErrorMsg: {j.get('lastErrorMessage') or j.get('aiExplanation')}")
        print(f"  URL: {j.get('applicationUrl')}")
        print(f"  Checkpoints: {[c.get('step') for c in (j.get('checkpointHistory') or [])]}")
        print("-" * 50)
        
    runs = list_entities(db, ENTITY_AUTOPILOT_RUN)
    print(f"\nTotal runs: {len(runs)}")
    for r in runs:
        print(f"Run {r.get('id')} [{r.get('status')}]: Processed={r.get('processedCount')}, Submitted={r.get('submittedCount')}, Failed={r.get('failedCount')}, Staged={r.get('stagedCount')}")
