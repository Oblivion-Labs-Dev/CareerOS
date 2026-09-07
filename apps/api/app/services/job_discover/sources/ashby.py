"""Ashby JobSourceAdapter implementation for CareerOS Job Ingestion V2."""

from __future__ import annotations

import time
from datetime import datetime
from typing import Any

import httpx

from app.services.job_discover.sources.base import JobSourceAdapter, NormalizedJob


class AshbySource(JobSourceAdapter):
    """Ingest jobs from Ashby public JSON API endpoints."""

    id = "ashby"
    name = "Ashby"
    source_type = "ats"
    priority = 95

    def supports(self, source_type: str, config: dict[str, Any] | None = None) -> bool:
        return source_type.lower() == "ashby"

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
        slug = config.get("slug") or config.get("boardId") or company
        url = f"https://api.ashbyhq.com/posting-api/job-board/{slug}?includeCompensation=true"

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
                ts = job.get("updatedAt") or job.get("publishedAt", "")
                if compiled_patterns and not matches_title(title, compiled_patterns):
                    continue
                if not is_recent(ts, cutoff):
                    continue

                location = job.get("location", "")
                sec_locations = job.get("secondaryLocations") or []
                all_locs = [location] if location else []
                for s_loc in sec_locations:
                    s_name = s_loc.get("location") if isinstance(s_loc, dict) else str(s_loc or "")
                    if s_name and s_name not in all_locs:
                        all_locs.append(s_name)

                is_remote = bool(job.get("isRemote"))
                workplace_type = "remote" if is_remote else ""
                combined_text = f"{location} {title} {' '.join(all_locs)}".lower()
                if not is_remote and any(k in combined_text for k in ("remote", "virtual", "wfh")):
                    is_remote = True
                is_hybrid = "hybrid" in combined_text
                remote_status = "REMOTE" if is_remote else ("HYBRID" if is_hybrid else "ONSITE")

                # Compensation parsing
                salary_str = ""
                salary_min = None
                salary_max = None
                salary_curr = "USD"
                comp = job.get("compensation") or {}
                if isinstance(comp, dict):
                    salary_min = float(comp.get("minSalary") or comp.get("targetSalary") or comp.get("min") or 0) or None
                    salary_max = float(comp.get("maxSalary") or comp.get("max") or 0) or None
                    salary_curr = comp.get("currency") or "USD"
                    summary = comp.get("summary") or comp.get("compensationTierSummary")
                    if summary:
                        salary_str = str(summary)
                    elif salary_min or salary_max:
                        salary_str = f"{salary_curr} {salary_min:,.0f} - {salary_max:,.0f}" if (salary_min and salary_max) else f"{salary_curr} {salary_min or salary_max:,.0f}"

                job_id = s(job.get("id", ""))
                hosted_url = f"https://jobs.ashbyhq.com/{slug}/{job_id}"
                apply_url = job.get("applicationUrl") or job.get("applyUrl") or hosted_url

                normalized = NormalizedJob(
                    id=f"{company}:{job_id}",
                    external_id=job_id,
                    company=company,
                    company_name=config.get("company_name") or company.replace("-", " ").capitalize(),
                    title=title,
                    location=location,
                    locations=all_locs,
                    remote=is_remote,
                    hybrid=is_hybrid,
                    remote_status=remote_status,
                    workplace_type=workplace_type,
                    department=job.get("department") or job.get("departmentName", ""),
                    team=job.get("team") or "",
                    source_url=hosted_url,
                    apply_url=apply_url,
                    canonical_url=hosted_url,
                    description=strip_html(job.get("descriptionHtml") or job.get("descriptionPlain", "")),
                    updated_at=job.get("updatedAt", ""),
                    first_published=job.get("publishedAt", ""),
                    employment_type=job.get("employmentType", "Full-time"),
                    salary_range=salary_str,
                    salary_min=salary_min,
                    salary_max=salary_max,
                    salary_currency=salary_curr,
                    source="ashby",
                    source_type="ats",
                    source_priority=95,
                    source_quality=95,
                    extraction_method="ashby_api",
                    provenance_sources=["ashby"],
                )
                jobs.append(normalized)

            duration = (time.perf_counter() - start_time) * 1000
            self.record_success(len(jobs), duration)
            return jobs
        except Exception as exc:
            self.record_failure(exc)
            return []
