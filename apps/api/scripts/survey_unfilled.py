import sys
sys.path.insert(0, ".")
import re
from app.db.store import init_db, session_scope
from app.services.application_assistant.persistence import list_autopilot_jobs
from app.services.application_assistant.question_classifier import classify_question

init_db()
with session_scope() as db:
    jobs = list_autopilot_jobs(db)

review_jobs = [j for j in jobs if j.get('status') in ('NEEDS_REVIEW', 'MANUAL_REVIEW')]
unfilled_counts = {}
for j in review_jobs:
    err = str(j.get('lastError') or '')
    m = re.search(r'Required fields remain unfilled in the browser:\s*(.*)', err)
    if m:
        for field in m.group(1).split(', '):
            field = field.strip()
            if field:
                unfilled_counts[field] = unfilled_counts.get(field, 0) + 1

print(f"Total review jobs: {len(review_jobs)}")
for f, count in sorted(unfilled_counts.items(), key=lambda x: -x[1]):
    print(f'{count}x: "{f}" -> {classify_question(f)}')
