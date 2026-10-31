import sys
sys.path.insert(0, 'apps/api')

from app.db.store import session_scope
from app.services.application_assistant.persistence import get_autopilot_run, list_autopilot_jobs

with session_scope() as db:
    # Get all runs
    from app.db.store import list_entities
    runs = list_entities(db, "aa_autopilot_run")
    print(f"Total runs: {len(runs)}")
    for r in runs[-5:]:
        print(f"  {r.get('id')}: status={r.get('status')}, processed={r.get('processedCount')}, submitted={r.get('submittedCount')}, started={r.get('startedAt')}, stopped={r.get('stoppedAt')}")
    
    # Check the latest run
    if runs:
        latest = runs[-1]
        print(f"\nLatest run: {latest.get('id')}")
        print(f"  Status: {latest.get('status')}")
        print(f"  Target: {latest.get('targetProcessCount')}")
        print(f"  Processed: {latest.get('processedCount')}")
        print(f"  Submitted: {latest.get('submittedCount')}")
        print(f"  Staged: {latest.get('stagedCount')}")
        print(f"  Skipped: {latest.get('skippedCount')}")
        print(f"  Failed: {latest.get('failedCount')}")
        print(f"  Ineligible: {latest.get('ineligibleCount')}")
        print(f"  Settings: {latest.get('settings')}")