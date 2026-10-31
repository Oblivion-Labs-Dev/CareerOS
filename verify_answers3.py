import sys
sys.path.insert(0, 'apps/api')

from app.db.store import session_scope, get_kv

with session_scope() as db:
    profile = get_kv(db, "profile")
    answers = profile.get("screeningAnswers", [])
    
    # Print ALL answers to find ours
    for i, a in enumerate(answers):
        q = a.get('question', '')
        aid = a.get('id', '')
        if 'review_' in aid or 'year' in q.lower() or 'experience' in q.lower() or 'why' in q.lower() or 'company' in q.lower() or 'stack' in q.lower():
            print(f"\n[{i}] ID: {aid}")
            print(f"    Q: {q}")
            print(f"    A: {a.get('answer', '')[:300]}")
            print(f"    Variants: {a.get('questionVariants', [])}")
            print(f"    MatchPatterns: {a.get('matchPatterns', [])}")
            print(f"    Source: {a.get('source', 'unknown')}")