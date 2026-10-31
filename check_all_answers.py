import sys
sys.path.insert(0, 'apps/api')

from app.db.store import session_scope, get_kv, list_entities

with session_scope() as db:
    # Check profile screening answers
    profile = get_kv(db, "profile")
    answers = profile.get("screeningAnswers", [])
    
    # Search for our answers by content
    search_terms = ['visa', 'sponsor', 'year', 'experience', 'why', 'company', 'stack', 'python', 'typescript', 'react', 'aws', 'kubernetes']
    
    print("=== PROFILE ANSWERS MATCHING SEARCH ===")
    for a in answers:
        q = (a.get('question', '') or '').lower()
        if any(term in q for term in search_terms):
            print(f"\n  Q: {a.get('question', '')}")
            print(f"  A: {a.get('answer', '')[:200]}")
            print(f"  Variants: {a.get('questionVariants', [])}")
            print(f"  MatchPatterns: {a.get('matchPatterns', [])}")
            print(f"  Source: {a.get('source', 'unknown')}")
            print(f"  ID: {a.get('id', 'none')}")
    
    # Also check answer library for our new entries
    lib_answers = list_entities(db, "aa_answer_library")
    print(f"\n\n=== ANSWER LIBRARY MATCHING SEARCH ===")
    for a in lib_answers:
        q = (a.get('normalizedKey', '') or a.get('question', '') or '').lower()
        if any(term in q for term in search_terms):
            print(f"\n  Q: {a.get('normalizedKey', a.get('question', ''))}")
            print(f"  A: {a.get('value', '')[:200]}")
            print(f"  Variants: {a.get('questionVariants', [])}")
            print(f"  Source: {a.get('source', 'unknown')}")
            print(f"  ID: {a.get('id', 'none')}")