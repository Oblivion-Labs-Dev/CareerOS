import sys
sys.path.insert(0, 'apps/api')

from app.db.store import session_scope, get_kv

with session_scope() as db:
    profile = get_kv(db, "profile")
    answers = profile.get("screeningAnswers", [])
    
    # Write to file to avoid Unicode issues
    with open('verify_output.txt', 'w', encoding='utf-8') as f:
        f.write(f"Total profile entries: {len(answers)}\n\n")
        for a in answers:
            q = a.get('question', '')
            if any(kw in q.lower() for kw in ['visa', 'sponsor', 'year', 'experience', 'why', 'company', 'stack', 'python', 'typescript', 'react', 'aws', 'kubernetes']):
                f.write(f"\n  Q: {q}\n")
                f.write(f"  A: {a.get('answer', '')[:200]}\n")
                f.write(f"  Variants: {a.get('questionVariants', [])}\n")
                f.write(f"  MatchPatterns: {a.get('matchPatterns', [])}\n")
                f.write(f"  ID: {a.get('id', 'none')}\n")
    
    print("Output written to verify_output.txt")