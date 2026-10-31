import sys
sys.path.insert(0, 'apps/api')

from app.db.store import session_scope
from app.services.application_assistant.persistence import get_autopilot_job, list_autopilot_jobs

with session_scope() as db:
    # Check the applying job
    job = get_autopilot_job(db, "apjob_9f32fbef-dd2b-401b-9ba0-cd0b97cece2d")
    if job:
        print(f"Job: {job.get('company')} - {job.get('title')}")
        print(f"Status: {job.get('status')}")
        print(f"ApplicationStartedAt: {job.get('applicationStartedAt')}")
        print(f"AttemptCount: {job.get('attemptCount')}")
        print(f"LastError: {job.get('lastError')}")
        print(f"LastErrorType: {job.get('lastErrorType')}")
        print(f"SubmissionEvidence: {job.get('submissionEvidence')}")
    else:
        print("Job not found")
    
    # Check all APPLYING jobs
    jobs = list_autopilot_jobs(db)
    applying = [j for j in jobs if j.get('status') == 'APPLYING']
    print(f"\nTotal APPLYING jobs: {len(applying)}")
    for j in applying:
        print(f"  {j.get('company')} - {j.get('title')} (started: {j.get('applicationStartedAt')})")