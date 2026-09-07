"""Jobicy JobSourceAdapter implementation for CareerOS Job Ingestion V2."""

from __future__ import annotations

import time
from datetime import datetime
from typing import Any

import httpx

from app.services.job_discover.sources.base import JobSourceAdapter, NormalizedJob


class JobicySource(JobSourceAdapter):
    """Ingest remote engineering jobs from Jobicy public API."""

    id = "jobicy"
    name = "Jobicy Remote Jobs"
    source_type = "public_api"
    priority = 80
    supports_incremental_sync = True

    def supports(self, source_type: str, config: dict[str, Any] | None = None) -> bool:
        return source_type.lower() in ("jobicy", "jobicy_api")

    async def fetch_jobs(
        self,
        client: httpx.AsyncClient,
        company: str = "all",
        config: dict[str, Any] | None = None,
        compiled_patterns: list[Any] | None = None,
        cutoff: datetime | None = None,
        role_keys: list[str] | None = None,
    ) -> list[NormalizedJob]:
        from app.services.job_discover.scraper_service import is_recent, matches_title, s, strip_html

        start_time = time.perf_counter()
        cfg = config or {}
        count = cfg.get("count", 50)
        industry = cfg.get("industry", "engineering")
        geo = cfg.get("geo", "usa")

        url = f"https://jobicy.com/api/v2/remote-jobs?count={count}&geo={geo}&industry={industry}"

        resp = await self.execute_request(client, url, timeout=20.0)
        if not resp or resp.status_code != 200:
            self.record_failure(f"HTTP {resp.status_code if resp else 'No response'}")
            return []

        try:
            data = resp.json()
            postings = data.get("jobs", [])
            jobs: list[NormalizedJob] = []

            for item in postings:
                title = item.get("jobTitle", "")
                pub_date = item.get("pubDate", "")

                if compiled_patterns and not matches_title(title, compiled_patterns):
                    continue
                if cutoff and not is_recent(pub_date, cutoff):
                    continue

                item_id = s(item.get("id", ""))
                comp_name = item.get("companyName", "Unknown Company")
                raw_url = item.get("url", "")
                loc = item.get("jobGeo", "Remote, USA")

                salary_min = float(item.get("annualSalaryMin")) if item.get("annualSalaryMin") else None
                salary_max = float(item.get("annualSalaryMax")) if item.get("annualSalaryMax") else None
                salary_curr = item.get("salaryCurrency") or "USD"
                salary_range = ""
                if salary_min or salary_max:
                    salary_range = f"{salary_curr} {salary_min:,.0f} - {salary_max:,.0f}" if (salary_min and salary_max) else f"{salary_curr} {salary_min or salary_max:,.0f}"

                normalized = NormalizedJob(
                    id=f"jobicy:{item_id or raw_url}",
                    external_id=item_id,
                    company=comp_name.lower().replace(" ", "-"),
                    company_name=comp_name,
                    title=title,
                    location=loc,
                    locations=[loc],
                    remote=True,
                    hybrid=False,
                    remote_status="REMOTE",
                    workplace_type="remote",
                    department=item.get("jobIndustry", "Engineering"),
                    source_url=raw_url,
                    apply_url=raw_url,
                    canonical_url=raw_url,
                    description=strip_html(item.get("jobDescription") or item.get("jobExcerpt", "")),
                    updated_at=pub_date,
                    first_published=pub_date,
                    employment_type=item.get("jobType", "Full-Time"),
                    seniority=item.get("jobLevel", "MID").upper(),
                    salary_min=salary_min,
                    salary_max=salary_max,
                    salary_currency=salary_curr,
                    salary_range=salary_range,
                    source="jobicy",
                    source_type="public_api",
                    source_priority=80,
                    source_quality=80,
                    extraction_method="jobicy_api",
                    provenance_sources=["jobicy"],
                    source_metadata={
                        "company_logo": item.get("companyLogo"),
                    },
                )
                jobs.append(normalized)

            duration = (time.perf_counter() - start_time) * 1000
            self.record_success(len(jobs), duration)
            return jobs
        except Exception as exc:
            self.record_failure(exc)
            return []
