"""Workable JobSourceAdapter implementation for CareerOS Job Ingestion V2."""

from __future__ import annotations

import time
from datetime import datetime
from typing import Any

import httpx

from app.services.job_discover.sources.base import JobSourceAdapter, NormalizedJob


class WorkableSource(JobSourceAdapter):
    """Ingest jobs from Workable public widget JSON API endpoints."""

    id = "workable"
    name = "Workable"
    source_type = "ats"
    priority = 95

    def supports(self, source_type: str, config: dict[str, Any] | None = None) -> bool:
        return source_type.lower() == "workable"

    async def fetch_jobs(
        self,
        client: httpx.AsyncClient,
        company: str,
        config: dict[str, Any],
        compiled_patterns: list[Any],
        cutoff: datetime,
        role_keys: list[str] | None = None,
    ) -> list[NormalizedJob]:
        from app.services.job_discover.scraper_service import is_recent, matches_title, s, strip_html

        start_time = time.perf_counter()
        slug = config.get("slug") or company
        url = f"https://apply.workable.com/api/v1/widget/accounts/{slug}"

        resp = await self.execute_request(client, url, timeout=20.0)
        if not resp or resp.status_code != 200:
            self.record_failure(f"HTTP {resp.status_code if resp else 'No response'}")
            return []

        try:
            data = resp.json()
            raw_jobs = data.get("jobs", [])
            jobs: list[NormalizedJob] = []

            for job in raw_jobs:
                title = job.get("title", "")
                ts = job.get("published_on", "")
                if not matches_title(title, compiled_patterns):
                    continue
                if not is_recent(ts, cutoff):
                    continue

                city = job.get("city", "")
                country = job.get("country", "")
                state = job.get("state") or job.get("region", "")
                location = f"{city}, {state} {country}".strip(", ") if (city or state or country) else ""

                is_remote = bool(job.get("telecommuting")) or any(k in f"{location} {title}".lower() for k in ("remote", "virtual", "wfh"))
                is_hybrid = "hybrid" in f"{location} {title}".lower()
                remote_status = "REMOTE" if is_remote else ("HYBRID" if is_hybrid else "ONSITE")

                job_id = s(job.get("shortcode") or job.get("id", ""))
                hosted_url = job.get("url") or job.get("application_url") or f"https://apply.workable.com/{slug}/j/{job_id}"
                apply_url = job.get("application_url") or hosted_url

                normalized = NormalizedJob(
                    id=f"{company}:{job_id}",
                    external_id=job_id,
                    company=company,
                    company_name=config.get("company_name") or company.replace("-", " ").capitalize(),
                    title=title,
                    location=location,
                    locations=[location] if location else [],
                    city=city,
                    state=state,
                    country=country or "US",
                    remote=is_remote,
                    hybrid=is_hybrid,
                    remote_status=remote_status,
                    department=job.get("department", ""),
                    source_url=hosted_url,
                    apply_url=apply_url,
                    canonical_url=hosted_url,
                    description=strip_html(job.get("description", "")),
                    updated_at=ts,
                    first_published=ts,
                    employment_type=job.get("employment_type", "Full-time"),
                    source="workable",
                    source_type="ats",
                    source_priority=95,
                    source_quality=95,
                    extraction_method="workable_api",
                    provenance_sources=["workable"],
                )
                jobs.append(normalized)

            duration = (time.perf_counter() - start_time) * 1000
            self.record_success(len(jobs), duration)
            return jobs
        except Exception as exc:
            self.record_failure(exc)
            return []
