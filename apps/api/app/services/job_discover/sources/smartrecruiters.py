"""SmartRecruiters JobSourceAdapter implementation for CareerOS Job Ingestion V2."""

from __future__ import annotations

import time
from datetime import datetime
from typing import Any

import httpx

from app.services.job_discover.sources.base import JobSourceAdapter, NormalizedJob


class SmartRecruitersSource(JobSourceAdapter):
    """Ingest jobs from SmartRecruiters public JSON API endpoints."""

    id = "smartrecruiters"
    name = "SmartRecruiters"
    source_type = "ats"
    priority = 95

    def supports(self, source_type: str, config: dict[str, Any] | None = None) -> bool:
        return source_type.lower() == "smartrecruiters"

    async def fetch_jobs(
        self,
        client: httpx.AsyncClient,
        company: str,
        config: dict[str, Any],
        compiled_patterns: list[Any],
        cutoff: datetime,
        role_keys: list[str] | None = None,
    ) -> list[NormalizedJob]:
        from app.services.job_discover.scraper_service import is_recent, matches_title, s

        start_time = time.perf_counter()
        slug = config.get("slug") or config.get("companyIdentifier") or company
        offset = 0
        limit = 100
        jobs: list[NormalizedJob] = []

        while True:
            url = f"https://api.smartrecruiters.com/v1/companies/{slug}/postings?offset={offset}&limit={limit}"
            resp = await self.execute_request(client, url, timeout=20.0)
            if not resp or resp.status_code != 200:
                if not jobs:
                    self.record_failure(f"HTTP {resp.status_code if resp else 'No response'}")
                break

            try:
                data = resp.json()
                postings = data.get("content", [])
                if not postings:
                    break

                for job in postings:
                    title = job.get("name", "")
                    ts = job.get("releasedDate", "")
                    if compiled_patterns and not matches_title(title, compiled_patterns):
                        continue
                    if not is_recent(ts, cutoff):
                        continue

                    loc = job.get("location", {})
                    location_parts = [loc.get("city", ""), loc.get("region", ""), loc.get("country", "")]
                    location = ", ".join(p for p in location_parts if p)

                    dept_obj = job.get("department") or {}
                    department = dept_obj.get("label", "") if isinstance(dept_obj, dict) else str(dept_obj or "")
                    emp_type_obj = job.get("typeOfEmployment") or {}
                    emp_type = emp_type_obj.get("label", "") if isinstance(emp_type_obj, dict) else str(emp_type_obj or "Full-time")
                    exp_level_obj = job.get("experienceLevel") or {}
                    exp_level = exp_level_obj.get("label", "") if isinstance(exp_level_obj, dict) else ""

                    # Remote / workplace type
                    is_remote = bool(loc.get("remote")) or any(k in f"{location} {title}".lower() for k in ("remote", "virtual", "wfh"))
                    is_hybrid = "hybrid" in f"{location} {title}".lower()
                    remote_status = "REMOTE" if is_remote else ("HYBRID" if is_hybrid else "ONSITE")

                    # Links
                    job_id = s(job.get("id") or job.get("uuid", ""))
                    hosted_url = job.get("ref") or f"https://jobs.smartrecruiters.com/{slug}/{job_id}"
                    apply_url = job.get("applyUrl") or hosted_url

                    normalized = NormalizedJob(
                        id=f"{company}:{job_id}",
                        external_id=job_id,
                        company=company,
                        company_name=config.get("company_name") or company.replace("-", " ").capitalize(),
                        title=title,
                        location=location,
                        locations=[location] if location else [],
                        city=loc.get("city", ""),
                        state=loc.get("region", ""),
                        country=loc.get("country", "US"),
                        remote=is_remote,
                        hybrid=is_hybrid,
                        remote_status=remote_status,
                        department=department,
                        source_url=hosted_url,
                        apply_url=apply_url,
                        canonical_url=hosted_url,
                        description="",  # Listing endpoint excludes description
                        updated_at=ts,
                        first_published=ts,
                        employment_type=emp_type,
                        seniority=exp_level or "MID",
                        source="smartrecruiters",
                        source_type="ats",
                        source_priority=95,
                        source_quality=95,
                        extraction_method="smartrecruiters_api",
                        provenance_sources=["smartrecruiters"],
                        source_metadata={
                            "industry": job.get("industry", {}).get("label") if isinstance(job.get("industry"), dict) else "",
                            "function": job.get("function", {}).get("label") if isinstance(job.get("function"), dict) else "",
                        },
                    )
                    jobs.append(normalized)

                total = data.get("totalFound", 0)
                offset += limit
                if offset >= total or offset >= 300:  # Cap pagination at 300 per company run
                    break

            except Exception as exc:
                self.record_failure(exc)
                break

        duration = (time.perf_counter() - start_time) * 1000
        if jobs:
            self.record_success(len(jobs), duration)
        return jobs
