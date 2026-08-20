import sys
sys.stdout.reconfigure(encoding='utf-8')
sys.path.insert(0, 'd:/1 - Projects/Projects/CareerOS/CareerOS/apps/api')
from app.db.store import session_scope, list_entities

with session_scope() as db:
    jobs = list_entities(db, 'aa_autopilot_job')
    for j in jobs:
        print("JOB:", j)
