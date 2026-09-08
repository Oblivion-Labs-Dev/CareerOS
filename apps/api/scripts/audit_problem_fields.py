"""Detailed audit of the last 20 submitted apps - focused on problem fields."""
import sys, json, io
from pathlib import Path
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app.db.store import session_scope
from app.services.application_assistant.persistence import list_autopilot_jobs

# Fields to specifically check
PROBLEM_FIELDS = [
    "Location", "Location (City)", "city", "state",
    "Race", "Ethnicity", "Hispanic",
    "sponsor", "authorization", "authorized",
    "State", "Province", "reside",
    "Gender", "Veteran", "Disability",
]

with session_scope() as db:
    jobs = list_autopilot_jobs(db)
    submitted = [j for j in jobs if j.get("status") == "SUBMITTED"]
    submitted.sort(key=lambda j: j.get("submittedAt") or j.get("updatedAt") or "", reverse=True)

    for idx, job in enumerate(submitted[:20]):
        company = job.get("company", "?")
        title = job.get("title", "?")
        answers = job.get("answers") or {}
        
        print(f"\n--- #{idx+1} [{company}] {title} ---")
        
        # Show ALL answers for each job, highlighting problem fields
        if isinstance(answers, dict):
            for q, a in sorted(answers.items()):
                q_lower = q.lower()
                is_problem = any(pf.lower() in q_lower for pf in PROBLEM_FIELDS)
                marker = " <<<" if is_problem else ""
                print(f"  {q}: {a}{marker}")
        else:
            print("  (no answers stored)")
