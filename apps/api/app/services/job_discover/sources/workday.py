"""Workday JobSource implementation for CareerOS."""

from __future__ import annotations

from datetime import datetime
from typing import Any

import httpx

from app.services.job_discover.sources.base import JobSource, NormalizedJob


class WorkdaySource(JobSource):
    """Ingest jobs from Workday JSON endpoints."""

    id = "workday"
    name = "Workday"

    def supports(self, source_type: str, config: dict[str, Any] | None = None) -> bool:
        return source_type.lower() == "workday"

    async def fetch_jobs(
        self,
        client: httpx.AsyncClient,
        company: str,
        config: dict[str, Any],
        compiled_patterns: list[Any],
        cutoff: datetime,
        role_keys: list[str] | None = None,
    ) -> list[NormalizedJob]:
        from app.services.job_discover.scraper_service import matches_title, s

        host = config.get("host", "")
        wd_company = config.get("company") or config.get("tenant") or company
        board = config.get("board") or config.get("site") or "careers"

        if not host:
            return []

        url = f"https://{host}/wday/cxs/{wd_company}/{board}/jobs"
        wd_headers = {
            "Content-Type": "application/json",
            "Accept": "application/json",
            "Origin": f"https://{host}",
            "Referer": f"https://{host}/{board}",
        }

        all_jobs: list[NormalizedJob] = []
        offset = 0
        limit = 20

        while True:
            payload = {"limit": limit, "offset": offset, "appliedFacets": {}, "searchText": ""}
            try:
                resp = await client.post(url, json=payload, headers=wd_headers, timeout=20)
                if resp.status_code not in (200, 201):
                    break
                data = resp.json()
                postings = data.get("jobPostings", [])
                if not postings:
                    break

                for job in postings:
                    title = job.get("title", "")
                    if not matches_title(title, compiled_patterns):
                        continue

                    ext_path = job.get("externalPath", "")
                    job_url = f"https://{host}{ext_path}" if ext_path else ""
                    job_id = s(job.get("bulletFields", [""])[0] if job.get("bulletFields") else ext_path)

                    location_parts = [loc.strip() for loc in (job.get("locationsText") or "").split("|") if loc.strip()]

                    normalized = NormalizedJob(
                        id=f"{company}:{job_id or title}",
                        external_id=job_id,
                        company=company,
                        company_name=company.capitalize(),
                        title=title,
                        location=" | ".join(location_parts),
                        department="",
                        source_url=job_url,
                        description="",  # Workday list API does not include description
                        updated_at="",
                        first_published=job.get("postedOn", ""),
                        employment_type=job.get("timeType", ""),
                        salary_range="",
                        source="workday",
                        extraction_method="workday",
                    )
                    all_jobs.append(normalized)

                total = data.get("total", 0)
                offset += limit
                if offset >= total or offset >= 200:
                    break
            except Exception:
                break

        return all_jobs
