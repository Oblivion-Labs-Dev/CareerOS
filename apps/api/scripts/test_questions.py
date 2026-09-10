import sys
sys.path.insert(0, '.')
from app.services.application_assistant.question_classifier import classify_question
from app.services.application_assistant.profile_answer_resolver import resolve_answer

questions = [
    ("Are you currently authorized to work in the country outlined for this job (e.g. H-1B status)?*", ["Yes", "No"]),
    ("Are you currently eligible to legally work in the United States? *", ["Yes", "No"]),
    ("Are you over 18 years of age?*", ["Yes", "No"]),
    ("Have you ever worked for Robinhood as an employee, intern or contractor? Note that providing false or misleading information may result in disqualification from the hiring process.*", ["Yes", "No"]),
    ("What is your preferred office location?*", ["Bellevue, WA", "Menlo Park, CA", "New York, NY"])
]

profile = {
    "workAuth": {"authorizedToWorkInUS": True, "requiresSponsorshipNowOrFuture": False},
    "city": "Seattle",
    "state": "Washington"
}

for q, opts in questions:
    cls = classify_question(q, "", opts)
    ans = resolve_answer(q, profile, opts)
    print(f"Q: {q}")
    print(f"  Classification: {cls.value}")
    print(f"  Resolved Answer: {ans.answer} (method: {ans.resolution_method})")

