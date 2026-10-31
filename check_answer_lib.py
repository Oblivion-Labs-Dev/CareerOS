import sys
sys.path.insert(0, 'apps/api')

from app.db.store import session_scope, get_kv, list_entities

with session_scope() as db:
    # Check answer library entities
    answers = list_entities(db, "aa_answer_library")
    print(f"Answer library entries: {len(answers)}")
    
    for a in answers:
        q = a.get('question', '') or a.get('normalizedKey', '')
        if any(keyword in q.lower() for keyword in ['visa', 'sponsor', 'year', 'experience', 'why', 'company', 'python', 'typescript', 'react', 'aws', 'kubernetes', 'authorized', 'stack']):
            print(f"\n  Q: {q}")
            print(f"  A: {a.get('value', '')[:200]}")
            print(f"  Variants: {a.get('questionVariants', [])}")
            print(f"  Source: {a.get('source', 'unknown')}")
            print(f"  ID: {a.get('id', 'none')}")