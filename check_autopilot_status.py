import sys
sys.path.insert(0, 'apps/api')

from app.db.store import session_scope
from app.services.application_assistant.autopilot_runner import AutopilotRunner
from app.services.application_assistant.persistence import get_autopilot_run, list_autopilot_jobs

with session_scope() as db:
    runner = AutopilotRunner.get_instance()
    print(f"Runner active_run_id: {runner.active_run_id}")
    
    # Get run status
    if runner.active_run_id:
        run = get_autopilot_run(db, runner.active_run_id)
        if run:
            print(f"Run status: {run.get('status')}")
            print(f"Target: {run.get('targetProcessCount')}")
            print(f"Processed: {run.get('processedCount')}")
            print(f"Submitted: {run.get('submittedCount')}")
            print(f"Staged: {run.get('stagedCount')}")
            print(f"Skipped: {run.get('skippedCount')}")
            print(f"Failed: {run.get('failedCount')}")
            print(f"Ineligible: {run.get('ineligibleCount')}")
            print(f"Settings: {run.get('settings')}")
    
    # Check queue
    jobs = list_autopilot_jobs(db)
    queued = [j for j in jobs if j.get('status') == 'QUEUED']
    applying = [j for j in jobs if j.get('status') == 'APPLYING']
    print(f"\nQUEUED: {len(queued)}")
    print(f"APPLYING: {len(applying)}")
    
    if applying:
        for j in applying:
            print(f"  Applying: {j.get('company')} - {j.get('title')}")
    
    # Check recent submissions
    submitted = [j for j in jobs if j.get('status') == 'SUBMITTED']
    print(f"\nSUBMITTED total: {len(submitted)}")
    if submitted:
        print("Recent submissions:")
        for j in submitted[-5:]:
            print(f"  {j.get('company')} - {j.get('title')} - {j.get('submittedAt')}")
    
    # Check MANUAL_REVIEW from this run
    manual_review = [j for j in jobs if j.get('status') == 'MANUAL_REVIEW']
    print(f"\nMANUAL_REVIEW total: {len(manual_review)}")
    
    # Check NEEDS_REVIEW
    needs_review = [j for j in jobs if j.get('status') == 'NEEDS_REVIEW']
    print(f"NEEDS_REVIEW total: {len(needs_review)}")