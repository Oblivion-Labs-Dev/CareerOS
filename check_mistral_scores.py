import sys
sys.path.insert(0, 'apps/api')

from app.db.store import session_scope
from app.services.application_assistant.persistence import list_autopilot_jobs

with session_scope() as db:
    jobs = list_autopilot_jobs(db)
    queued = [j for j in jobs if j.get('status') == 'QUEUED']
    
    print(f"QUEUED jobs: {len(queued)}")
    
    # Check for mistralMatch field
    with_mistral = 0
    without_mistral = 0
    for j in queued[:50]:
        mm = j.get('mistralMatch')
        if mm:
            with_mistral += 1
            score = mm.get('score', 0) if isinstance(mm, dict) else 0
            print(f"  {j.get('company')} - {j.get('title')}: keyword={j.get('matchScore', 0)}%, mistral={score}%")
        else:
            without_mistral += 1
    
    print(f"\nWith mistralMatch: {with_mistral}")
    print(f"Without mistralMatch: {without_mistral}")
    
    # Also check NEEDS_REVIEW jobs
    needs_review = [j for j in jobs if j.get('status') == 'NEEDS_REVIEW']
    print(f"\nNEEDS_REVIEW jobs: {len(needs_review)}")
    for j in needs_review[:10]:
        mm = j.get('mistralMatch')
        score = mm.get('score', 0) if isinstance(mm, dict) else 0
        print(f"  {j.get('company')} - {j.get('title')}: keyword={j.get('matchScore', 0)}%, mistral={score}%")