"""Greenhouse JobSourceAdapter implementation for CareerOS Job Ingestion V2."""

from __future__ import annotations

import time
from datetime import datetime
from typing import Any

import httpx

from app.services.job_discover.sources.base import JobSourceAdapter, NormalizedJob


class GreenhouseSource(JobSourceAdapter):
    """Ingest jobs from Greenhouse public JSON API endpoints."""

    id = "greenhouse"
    name = "Greenhouse"
    source_type = "ats"
    priority = 95

    def supports(self, source_type: str, config: dict[str, Any] | None = None) -> bool:
        return source_type.lower() == "greenhouse"

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
        url = f"https://boards-api.greenhouse.io/v1/boards/{slug}/jobs?content=true"

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
                ts = job.get("updated_at", "")
                if compiled_patterns and not matches_title(title, compiled_patterns):
                    continue
                if not is_recent(ts, cutoff):
                    continue

                loc = job.get("location", {})
                location = loc.get("name", "") if isinstance(loc, dict) else str(loc or "")
                departments = job.get("departments") or []
                metadata = {m.get("name", ""): m.get("value") for m in (job.get("metadata") or [])}
                dept_names = ", ".join(d.get("name", "") for d in departments if d.get("name"))

                # Extract offices / secondary locations
                offices = job.get("offices") or []
                all_locs = [location] if location else []
                for off in offices:
                    off_name = off.get("name")
                    if off_name and off_name not in all_locs:
                        all_locs.append(off_name)

                # Parse salary range if exposed
                salary_str = s(metadata.get("Salary Range", metadata.get("Compensation Range", "")))
                salary_min = None
                salary_max = None
                if salary_str:
                    import re
                    nums = [float(n.replace(",", "")) for n in re.findall(r"\b\d{2,3}(?:,\d{3})+\b|\b\d{5,6}\b", salary_str)]
                    if len(nums) >= 2:
                        salary_min, salary_max = min(nums[:2]), max(nums[:2])
                    elif len(nums) == 1:
                        salary_min = nums[0]

                # Detect remote / hybrid
                combined_text = f"{location} {title} {' '.join(all_locs)}".lower()
                is_remote = any(k in combined_text for k in ("remote", "virtual", "wfh", "telecommute"))
                is_hybrid = "hybrid" in combined_text
                remote_status = "REMOTE" if is_remote else ("HYBRID" if is_hybrid else "ONSITE")

                job_id = s(job.get("id", ""))
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
                    department=dept_names,
                    source_url=job.get("absolute_url", ""),
                    apply_url=job.get("absolute_url", ""),
                    description=strip_html(job.get("content", "")),
                    updated_at=ts,
                    first_published=job.get("first_published", ""),
                    employment_type=s(metadata.get("Employment Type", "Full-time")),
                    salary_range=salary_str,
                    salary_min=salary_min,
                    salary_max=salary_max,
                    source="greenhouse",
                    source_type="ats",
                    source_priority=95,
                    source_quality=95,
                    extraction_method="greenhouse_api",
                    provenance_sources=["greenhouse"],
                    source_metadata={
                        "internal_job_id": job.get("internal_job_id"),
                        "requisition_id": job.get("requisition_id"),
                    },
                )
                jobs.append(normalized)

            duration = (time.perf_counter() - start_time) * 1000
            self.record_success(len(jobs), duration)
            return jobs
        except Exception as exc:
            self.record_failure(exc)
            return []
