"""Greenhouse JobSource implementation for CareerOS."""

from __future__ import annotations

from datetime import datetime
from typing import Any

import httpx

from app.services.job_discover.sources.base import JobSource, NormalizedJob


class GreenhouseSource(JobSource):
    """Ingest jobs from Greenhouse public JSON API endpoints."""

    id = "greenhouse"
    name = "Greenhouse"

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

        slug = config.get("slug") or config.get("boardId") or company
        url = f"https://boards-api.greenhouse.io/v1/boards/{slug}/jobs?content=true"

        try:
            resp = await client.get(url, timeout=15)
            if resp.status_code != 200:
                return []
            data = resp.json()
            jobs: list[NormalizedJob] = []

            for job in data.get("jobs", []):
                title = job.get("title", "")
                ts = job.get("updated_at", "")
                if not matches_title(title, compiled_patterns):
                    continue
                if not is_recent(ts, cutoff):
                    continue

                loc = job.get("location", {})
                location = loc.get("name", "") if isinstance(loc, dict) else str(loc or "")
                departments = job.get("departments") or []
                metadata = {m.get("name", ""): m.get("value") for m in (job.get("metadata") or [])}
                dept_names = ", ".join(d.get("name", "") for d in departments if d.get("name"))

                normalized = NormalizedJob(
                    id=f"{company}:{s(job.get('id', ''))}",
                    external_id=s(job.get("id", "")),
                    company=company,
                    company_name=company.capitalize(),
                    title=title,
                    location=location,
                    department=dept_names,
                    source_url=job.get("absolute_url", ""),
                    description=strip_html(job.get("content", "")),
                    updated_at=job.get("updated_at", ""),
                    first_published=job.get("first_published", ""),
                    employment_type=s(metadata.get("Employment Type", "")),
                    salary_range=s(metadata.get("Salary Range", metadata.get("Compensation Range", ""))),
                    source="greenhouse",
                    extraction_method="greenhouse",
                )
                jobs.append(normalized)

            return jobs
        except Exception:
            return []
