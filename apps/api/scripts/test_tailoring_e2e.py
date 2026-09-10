import asyncio
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app.services.application_assistant.resume_diff_service import generate_role_tailoring_diff
from app.db.store import session_scope, get_kv

async def main():
    with session_scope() as db:
        profile = get_kv(db, "profile") or {}
        master_resume = get_kv(db, "resume_corpus_master") or {}
    
    test_job = {
        "id": "test_job_1",
        "company": "Robinhood",
        "title": "Senior Software Engineer, Security Platform",
        "location": "Bellevue, WA",
        "matchScore": 88.0,
        "description": "Robinhood is seeking a Senior Software Engineer for our Security Platform team in Bellevue, WA. Requirements: 5+ years experience in distributed systems, Python, Go, Kubernetes, cloud security, infrastructure."
    }
    
    print("Testing generate_role_tailoring_diff...")
    diff = await generate_role_tailoring_diff(test_job, profile, master_resume, mode="honest")
    print("Match score:", diff.get("matchScore"))
    print("Tailoring failed:", diff.get("tailoringFailed"))
    print("Total changes:", diff.get("totalChanges"))
    bullet_diffs = diff.get("bulletDiffs", [])
    print("Number of bullet diffs:", len(bullet_diffs))
    for b in bullet_diffs[:2]:
        print("  - [modified={}] {}".format(b.get("isModified"), b.get("tailored", "")[:100]))

if __name__ == "__main__":
    asyncio.run(main())
