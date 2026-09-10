import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app.services.application_assistant.question_classifier import classify_question
from app.services.application_assistant.profile_answer_resolver import resolve_answer

q = "Have you ever worked for Robinhood as an employee, intern or contractor? Note that providing false or misleading information may result in disqualification from the hiring process.*"
opts = ["--", "Yes", "No"]

qtype = classify_question(q, options=opts)
print("Classified QType:", qtype)

profile = {"firstName": "Akshay", "lastName": "Borse"}
res = resolve_answer(q, qtype, profile, options=opts)
print("Resolution answer:", res.answer)
print("Resolution confidence:", res.confidence)
print("Resolution method:", res.resolution_method)
