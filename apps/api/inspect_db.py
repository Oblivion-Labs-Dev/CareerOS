import sys
sys.stdout.reconfigure(encoding='utf-8')
sys.path.insert(0, 'd:/1 - Projects/Projects/CareerOS/CareerOS/apps/api')
from app.db.store import session_scope, list_entities

with session_scope() as db:
    runs = list_entities(db, 'aa_autopilot_run')
    r = runs[-1] if runs else {}
    print("LATEST RUN:", r.get("id"), "status:", r.get("status"), "currentJobId:", r.get("currentJobId"))
    print("ALL LOGS FOR RUN:")
    for l in r.get("logs", []):
        print(f"  [{l.get('timestamp')}] {l.get('level')}: {l.get('message')}")
    print("\nALL AUTOPILOT JOBS:")
    jobs = list_entities(db, 'aa_autopilot_job')
    for j in jobs:
        print(f"{j.get('id')} | {j.get('company')} | {j.get('title')} | status={j.get('status')} | lockedBy={j.get('lockedBy')} | lockExpires={j.get('lockExpiresAt')} | step={j.get('currentStep')}")
        if j.get('lastError'):
            print(f"   lastError: {j.get('lastError')}")
        if j.get('checkpointHistory'):
            print(f"   checkpoints: {[c.get('step') for c in j.get('checkpointHistory', [])]}")
