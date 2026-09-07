"""Lever JobSourceAdapter implementation for CareerOS Job Ingestion V2."""

from __future__ import annotations

import re
import time
from datetime import UTC, datetime
from typing import Any

import httpx

from app.services.job_discover.sources.base import JobSourceAdapter, NormalizedJob


class LeverSource(JobSourceAdapter):
    """Ingest jobs from Lever public JSON API endpoints."""

    id = "lever"
    name = "Lever"
    source_type = "ats"
    priority = 95

    def supports(self, source_type: str, config: dict[str, Any] | None = None) -> bool:
        return source_type.lower() == "lever"

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
        url = f"https://api.lever.co/v0/postings/{slug}?mode=json"

        resp = await self.execute_request(client, url, timeout=20.0)
        if not resp or resp.status_code != 200:
            self.record_failure(f"HTTP {resp.status_code if resp else 'No response'}")
            return []

        try:
            postings = resp.json()
            if not isinstance(postings, list):
                self.record_failure("Malformed response: expected list")
                return []

            jobs: list[NormalizedJob] = []
            for job in postings:
                title = job.get("text", "")
                created = job.get("createdAt", 0)
                ts = datetime.fromtimestamp(created / 1000, tz=UTC).isoformat() if created else ""
                if compiled_patterns and not matches_title(title, compiled_patterns):
                    continue
                if not is_recent(ts, cutoff):
                    continue

                categories = job.get("categories", {})
                location = categories.get("location", "")
                department = categories.get("department", "")
                team = categories.get("team", "")
                commitment = categories.get("commitment", "Full-time")

                # Workplace type / remote detection
                workplace_type = str(job.get("workplaceType") or categories.get("workplaceType") or "")
                combined_text = f"{location} {title} {workplace_type}".lower()
                is_remote = workplace_type.lower() == "remote" or any(k in combined_text for k in ("remote", "virtual", "wfh"))
                is_hybrid = workplace_type.lower() == "hybrid" or "hybrid" in combined_text
                remote_status = "REMOTE" if is_remote else ("HYBRID" if is_hybrid else "ONSITE")

                # All locations
                all_locs = [location] if location else []
                addl = categories.get("allLocations") or []
                for loc_item in addl:
                    if loc_item and loc_item not in all_locs:
                        all_locs.append(loc_item)

                # Salary / compensation
                salary_range = ""
                salary_min = None
                salary_max = None
                salary_curr = "USD"
                salary_obj = job.get("salaryRange") or {}
                if isinstance(salary_obj, dict) and (salary_obj.get("min") or salary_obj.get("max")):
                    salary_min = float(salary_obj["min"]) if salary_obj.get("min") is not None else None
                    salary_max = float(salary_obj["max"]) if salary_obj.get("max") is not None else None
                    salary_curr = salary_obj.get("currency") or "USD"
                    salary_range = f"{salary_curr} {salary_min:,.0f} - {salary_max:,.0f}" if (salary_min and salary_max) else f"{salary_curr} {salary_min or salary_max:,.0f}"

                job_id = s(job.get("id", ""))
                hosted_url = job.get("hostedUrl") or ""
                apply_url = job.get("applyUrl") or hosted_url

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
                    department=department,
                    team=team,
                    source_url=hosted_url,
                    apply_url=apply_url,
                    canonical_url=hosted_url,
                    description=strip_html(job.get("descriptionPlain") or job.get("description", "")),
                    updated_at=ts,
                    first_published=ts,
                    employment_type=commitment,
                    salary_range=salary_range,
                    salary_min=salary_min,
                    salary_max=salary_max,
                    salary_currency=salary_curr,
                    source="lever",
                    source_type="ats",
                    source_priority=95,
                    source_quality=95,
                    extraction_method="lever_api",
                    provenance_sources=["lever"],
                )
                jobs.append(normalized)

            duration = (time.perf_counter() - start_time) * 1000
            self.record_success(len(jobs), duration)
            return jobs
        except Exception as exc:
            self.record_failure(exc)
            return []
