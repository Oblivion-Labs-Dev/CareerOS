import sys
sys.path.insert(0, 'apps/api')

from app.db.store import init_db, session_scope, get_kv, set_kv
from app.services.application_assistant.pending_question_groups import remember_answer_on_profile
import hashlib
import re
from app.services.application_assistant.answer_classification import normalize_field_key

# Initialize database
init_db()
print("Database initialized")

def save_answer(question: str, answer: str, variants: list[str] = None):
    """Save an answer to the profile's screeningAnswers."""
    with session_scope() as db:
        remember_answer_on_profile(db, question=question, answer=answer, variants=variants or [])
    print(f"Saved: {question[:80]}... -> {answer[:80]}")

# === VISA SPONSORSHIP (3 variants) ===
visa_q = "Do you now or in the future require visa sponsorship to work in the US?"
visa_variants = [
    "Do you now or in the future require visa sponsorship to work in the US?",
    "Will you now or in the future require sponsorship for a US work visa?",
    "Are you legally authorized to work in the United States?"
]
save_answer(visa_q, "Yes", visa_variants)

# === YEARS OF EXPERIENCE ===
yoe_q = "How many years of professional software engineering experience do you have?"
save_answer(yoe_q, "8", [
    "How many years of professional software engineering experience do you have?",
    "Years of professional software engineering experience",
    "Total years of experience"
])

# === STACK-SPECIFIC YEARS ===
stack_q = "Years of experience with Python, TypeScript, React, AWS, Kubernetes?"
save_answer(stack_q, "6", [
    "Years of experience with Python?",
    "Years of experience with TypeScript?",
    "Years of experience with React?",
    "Years of experience with AWS?",
    "Years of experience with Kubernetes?",
    "How many years of experience do you have with Python/TypeScript/React/AWS/Kubernetes?"
])

# === WHY [COMPANY] TEMPLATE ===
why_template = """What interests me about [Company] is the opportunity to build something meaningful and solve problems that aren't necessarily straightforward.

I've always enjoyed taking something complicated, understanding why it's complicated in the first place, and finding a way to make it simpler. That's been a recurring theme throughout my time at Amazon and Microsoft, whether I was building systems at scale, improving how engineers work, or exploring what AI can make possible.

Over time, I've realized that what matters most to me isn't a particular technology or industry. It's working with curious people, having the freedom to question assumptions, and building things that make the next problem easier to solve. That's the kind of work I'd love to continue at [Company]."""

# We'll save this as a template - the company name will need to be substituted per company
why_q = "Why do you want to work at [Company]?"
save_answer(why_q, why_template, [
    "Why do you want to work at [Company]?",
    "Why are you interested in [Company]?",
    "What excites you about [Company]?",
    "Why [Company]?"
])

print("\nAll answers saved to profile!")

# Verify
with session_scope() as db:
    profile = get_kv(db, "profile")
    answers = profile.get("screeningAnswers", [])
    print(f"\nTotal screening answers in profile: {len(answers)}")
    for a in answers:
        print(f"  Q: {a.get('question', '')[:80]}")
        print(f"  A: {a.get('answer', '')[:80]}")
        print(f"  Variants: {len(a.get('questionVariants', []))}")
        print()