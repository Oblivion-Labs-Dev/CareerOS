"""Summarize ONLY the problem fields across last 20 submitted apps."""
import sys, io
from pathlib import Path
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app.db.store import session_scope
from app.services.application_assistant.persistence import list_autopilot_jobs

# Known wrong answers to flag
WRONG_VALUES = {
    "state_wrong": ["delaware", "illinois", "il", "de"],
    "location_wrong": ["karnataka", "india", "akshaya nagara"],
    "race_wrong": ["american indian", "alaskan native", "native american"],
    "sponsorship_wrong_no": False,  # sponsorship should be Yes
    "other_links_wrong": ["yes, extensive"],  # "Other Links" getting a cover-letter-style answer instead of a URL
    "citizenship_wrong": False,  # EU citizenship "No" used for actual citizenship question
}

with session_scope() as db:
    jobs = list_autopilot_jobs(db)
    submitted = [j for j in jobs if j.get("status") == "SUBMITTED"]
    submitted.sort(key=lambda j: j.get("submittedAt") or j.get("updatedAt") or "", reverse=True)

    issues = []
    for idx, job in enumerate(submitted[:20]):
        company = job.get("company", "?")
        title = job.get("title", "?")
        answers = job.get("answers") or {}
        job_issues = []

        if not isinstance(answers, dict):
            continue

        for q, a in answers.items():
            q_lower = q.lower()
            a_lower = str(a).lower().strip()

            # 1. State/Province answered wrong
            if ("state" in q_lower or "province" in q_lower or "reside" in q_lower) and a_lower in WRONG_VALUES["state_wrong"]:
                job_issues.append(f"  WRONG STATE: '{q}' = '{a}' (should be Washington)")

            # 2. Location contains India
            if ("location" in q_lower or "city" in q_lower) and any(w in a_lower for w in WRONG_VALUES["location_wrong"]):
                job_issues.append(f"  WRONG LOCATION: '{q}' = '{a}' (should be Seattle, WA)")

            # 3. Race/Ethnicity wrong
            if ("race" in q_lower or "ethnicity" in q_lower) and any(w in a_lower for w in WRONG_VALUES["race_wrong"]):
                job_issues.append(f"  WRONG RACE: '{q}' = '{a}' (should be Asian)")

            # 4. "Other Links" getting a text answer instead of URL
            if "other links" in q_lower and any(w in a_lower for w in WRONG_VALUES["other_links_wrong"]):
                job_issues.append(f"  WRONG OTHER LINKS: '{q}' = '{a}' (should be a URL or empty)")

            # 5. Citizenship question answered as just "No" when it asks for citizenship country
            if "citizenship" in q_lower and "what is" in q_lower and a_lower == "no":
                job_issues.append(f"  WRONG CITIZENSHIP: '{q}' = '{a}' (should be 'India' or similar)")

            # 6. Sponsorship answered "No" when should be "Yes"
            if ("sponsor" in q_lower) and a_lower == "no":
                job_issues.append(f"  WRONG SPONSORSHIP: '{q}' = '{a}' (should be Yes)")

            # 7. GitLab sponsorship with Netherlands visa
            if "sponsor" in q_lower and "netherlands" in a_lower:
                job_issues.append(f"  WRONG SPONSORSHIP DETAIL: '{q}' = '{a}' (should just be 'Yes')")

        if job_issues:
            issues.append((idx+1, company, title, job_issues))

    print(f"=== FIELD ISSUES FOUND IN LAST 20 SUBMITTED APPS ===\n")
    if not issues:
        print("No issues found!")
    else:
        for num, comp, title, job_issues in issues:
            print(f"#{num} [{comp}] {title}")
            for iss in job_issues:
                print(f"  {iss}")
            print()
        print(f"\nTotal apps with issues: {len(issues)} / 20")
        
        # Summary of issue types
        all_iss = [iss for _, _, _, jis in issues for iss in jis]
        print(f"\nIssue breakdown:")
        for prefix in ["WRONG STATE", "WRONG LOCATION", "WRONG RACE", "WRONG OTHER LINKS", "WRONG CITIZENSHIP", "WRONG SPONSORSHIP"]:
            count = sum(1 for i in all_iss if i.strip().startswith(prefix))
            if count:
                print(f"  {prefix}: {count} occurrences")
