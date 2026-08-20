import json
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app.db.store import session_scope
from app.services.application_assistant.persistence import list_autopilot_jobs, get_active_autopilot_run

def main():
    with session_scope() as db:
        run = get_active_autopilot_run(db)
        if run:
            print("Active Run ID:", run.get("id"))
            print("Status:", run.get("status"))
            print("Processed:", run.get("processedCount"), "Submitted:", run.get("submittedCount"), "Staged:", run.get("stagedCount"), "Failed:", run.get("failedCount"))
            print("\nRecent Logs:")
            for l in (run.get("logs") or [])[-20:]:
                print(f"[{l.get('level')}] {l.get('message')}")
        
        jobs = list_autopilot_jobs(db)
        print(f"\nTotal autopilot jobs: {len(jobs)}")
        for j in jobs:
            print(f"Job [{j.get('id')}] {j.get('company')} - {j.get('title')} | Status: {j.get('status')} | Error: {j.get('lastError')} | ErrorType: {j.get('lastErrorType')}")

if __name__ == "__main__":
    main()
