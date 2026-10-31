import sys
sys.path.insert(0, 'apps/api')

from app.db.store import session_scope
from app.services.application_assistant.persistence import list_autopilot_jobs
from app.services.application_assistant.domain import AutopilotJobStatus

with session_scope() as db:
    jobs = list_autopilot_jobs(db)
    applying = [j for j in jobs if j.get('status') == AutopilotJobStatus.APPLYING.value]
    print(f"APPLYING jobs: {len(applying)}")
    for j in applying:
        print(f"  {j.get('company')} - {j.get('title')}")
        print(f"    ID: {j.get('id')}")
        print(f"    updatedAt: {j.get('updatedAt')}")
        print(f"    lockedAt: {j.get('lockedAt')}")
        print(f"    lockedBy: {j.get('lockedBy')}")
        print(f"    lockExpiresAt: {j.get('lockExpiresAt')}")
        print(f"    applicationStartedAt: {j.get('applicationStartedAt')}")
        print(f"    attemptCount: {j.get('attemptCount')}")
        print(f"    lastAttemptRunId: {j.get('lastAttemptRunId')}")
    
    # Also check the run
    from app.services.application_assistant.persistence import get_autopilot_run
    run = get_autopilot_run(db, "aprun_6e4ac3c5-ebe6-4ea6-9ba3-95998f1358bf")
    if run:
        print(f"\nRun: {run.get('id')}")
        print(f"  Status: {run.get('status')}")
        print(f"  Processed: {run.get('processedCount')}")
        print(f"  CurrentJobId: {run.get('currentJobId')}")
        print(f"  LastHeartbeat: {run.get('lastHeartbeatAt')}")