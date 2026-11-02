import asyncio
import json
import sqlite3
import sys
import os

# Add apps/api to path
sys.path.insert(0, os.path.abspath("apps/api"))

from app.services.application_assistant.resume_diff_service import generate_role_tailoring_diff

# Load profile from db
conn = sqlite3.connect("apps/api/data/career_os.db")
cursor = conn.cursor()
profile_row = cursor.execute("SELECT value FROM kv_store WHERE key='profile'").fetchone()
profile = json.loads(profile_row[0]) if profile_row else {}

# Test jobs
test_jobs = [
    {
        "id": "job_reddit",
        "company": "Reddit",
        "title": "Software Engineer",
        "description": "Build high-throughput distributed systems and backend infrastructure serving millions of daily active Redditors.",
    },
    {
        "id": "job_smartsheet",
        "company": "Smartsheet",
        "title": "Senior Software Engineer II - Applied AI",
        "description": "Design autonomous AI agent workflows, fine-tuned LLM inference pipelines, and vector database retrieval architectures.",
    },
    {
        "id": "job_segment",
        "company": "Segment",
        "title": "Senior Cloud Software Engineer",
        "description": "Scale cloud-native Kubernetes infrastructure, Terraform IaC automation, and distributed event streams handling trillions of events.",
    }
]

async def run_tests():
    print("=" * 75)
    print("TSENTA-STYLE RESUME RESTRUCTURING & REORGANIZING EVALUATION")
    print("=" * 75)

    for job in test_jobs:
        print(f"\n===========================================================================")
        print(f"TARGET ROLE: {job['title']} @ {job['company']}")
        print(f"===========================================================================")
        
        for mode in ["off", "honest", "aggressive"]:
            diff = await generate_role_tailoring_diff(job, profile, mode=mode)
            print(f"\n>>> MODE: {mode.upper()} <<<")
            print(f"Match Score: {diff['matchScore']}% | Total Bullet Changes: {diff['totalChanges']}")
            print(f"Cover Letter Hook: \"{diff['tailoredCoverLetter'].splitlines()[2]}\"")
            print(f"Screening Answer: \"{diff['screeningQAs'][0]['suggestedAnswer'][:120]}...\"")
            print("Tailored Bullets:")
            for idx, b in enumerate(diff['bulletDiffs'][:3]):
                print(f"  [{idx+1}] Modified: {b['isModified']}")
                if mode == "off":
                    print(f"      Exact: {b['tailored']}")
                else:
                    print(f"      Orig:  {b['original']}")
                    print(f"      Tail:  {b['tailored']}")

if __name__ == "__main__":
    asyncio.run(run_tests())
