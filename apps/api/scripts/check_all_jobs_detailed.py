import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app.db.store import session_scope
from app.services.application_assistant.persistence import list_autopilot_jobs, get_active_autopilot_run

with session_scope() as db:
    run = get_active_autopilot_run(db)
    print("=== ACTIVE RUN ===")
    if run:
        print("Run ID:", run.get("id"), "| Status:", run.get("status"))
        print(f"Processed: {run.get('processedCount')}, Submitted: {run.get('submittedCount')}, Staged: {run.get('stagedCount')}, Failed: {run.get('failedCount')}")
    else:
        print("No active run.")

    jobs = list_autopilot_jobs(db)
    print(f"\n=== ALL JOBS ({len(jobs)} total) ===")
    status_counts = {}
    for j in jobs:
        s = j.get("status")
        status_counts[s] = status_counts.get(s, 0) + 1

    print("Status counts:", status_counts)
    
    # Sort by updatedAt desc
    sorted_jobs = sorted(jobs, key=lambda x: x.get("updatedAt", "") or "", reverse=True)
    print("\nTop 25 most recently updated jobs:")
    for j in sorted_jobs[:25]:
        print(f"[{j.get('id')}] {j.get('company')} - {j.get('title')[:40]} | Status: {j.get('status')} | Updated: {j.get('updatedAt')} | Error: {j.get('lastError')}")
