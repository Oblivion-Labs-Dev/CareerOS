import sys
sys.stdout.reconfigure(encoding='utf-8')
sys.path.insert(0, 'd:/1 - Projects/Projects/CareerOS/CareerOS/apps/api')
from app.db.store import session_scope, list_entities, get_kv
from app.services.application_assistant.persistence import list_discovered_jobs, list_autopilot_jobs
from app.services.application_assistant.job_filter_ranker import filter_and_rank_jobs, evaluate_hard_filters
from app.services.application_assistant.qwen_job_match import evaluate_job_match

with session_scope() as db:
    profile = get_kv(db, "profile") or {}
    raw_jobs = list_discovered_jobs(db, active_only=True, exclude_demo=True)
    existing_jobs = list_autopilot_jobs(db)
    print(f"Profile title: {profile.get('targetTitle')}, skills: {profile.get('skills')}")
    print(f"Total raw jobs: {len(raw_jobs)}")
    
    passed_hard = 0
    scores = []
    for j in raw_jobs[:50]:
        p, reason = evaluate_hard_filters(j, profile, existing_jobs)
        if p:
            passed_hard += 1
            res = evaluate_job_match(j, profile)
            scores.append((j.get('title'), j.get('company'), res.get('overallScore')))
    print(f"Passed hard filters (out of 50): {passed_hard}")
    print("Sample scores:")
    for s in scores[:10]:
        print(" ", s)
