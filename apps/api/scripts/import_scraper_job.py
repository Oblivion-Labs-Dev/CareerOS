"""Import a job from the scraper index into Application Assistant."""

from __future__ import annotations

import hashlib
import json
import sys

from app.db.store import get_kv, session_scope
from app.services.application_assistant.job_matching import match_job
from app.services.application_assistant.persistence import save_job_match, upsert_discovered_job
from app.services.job_discover import store as jd_store

JOB_ID = sys.argv[1] if len(sys.argv) > 1 else "reddit:8082867"


def main() -> None:
    with session_scope() as db:
        snap = jd_store.get_snapshot(db)
        scraper_job = next((j for j in (snap.get("jobs") or []) if j.get("id") == JOB_ID), None)
        if not scraper_job:
            print(json.dumps({"success": False, "error": f"Scraper job {JOB_ID} not found"}))
            sys.exit(1)

        desc = (scraper_job.get("description") or "")[:500]
        content_hash = hashlib.md5(
            f"{scraper_job['title']}{scraper_job.get('location', '')}{desc}".encode()
        ).hexdigest()
        url = scraper_job["url"]
        job_data = {
            "id": "aa_" + scraper_job["id"].replace(":", "_"),
            "sourceProvider": "greenhouse",
            "company": (scraper_job.get("companyName") or "").title(),
            "title": scraper_job["title"],
            "description": scraper_job.get("description", ""),
            "location": scraper_job.get("location", ""),
            "workplaceType": "remote" if "remote" in scraper_job.get("location", "").lower() else "",
            "applicationUrl": url,
            "listingUrl": url,
            "externalJobId": scraper_job.get("externalId", ""),
            "contentHash": content_hash,
            "active": True,
            "discoveryRunId": "scraper_import",
            "scraperJobId": scraper_job["id"],
        }
        saved = upsert_discovered_job(db, job_data)
        profile = get_kv(db, "profile") or {}
        match = match_job(saved, profile)
        save_job_match(db, match)
        print(
            json.dumps(
                {
                    "success": True,
                    "jobId": saved["id"],
                    "title": saved["title"],
                    "company": saved["company"],
                    "url": url,
                    "matchScore": match.get("overallScore"),
                }
            )
        )


if __name__ == "__main__":
    main()
