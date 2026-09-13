import asyncio
from app.services.application_assistant.question_classifier import classify_question, QuestionType
from app.services.application_assistant.profile_answer_resolver import resolve_answer

questions = [
    ("Have you previously applied to a role at EarnIn?*", ["Yes", "No"]),
    ("The interview may be recorded in various formats, including audio, video, and/or transcript, and reviewed by EarnIn’s hiring team for internal evaluation purposes only. These recordings will not be shared outside the company and will be securely stored and deleted in accordance with EarnIn’s Records Retention Policy.*", ["Yes", "No"]),
    ("Do you have experience writing code that is reliable, durable, and easily maintained?*", ["Yes", "No"]),
    ("Do you have at least 6 months of experience using AI-assisted development tools (e.g., GitHub Copilot, Cursor, ChatGPT, or similar tools) as part of your software development workflow?*", ["Yes", "No"]),
    ("Do you have experience coordinating cross-functionally with product, design, QA, analytics, security, and TPM stakeholders throughout the software development lifecycle? *", ["Yes", "No"]),
]

profile = {
    "firstName": "Akshay",
    "lastName": "Borse",
    "currentCompany": "Microsoft",
    "workExperience": [{"company": "Microsoft", "title": "Senior Software Engineer"}],
}

print("=== VERIFYING RESOLVER ON PREVIOUSLY FAILING QUESTIONS ===")
all_pass = True
for q, opts in questions:
    q_type = classify_question(q)
    res = resolve_answer(question_text=q, profile=profile, options=opts)
    print(f"\nQuestion: {q[:70]}...")
    print(f"  Classified: {q_type.value}")
    print(f"  Answer: {res.answer}")
    print(f"  Confidence: {res.confidence}")
    print(f"  Method: {res.resolution_method}")
    print(f"  Blocking Errors: {res.blocking_errors}")
    if not res.answer or res.blocking_errors or res.confidence < 0.9:
        all_pass = False

print("\nALL RESOLVED DETERMINISTICALLY:", all_pass)
