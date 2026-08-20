import sys
sys.stdout.reconfigure(encoding='utf-8')
sys.path.insert(0, 'd:/1 - Projects/Projects/CareerOS/CareerOS/apps/api')
from app.db.store import session_scope, list_entities, delete_entity, upsert_entity

with session_scope() as db:
    jobs = list_entities(db, 'aa_autopilot_job')
    print("CURRENT AUTOPILOT JOBS:", len(jobs))
    dummy_count = 0
    for j in jobs:
        url = j.get('applicationUrl') or ''
        company = j.get('company') or ''
        if 'run_id=' in url or 'Batch #' in company or 'job_workato_ai' in j.get('jobId', '') or 'job_databricks_swe' in j.get('jobId', ''):
            print(f"  Deleting dummy/test job: {j.get('id')} - {company} ({url})")
            delete_entity(db, 'aa_autopilot_job', j['id'])
            dummy_count += 1
    print(f"Deleted {dummy_count} corrupted dummy jobs.")
    
    # Check runs
    runs = list_entities(db, 'aa_autopilot_run')
    for r in runs:
        if r.get('status') in ('RUNNING', 'RECOVERING'):
            print(f"Resetting stuck run {r.get('id')} to STOPPED")
            r['status'] = 'STOPPED'
            upsert_entity(db, 'aa_autopilot_run', r)
