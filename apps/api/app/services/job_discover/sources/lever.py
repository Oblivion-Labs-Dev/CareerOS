"""Lever JobSource implementation for CareerOS."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

import httpx

from app.services.job_discover.sources.base import JobSource, NormalizedJob


class LeverSource(JobSource):
    """Ingest jobs from Lever public JSON API endpoints."""

    id = "lever"
    name = "Lever"

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

        slug = config.get("slug") or config.get("boardId") or company
        url = f"https://api.lever.co/v0/postings/{slug}"

        try:
            resp = await client.get(url, timeout=15)
            if resp.status_code != 200:
                return []
            postings = resp.json()
            if not isinstance(postings, list):
                return []

            jobs: list[NormalizedJob] = []
            for job in postings:
                title = job.get("text", "")
                created = job.get("createdAt", 0)
                ts = datetime.fromtimestamp(created / 1000, tz=UTC).isoformat() if created else ""
                if not matches_title(title, compiled_patterns):
                    continue
                if not is_recent(ts, cutoff):
                    continue

                categories = job.get("categories", {})
                normalized = NormalizedJob(
                    id=f"{company}:{s(job.get('id', ''))}",
                    external_id=s(job.get("id", "")),
                    company=company,
                    company_name=company.capitalize(),
                    title=title,
                    location=categories.get("location", ""),
                    department=categories.get("department", ""),
                    source_url=job.get("hostedUrl") or job.get("applyUrl", ""),
                    description=strip_html(job.get("descriptionPlain") or job.get("description", "")),
                    updated_at="",
                    first_published=ts,
                    employment_type=categories.get("commitment", ""),
                    salary_range="",
                    source="lever",
                    extraction_method="lever",
                )
                jobs.append(normalized)

            return jobs
        except Exception:
            return []
