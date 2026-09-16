"""RemoteOK JobSourceAdapter implementation for CareerOS Job Ingestion V2."""

from __future__ import annotations

import time
from datetime import datetime
from typing import Any

import httpx

from app.services.job_discover.sources.base import JobSourceAdapter, NormalizedJob


class RemoteOKSource(JobSourceAdapter):
    """Ingest remote jobs from RemoteOK's public, keyless JSON API.

    Verified 2026-09-15: `https://remoteok.com/api` is real and live (100 current
    postings tested). RemoteOK's own response embeds an attribution requirement
    ("legal" object at index 0, not a job) - CareerOS keeps `source_url`/`apply_url`
    pointing back at remoteok.com on every posting, which satisfies it.
    """

    id = "remoteok"
    name = "RemoteOK"
    source_type = "public_api"
    priority = 80

    def supports(self, source_type: str, config: dict[str, Any] | None = None) -> bool:
        return source_type.lower() in ("remoteok", "remote_ok")

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
        url = "https://remoteok.com/api"
        headers = {"User-Agent": "CareerOS-JobIngestion/2.0 (+https://careeros.dev)"}

        resp = await self.execute_request(client, url, headers=headers, timeout=20.0)
        if not resp or resp.status_code != 200:
            self.record_failure(f"HTTP {resp.status_code if resp else 'No response'}")
            return []

        try:
            data = resp.json()
            # First element is RemoteOK's own "legal"/attribution notice, not a posting.
            postings = [item for item in data if isinstance(item, dict) and item.get("id")]
            jobs: list[NormalizedJob] = []

            for item in postings:
                title = item.get("position", "")
                pub_date = item.get("date", "")

                if compiled_patterns and not matches_title(title, compiled_patterns):
                    continue
                if cutoff and pub_date and not is_recent(pub_date, cutoff):
                    continue

                item_id = s(item.get("id", ""))
                comp_name = item.get("company", "Unknown Company")
                job_url = item.get("url", "")
                loc = item.get("location") or "Remote, Worldwide"
                salary_min = item.get("salary_min") or None
                salary_max = item.get("salary_max") or None

                normalized = NormalizedJob(
                    id=f"remoteok:{item_id}",
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
                    source_url=job_url,
                    apply_url=item.get("apply_url") or job_url,
                    canonical_url=job_url,
                    description=strip_html(item.get("description", "")),
                    updated_at=pub_date,
                    first_published=pub_date,
                    employment_type="Full-time",
                    salary_min=float(salary_min) if salary_min else None,
                    salary_max=float(salary_max) if salary_max else None,
                    skills=[str(t) for t in item.get("tags", [])],
                    source="remoteok",
                    source_type="public_api",
                    source_priority=80,
                    source_quality=80,
                    extraction_method="remoteok_api",
                    provenance_sources=["remoteok"],
                )
                jobs.append(normalized)

            duration = (time.perf_counter() - start_time) * 1000
            self.record_success(len(jobs), duration)
            return jobs
        except Exception as exc:
            self.record_failure(exc)
            return []
