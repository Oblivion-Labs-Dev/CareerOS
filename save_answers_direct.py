import sys
sys.path.insert(0, 'apps/api')

from app.db.store import session_scope, get_kv, set_kv
from app.services.application_assistant.answer_classification import normalize_field_key
from app.services.application_assistant.pending_question_groups import _clean_wording, _wording_pattern
import hashlib
import re

# Test the normalization
questions = [
    "Do you now or in the future require visa sponsorship to work in the US?",
    "Will you now or in the future require sponsorship for a US work visa?",
    "Are you legally authorized to work in the United States?",
    "How many years of professional software engineering experience do you have?",
    "Years of experience with Python, TypeScript, React, AWS, Kubernetes?",
    "Why do you want to work at [Company]?"
]

for q in questions:
    cleaned = _clean_wording(q)
    key = normalize_field_key(cleaned)
    pattern = _wording_pattern(cleaned)
    print(f"Q: {q}")
    print(f"  Cleaned: {cleaned}")
    print(f"  Key: {key}")
    print(f"  Pattern: {pattern}")
    print()

# Now manually save to profile
with session_scope() as db:
    profile = dict(get_kv(db, "profile") or {})
    entries = [dict(e) for e in profile.get("screeningAnswers") or [] if isinstance(e, dict)]
    
    print(f"Current profile entries: {len(entries)}")
    
    # Add our new answers manually
    new_entries = [
        {
            "id": "visa_sponsorship_us",
            "question": "Do you now or in the future require visa sponsorship to work in the US?",
            "answer": "Yes",
            "questionVariants": [
                "Do you now or in the future require visa sponsorship to work in the US?",
                "Will you now or in the future require sponsorship for a US work visa?",
                "Are you legally authorized to work in the United States?"
            ],
            "matchPatterns": [
                "require.*sponsor",
                "need.*sponsor",
                "visa\\s+sponsor",
                "authorized.*work.*united\\s+states",
                "eligible.*work.*us"
            ],
            "source": "user_approved"
        },
        {
            "id": "years_experience_total",
            "question": "How many years of professional software engineering experience do you have?",
            "answer": "8",
            "questionVariants": [
                "How many years of professional software engineering experience do you have?",
                "Years of professional software engineering experience",
                "Total years of experience",
                "Years of experience as a software engineer"
            ],
            "matchPatterns": [
                "years.*professional.*software.*engineer",
                "total.*years.*experience",
                "how\\s+many\\s+years.*experience"
            ],
            "source": "user_approved"
        },
        {
            "id": "years_experience_stack",
            "question": "Years of experience with Python, TypeScript, React, AWS, Kubernetes?",
            "answer": "6",
            "questionVariants": [
                "Years of experience with Python?",
                "Years of experience with TypeScript?",
                "Years of experience with React?",
                "Years of experience with AWS?",
                "Years of experience with Kubernetes?",
                "How many years of experience do you have with Python/TypeScript/React/AWS/Kubernetes?"
            ],
            "matchPatterns": [
                "years.*experience.*python",
                "years.*experience.*typescript",
                "years.*experience.*react",
                "years.*experience.*aws",
                "years.*experience.*kubernetes"
            ],
            "source": "user_approved"
        },
        {
            "id": "why_company_template",
            "question": "Why do you want to work at [Company]?",
            "answer": "What interests me about [Company] is the opportunity to build something meaningful and solve problems that aren't necessarily straightforward.\n\nI've always enjoyed taking something complicated, understanding why it's complicated in the first place, and finding a way to make it simpler. That's been a recurring theme throughout my time at Amazon and Microsoft, whether I was building systems at scale, improving how engineers work, or exploring what AI can make possible.\n\nOver time, I've realized that what matters most to me isn't a particular technology or industry. It's working with curious people, having the freedom to question assumptions, and building things that make the next problem easier to solve. That's the kind of work I'd love to continue at [Company].",
            "questionVariants": [
                "Why do you want to work at [Company]?",
                "Why are you interested in [Company]?",
                "What excites you about [Company]?",
                "Why [Company]?"
            ],
            "matchPatterns": [
                "why\\s+(?:do\\s+you\\s+)?want\\s+to\\s+work\\s+at",
                "why\\s+(?:are\\s+you\\s+)?interested\\s+in",
                "what\\s+excites\\s+you\\s+about",
                "^why\\s+\\w+\\?"
            ],
            "source": "user_approved"
        }
    ]
    
    # Merge with existing - replace if same ID exists
    existing_ids = {e.get('id') for e in entries}
    for ne in new_entries:
        if ne['id'] in existing_ids:
            # Update existing
            for i, e in enumerate(entries):
                if e.get('id') == ne['id']:
                    entries[i] = ne
                    break
        else:
            entries.append(ne)
    
    profile["screeningAnswers"] = entries
    set_kv(db, "profile", profile)
    print(f"Updated profile with {len(new_entries)} new/updated entries. Total: {len(entries)}")

# Verify
with session_scope() as db:
    profile = get_kv(db, "profile")
    answers = profile.get("screeningAnswers", [])
    print(f"\nVerified profile entries: {len(answers)}")
    for a in answers:
        q = a.get('question', '')
        if any(kw in q.lower() for kw in ['visa', 'sponsor', 'year', 'experience', 'why', 'company', 'stack', 'python', 'typescript', 'react', 'aws', 'kubernetes']):
            print(f"\n  Q: {q}")
            print(f"  A: {a.get('answer', '')[:150]}")
            print(f"  Variants: {a.get('questionVariants', [])}")
            print(f"  MatchPatterns: {a.get('matchPatterns', [])}")
            print(f"  ID: {a.get('id', 'none')}")