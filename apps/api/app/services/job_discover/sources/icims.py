"""iCIMS JobSourceAdapter implementation for CareerOS Job Ingestion V2."""

from __future__ import annotations

import re
import time
from datetime import datetime
from typing import Any

import httpx

from app.services.job_discover.sources.base import JobSourceAdapter, NormalizedJob


class ICIMSSource(JobSourceAdapter):
    """Ingest jobs from iCIMS portal search endpoints."""

    id = "icims"
    name = "iCIMS"
    source_type = "ats"
    priority = 95

    def supports(self, source_type: str, config: dict[str, Any] | None = None) -> bool:
        return source_type.lower() == "icims"

    async def fetch_jobs(
        self,
        client: httpx.AsyncClient,
        company: str,
        config: dict[str, Any],
        compiled_patterns: list[Any],
        cutoff: datetime,
        role_keys: list[str] | None = None,
    ) -> list[NormalizedJob]:
        from app.services.job_discover.scraper_service import matches_title, s, strip_html

        start_time = time.perf_counter()
        portal = config.get("portal") or company
        # iCIMS search JSON/HTML endpoint
        url = f"https://{portal}.icims.com/jobs/search?pr=0&schemaId=&o=&in_iframe=1"

        resp = await self.execute_request(
            client,
            url,
            headers={"Accept": "text/html,application/xhtml+xml"},
            timeout=20.0,
        )
        if not resp or resp.status_code != 200:
            self.record_failure(f"HTTP {resp.status_code if resp else 'No response'}")
            return []

        try:
            html = resp.text
            jobs: list[NormalizedJob] = []

            # Match iCIMS job rows: <a class="iCIMS_Anchor" href="https://.../jobs/{id}/{slug}/job?in_iframe=1" ...><span>Title</span></a>
            pattern = re.compile(
                r'href=["\'](https://[^"\']*icims\.com/jobs/(\d+)/([^"\'/]+)/job[^"\']*)["\'][^>]*>(?:<span[^>]*>)?([^<]+)',
                re.IGNORECASE,
            )

            for match in pattern.finditer(html):
                job_url = match.group(1).replace("&amp;", "&")
                job_id = match.group(2)
                title = match.group(4).strip()

                if not matches_title(title, compiled_patterns):
                    continue

                combined = title.lower()
                is_remote = any(k in combined for k in ("remote", "virtual", "wfh"))
                is_hybrid = "hybrid" in combined
                remote_status = "REMOTE" if is_remote else ("HYBRID" if is_hybrid else "ONSITE")

                normalized = NormalizedJob(
                    id=f"{company}:{job_id}",
                    external_id=job_id,
                    company=company,
                    company_name=config.get("company_name") or company.replace("-", " ").capitalize(),
                    title=title,
                    location="United States",
                    remote=is_remote,
                    hybrid=is_hybrid,
                    remote_status=remote_status,
                    source_url=job_url,
                    apply_url=job_url,
                    canonical_url=job_url.split("?")[0],
                    description="",
                    source="icims",
                    source_type="ats",
                    source_priority=95,
                    source_quality=95,
                    extraction_method="icims_portal",
                    provenance_sources=["icims"],
                    source_metadata={"requisition_id": job_id},
                )
                jobs.append(normalized)

            duration = (time.perf_counter() - start_time) * 1000
            self.record_success(len(jobs), duration)
            return jobs
        except Exception as exc:
            self.record_failure(exc)
            return []
