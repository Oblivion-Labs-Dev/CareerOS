import sys
sys.path.insert(0, 'apps/api')

from app.db.store import session_scope, get_kv

with session_scope() as db:
    profile = get_kv(db, "profile")
    answers = profile.get("screeningAnswers", [])
    
    # Search for our specific answers
    search_terms = ["visa", "sponsor", "years", "experience", "why", "company", "python", "typescript", "react", "aws", "kubernetes"]
    
    print(f"Total screening answers: {len(answers)}")
    print("\n=== RELEVANT ANSWERS ===")
    for a in answers:
        q = a.get('question', '').lower()
        if any(term in q for term in search_terms):
            print(f"\nQ: {a.get('question', '')}")
            print(f"A: {a.get('answer', '')[:200]}")
            print(f"Variants: {a.get('questionVariants', [])}")
            print(f"Source: {a.get('source', 'unknown')}")