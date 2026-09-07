"""Remotive JobSourceAdapter implementation for CareerOS Job Ingestion V2."""

from __future__ import annotations

import time
from datetime import datetime
from typing import Any

import httpx

from app.services.job_discover.sources.base import JobSourceAdapter, NormalizedJob


class RemotiveSource(JobSourceAdapter):
    """Ingest remote jobs from Remotive public API."""

    id = "remotive"
    name = "Remotive Jobs"
    source_type = "public_api"
    priority = 80
    supports_incremental_sync = True

    def supports(self, source_type: str, config: dict[str, Any] | None = None) -> bool:
        return source_type.lower() in ("remotive", "remotive_api")

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
        url = "https://remotive.com/api/remote-jobs?category=software-dev&limit=100"

        resp = await self.execute_request(client, url, timeout=20.0)
        if not resp or resp.status_code != 200:
            self.record_failure(f"HTTP {resp.status_code if resp else 'No response'}")
            return []

        try:
            data = resp.json()
            postings = data.get("jobs", [])
            jobs: list[NormalizedJob] = []

            for item in postings:
                title = item.get("title", "")
                pub_date = item.get("publication_date", "")

                if compiled_patterns and not matches_title(title, compiled_patterns):
                    continue
                if cutoff and pub_date and not is_recent(pub_date, cutoff):
                    continue

                item_id = s(item.get("id", ""))
                comp_name = item.get("company_name", "Unknown Company")
                raw_url = item.get("url", "")
                loc = item.get("candidate_required_location", "Remote, Worldwide")
                salary = item.get("salary", "")

                normalized = NormalizedJob(
                    id=f"remotive:{item_id}",
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
                    department=item.get("category", "Software Development"),
                    source_url=raw_url,
                    apply_url=raw_url,
                    canonical_url=raw_url,
                    description=strip_html(item.get("description", "")),
                    updated_at=pub_date,
                    first_published=pub_date,
                    employment_type=item.get("job_type", "Full-time"),
                    salary_range=salary,
                    skills=[str(t) for t in item.get("tags", [])],
                    source="remotive",
                    source_type="public_api",
                    source_priority=80,
                    source_quality=80,
                    extraction_method="remotive_api",
                    provenance_sources=["remotive"],
                )
                jobs.append(normalized)

            duration = (time.perf_counter() - start_time) * 1000
            self.record_success(len(jobs), duration)
            return jobs
        except Exception as exc:
            self.record_failure(exc)
            return []
