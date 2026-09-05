"""Autonomous Multi-Company Application Runner with Interactive Question Resolution & Self-Healing."""

import asyncio
import json
import logging
import os
import sys
import sqlite3
from pathlib import Path
from typing import Any

# Ensure apps/api is in python path
repo_root = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(repo_root / "apps" / "api"))
sys.stdout.reconfigure(line_buffering=True)
sys.stderr.reconfigure(line_buffering=True)

from dotenv import load_dotenv
load_dotenv(repo_root / "apps" / "api" / ".env")

from app.db.store import session_scope, get_kv, set_kv, upsert_entity, new_id, now_iso
from app.services.application_assistant.persistence import list_answer_library, upsert_answer
from app.services.application_assistant.playwright_autopilot_executor import execute_live_playwright_submission

logging.basicConfig(level=logging.INFO, format="[%(levelname)s] %(asctime)s - %(name)s - %(message)s")
logger = logging.getLogger("autonomous_batch")

JOBS_TO_TEST = [
    {
        "id": "job_reddit_8082867",
        "company": "Reddit",
        "title": "Software Engineer",
        "applicationUrl": "https://job-boards.greenhouse.io/reddit/jobs/8082867",
    },
    {
        "id": "job_spacex_8650986002",
        "company": "SpaceX",
        "title": "Sr. Full Stack Engineer (Application Software)",
        "applicationUrl": "https://boards.greenhouse.io/spacex/jobs/8650986002?gh_jid=8650986002",
    },
    {
        "id": "job_gitlab_8615319002",
        "company": "GitLab",
        "title": "Senior Backend Engineer - Monitoring and Anomaly Detection (Monetization)",
        "applicationUrl": "https://job-boards.greenhouse.io/gitlab/jobs/8615319002",
    },
    {
        "id": "job_smartsheet_8007934",
        "company": "Smartsheet",
        "title": "Software Engineer II - App Core (Remote Eligible)",
        "applicationUrl": "https://job-boards.greenhouse.io/smartsheet/jobs/8007934",
    },
    {
        "id": "job_affirm_7806924003",
        "company": "Affirm",
        "title": "Senior Software Engineer, Backend (ML Feature Platform)",
        "applicationUrl": "https://job-boards.greenhouse.io/affirm/jobs/7806924003",
    },
    {
        "id": "job_mixpanel_8064216",
        "company": "Mixpanel",
        "title": "Software Engineer, AI Platform",
        "applicationUrl": "https://job-boards.greenhouse.io/mixpanel/jobs/8064216",
    },
    {
        "id": "job_segment_8071710",
        "company": "Segment",
        "title": "Staff Software Engineer",
        "applicationUrl": "https://job-boards.greenhouse.io/twilio/jobs/8071710",
    },
    {
        "id": "job_grafana_6123193004",
        "company": "Grafana Labs",
        "title": "Senior Backend Engineer - Databases - Loki Query | UK | Remote",
        "applicationUrl": "https://job-boards.greenhouse.io/grafanalabs/jobs/6123193004",
    },
    {
        "id": "job_temporal_5133728007",
        "company": "Temporal",
        "title": "Senior Software Engineer, Compute (Temporal Cloud)",
        "applicationUrl": "https://job-boards.greenhouse.io/temporaltechnologies/jobs/5133728007",
    },
    {
        "id": "job_vercel_5428982004",
        "company": "Vercel",
        "title": "Software Engineer, Observability",
        "applicationUrl": "https://job-boards.greenhouse.io/vercel/jobs/5428982004",
    },
]


def load_candidate_profile() -> dict[str, Any]:
    with session_scope() as db:
        prof = get_kv(db, "profile") or {}
        # Make sure full details are present
        prof.setdefault("firstName", "Akshay")
        prof.setdefault("lastName", "Borse")
        prof.setdefault("fullName", "Akshay Borse")
        prof["email"] = "amsborse+careeros@gmail.com"
        prof["location"] = "Auburn, WA"
        prof.setdefault("city", "Auburn")
        prof.setdefault("state", "Washington")
        prof.setdefault("postalCode", "98092")
        prof.setdefault("linkedin", "https://www.linkedin.com/in/amsborse/")
        prof.setdefault("github", "https://github.com/amsborse")
        prof.setdefault("portfolio", "https://amsborse.github.io/resume")
        prof.setdefault("currentCompany", "Microsoft")
        prof.setdefault("currentTitle", "Senior Software Engineer")
        prof.setdefault("yearsExperience", 8)
        prof.setdefault("workAuthorization", "Yes")
        prof.setdefault("sponsorship", "Yes")
        prof.setdefault("gender", "Man")
        prof.setdefault("raceEthnicity", "South Asian")
        prof.setdefault("hispanic", "No")
        prof.setdefault("veteran", "I am not a protected veteran")
        prof.setdefault("disability", "No, I don't have a disability")
        prof.setdefault("sexualOrientation", "Heterosexual")
        prof.setdefault("transgender", "No")
        prof.setdefault("pronouns", "He/him")
        prof.setdefault("workAuth", {
            "authorizedToWorkInUS": True,
            "authorizationType": "H-1B",
            "requiresSponsorshipNowOrFuture": True,
            "permanentWorkAuthorization": False,
            "usCitizen": False,
            "usNational": False,
            "greenCardHolder": False,
        })
        prof.setdefault("security", {
            "hasHeldUSSecurityClearance": False,
            "eligibleForUSSecurityClearance": False,
        })
        return prof


def load_answer_library() -> list[dict[str, Any]]:
    with session_scope() as db:
        return list_answer_library(db)


async def run_single_job(job: dict[str, Any], profile: dict[str, Any], answer_lib: list[dict[str, Any]]) -> dict[str, Any]:
    logger.info(f"=== Starting Autonomous Run for [{job['company']}] {job['title']} ===")
    
    logs = []
    def log_cb(msg: str, lvl: str = "info"):
        logs.append(f"[{lvl.upper()}] {msg}")
        logger.info(f"[{job['company']}] {msg}")

    result = await execute_live_playwright_submission(
        job_item=job,
        profile=profile,
        answer_lib=answer_lib,
        headless=True,
        timeout_sec=150.0,
        log_callback=log_cb,
    )
    result["logs"] = logs
    return result


async def main():
    target_idx = int(sys.argv[1]) if len(sys.argv) > 1 else None
    
    profile = load_candidate_profile()
    answer_lib = load_answer_library()
    
    jobs = [JOBS_TO_TEST[target_idx]] if target_idx is not None else JOBS_TO_TEST
    
    results = {}
    for i, job in enumerate(jobs):
        logger.info(f"\n[{i+1}/{len(jobs)}] Processing {job['company']}...")
        res = await run_single_job(job, profile, answer_lib)
        results[job["company"]] = {
            "submitted": res.get("submitted", False),
            "stagedForReview": res.get("stagedForReview", False),
            "error": res.get("error", ""),
            "evidence": res.get("evidence", {}),
            "fieldsFilled": res.get("fieldsFilled", {}),
        }
        print(f"RESULT FOR {job['company']}: submitted={res.get('submitted')} staged={res.get('stagedForReview')} error={res.get('error')}")

    out_file = repo_root / "data" / "autonomous_batch_results.json"
    out_file.parent.mkdir(parents=True, exist_ok=True)
    with open(out_file, "w", encoding="utf-8") as f:
        json.dump(results, f, indent=2)
    logger.info(f"Summary written to {out_file}")

if __name__ == "__main__":
    asyncio.run(main())
