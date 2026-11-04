import json
from app.db.store import session_scope, list_entities, upsert_entity

with session_scope() as db:
    jobs = list_entities(db, "aa_autopilot_job")
    print(f"Total aa_autopilot_job entities: {len(jobs)}")
    for j in jobs[:5]:
        print(j.get("id"), j.get("company"), j.get("title"), j.get("status"))

    # Stage Stripe job directly into aa_autopilot_job
    stripe_job = {
        "id": "apjob_test_stripe_review_demo",
        "jobId": "job_stripe_demo",
        "company": "Stripe",
        "title": "Senior Full Stack Engineer - Infrastructure",
        "applicationUrl": "https://stripe.com/jobs/senior-full-stack",
        "status": "STAGED",
        "currentStep": "STAGED",
        "matchScore": 94,
        "aiExplanation": "Staged for human review: Custom screening questions require user confirmation.",
        "failureReason": "Screening questions require manual verification.",
        "unresolvedQuestions": [
            {
                "question": "What is your target base salary range?",
                "fieldKey": "salary_expectation",
                "suggestedAnswer": "$175,000 - $190,000"
            }
        ],
        "submissionEvidence": {
            "policyEvaluation": {
                "blockingIssues": [
                    {
                        "code": "MISSING_COMPENSATION_RANGE",
                        "label": "Expected Salary Confirmation",
                        "details": "Candidate expected salary range ($175,000 - $190,000) needs approval for submission."
                    }
                ],
                "warnings": [
                    "Hybrid schedule requires 2 days in SF or Remote approval."
                ]
            }
        }
    }
    upsert_entity(db, "aa_autopilot_job", stripe_job)
    print("Successfully upserted Stripe into aa_autopilot_job!")
