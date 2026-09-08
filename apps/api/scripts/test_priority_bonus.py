import sys
from pathlib import Path
sys.path.insert(0, str(Path("CareerOS/apps/api").resolve()))
from app.services.application_assistant.job_filter_ranker import role_location_priority_bonus

sample_jobs = [
    {"title": "Senior Software Engineer", "location": "Seattle, WA"},
    {"title": "Senior Backend Engineer", "location": "Remote, US"},
    {"title": "Staff Software Engineer", "location": "Bellevue, WA"},
    {"title": "Principal Software Engineer", "location": "Remote, United States"},
    {"title": "Software Engineer II", "location": "Seattle, WA"},
    {"title": "Software Engineer II", "location": "Remote, US"},
    {"title": "Product Manager", "location": "Remote, US"},
]

print("=== PRIORITY SCORES ===")
for j in sample_jobs:
    bonus = role_location_priority_bonus(j)
    print(f"{bonus:>5.1f} pts | {j['title']} ({j['location']})")

sorted_jobs = sorted(sample_jobs, key=lambda j: role_location_priority_bonus(j), reverse=True)
print("\n=== SORTED QUEUE ORDER ===")
for idx, j in enumerate(sorted_jobs, 1):
    print(f"{idx}. {j['title']} - {j['location']} (+{role_location_priority_bonus(j)} pts)")
