import sys
sys.path.insert(0, 'apps/api')

from app.db.store import session_scope, get_kv

with session_scope() as db:
    profile = get_kv(db, "profile")
    answers = profile.get("screeningAnswers", [])
    
    # Print all answers with their full details
    for i, a in enumerate(answers):
        q = a.get('question', '')
        # Check for our specific questions
        if any(keyword in q.lower() for keyword in ['visa', 'sponsor', 'year', 'experience', 'why', 'company', 'python', 'typescript', 'react', 'aws', 'kubernetes', 'authorized']):
            print(f"\n[{i}] Q: {q}")
            print(f"    A: {a.get('answer', '')[:200]}")
            print(f"    Variants: {a.get('questionVariants', [])}")
            print(f"    MatchPatterns: {a.get('matchPatterns', [])}")
            print(f"    Source: {a.get('source', 'unknown')}")
            print(f"    ID: {a.get('id', 'none')}")