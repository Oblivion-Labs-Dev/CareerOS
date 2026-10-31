import sys
sys.path.insert(0, 'apps/api')

from app.db.store import session_scope
from app.services.application_assistant.persistence import list_autopilot_jobs
from app.services.application_assistant.autopilot_runner import AutopilotRunner
import asyncio

with session_scope() as db:
    jobs = list_autopilot_jobs(db)
    
    # Count by status
    from collections import Counter
    status_counts = Counter(j.get('status') for j in jobs)
    print("Job status counts:")
    for status, count in status_counts.most_common():
        print(f"  {status}: {count}")
    
    # Queued jobs
    queued = [j for j in jobs if j.get('status') == 'QUEUED']
    print(f"\nQUEUED jobs: {len(queued)}")
    if queued:
        print("Top 10 queued:")
        for j in queued[:10]:
            print(f"  {j.get('company')} - {j.get('title')} (match: {j.get('matchScore', 0)}%)")

# Check autopilot runner status
runner = AutopilotRunner.get_instance()
print(f"\nAutopilot runner active_run_id: {runner.active_run_id}")
print(f"Runner priority_job_ids: {runner.priority_job_ids}")
print(f"Runner manual_apply_job_ids: {runner.manual_apply_job_ids}")