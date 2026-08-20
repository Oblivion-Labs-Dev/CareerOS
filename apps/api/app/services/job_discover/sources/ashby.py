"""Ashby JobSource implementation for CareerOS."""

from __future__ import annotations

from datetime import datetime
from typing import Any

import httpx

from app.services.job_discover.sources.base import JobSource, NormalizedJob


class AshbySource(JobSource):
    """Ingest jobs from Ashby public JSON API endpoints."""

    id = "ashby"
    name = "Ashby"

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

        slug = config.get("slug") or config.get("boardId") or company
        url = f"https://api.ashbyhq.com/posting-api/job-board/{slug}"

        try:
            resp = await client.get(url, timeout=15)
            if resp.status_code != 200:
                return []
            data = resp.json()
            jobs: list[NormalizedJob] = []

            for job in data.get("jobs", []):
                title = job.get("title", "")
                ts = job.get("updatedAt") or job.get("publishedAt", "")
                if not matches_title(title, compiled_patterns):
                    continue
                if not is_recent(ts, cutoff):
                    continue

                job_id = s(job.get("id", ""))
                normalized = NormalizedJob(
                    id=f"{company}:{job_id}",
                    external_id=job_id,
                    company=company,
                    company_name=company.capitalize(),
                    title=title,
                    location=job.get("location", ""),
                    department=job.get("department") or job.get("departmentName", ""),
                    source_url=f"https://jobs.ashbyhq.com/{slug}/{job_id}",
                    description=strip_html(job.get("descriptionHtml") or job.get("descriptionPlain", "")),
                    updated_at=job.get("updatedAt", ""),
                    first_published=job.get("publishedAt", ""),
                    employment_type=job.get("employmentType", ""),
                    salary_range="",
                    source="ashby",
                    extraction_method="ashby",
                )
                jobs.append(normalized)

            return jobs
        except Exception:
            return []
