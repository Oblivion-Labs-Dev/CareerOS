"""Audit the last 20 submitted applications for field correctness."""
import sys, json, io
from pathlib import Path
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app.db.store import session_scope, get_kv
from app.services.application_assistant.persistence import list_autopilot_jobs

# Expected correct values
EXPECTED = {
    "firstName": "Akshay",
    "lastName": "Borse",
    "email_contains": "amsborse",
    "location": "Seattle",
    "city": "Seattle",
    "state": "Washington",
    "raceEthnicity_correct": ["asian", "asian (not hispanic or latino)", "asian (including south asian, east asian, or southeast asian)"],
    "raceEthnicity_wrong": ["american indian", "alaskan native", "native american"],
    "hispanic_correct": ["no", "not hispanic", "non hispanic"],
    "sponsorship": "yes",
    "workAuthorization": "yes",
    "veteran_correct": ["not a protected veteran", "i am not a protected veteran", "no"],
    "location_wrong": ["karnataka", "india", "akshaya nagara", "illinois"],
    "state_wrong": ["illinois", "il"],
}

with session_scope() as db:
    jobs = list_autopilot_jobs(db)
    submitted = [j for j in jobs if j.get("status") == "SUBMITTED"]
    submitted.sort(key=lambda j: j.get("submittedAt") or j.get("updatedAt") or "", reverse=True)
    
    last_20 = submitted[:20]
    print(f"Auditing {len(last_20)} most recent SUBMITTED applications\n")
    print("=" * 100)
    
    issues_found = 0
    clean_count = 0
    
    for idx, job in enumerate(last_20):
        job_id = job.get("id", "?")
        company = job.get("company", "?")
        title = job.get("title", "?")
        submitted_at = job.get("submittedAt") or job.get("updatedAt") or "?"
        
        # Get filled fields from the job's submission record
        filled = job.get("filledFields") or job.get("submissionFields") or {}
        answers = job.get("answers") or job.get("submissionAnswers") or {}
        checkpoint = job.get("checkpoint") or {}
        metadata = job.get("metadata") or {}
        raw_answers = job.get("rawAnswers") or {}
        
        # Collect all field data from various locations
        all_fields = {}
        for source_name, source in [("filledFields", filled), ("answers", answers), 
                                      ("checkpoint", checkpoint), ("metadata", metadata),
                                      ("rawAnswers", raw_answers)]:
            if isinstance(source, dict):
                for k, v in source.items():
                    if v and str(v).strip():
                        all_fields[f"{source_name}.{k}"] = v
        
        print(f"\n#{idx+1} [{company}] {title}")
        print(f"   ID: {job_id} | Submitted: {submitted_at}")
        
        job_issues = []
        
        # Check all stored field values for known problems
        for field_path, value in all_fields.items():
            val_lower = str(value).lower()
            
            # Check for wrong location
            for wrong in EXPECTED["location_wrong"]:
                if wrong in val_lower:
                    job_issues.append(f"  ❌ WRONG LOCATION: {field_path} = '{value}'")
                    break
            
            # Check for wrong race/ethnicity
            for wrong in EXPECTED["raceEthnicity_wrong"]:
                if wrong in val_lower:
                    job_issues.append(f"  ❌ WRONG RACE: {field_path} = '{value}' (should be Asian)")
                    break
            
            # Check for wrong state
            for wrong in EXPECTED["state_wrong"]:
                if val_lower.strip() == wrong:
                    job_issues.append(f"  ❌ WRONG STATE: {field_path} = '{value}' (should be Washington)")
                    break
        
        if job_issues:
            issues_found += 1
            for issue in job_issues:
                print(issue)
        else:
            clean_count += 1
            print("   ✅ No known field issues detected in stored data")
        
        # Print all stored fields for inspection
        if all_fields:
            print(f"   📋 Stored fields ({len(all_fields)}):")
            for fp, fv in sorted(all_fields.items()):
                print(f"      {fp}: {fv}")
        else:
            print("   ⚠️  No field data stored in job record")
    
    print("\n" + "=" * 100)
    print(f"\nAUDIT SUMMARY:")
    print(f"  Total audited: {len(last_20)}")
    print(f"  Clean: {clean_count}")
    print(f"  Issues found: {issues_found}")
