"""Oracle Cloud Recruiting / Taleo JobSourceAdapter for CareerOS Job Ingestion V2."""

from __future__ import annotations

import re
import time
from datetime import datetime
from typing import Any

import httpx

from app.services.job_discover.sources.base import JobSourceAdapter, NormalizedJob


class OracleSource(JobSourceAdapter):
    """Ingest jobs from Oracle Cloud HCM Candidate Experience endpoints."""

    id = "oracle"
    name = "Oracle Cloud Recruiting"
    source_type = "ats"
    priority = 95

    def supports(self, source_type: str, config: dict[str, Any] | None = None) -> bool:
        return source_type.lower() in ("oracle", "oraclecloud", "taleo")

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
        host = config.get("host", "eeho.fa.us2.oraclecloud.com")
        site = config.get("site", "jobsearch")
        # Oracle HCM REST API
        url = f"https://{host}/hcmRestApi/resources/latest/recruitingCEJobRequisitions?onlyData=true&finder=findReqs;siteNumber={site},facetsList=LOCATIONS%3BPOSTING_DATES"

        resp = await self.execute_request(client, url, timeout=20.0)
        if not resp or resp.status_code != 200:
            self.record_failure(f"HTTP {resp.status_code if resp else 'No response'}")
            return []

        try:
            data = resp.json()
            items = data.get("items", [])
            jobs: list[NormalizedJob] = []

            for item in items:
                title = item.get("Title", "")
                if not matches_title(title, compiled_patterns):
                    continue

                req_id = s(item.get("Id", ""))
                location = item.get("PrimaryLocation", "")
                posted = item.get("PostedDate", "")

                combined = f"{location} {title}".lower()
                is_remote = any(k in combined for k in ("remote", "virtual", "wfh"))
                is_hybrid = "hybrid" in combined
                remote_status = "REMOTE" if is_remote else ("HYBRID" if is_hybrid else "ONSITE")

                job_url = f"https://{host}/hcmUI/CandidateExperience/en/sites/{site}/job/{req_id}"

                normalized = NormalizedJob(
                    id=f"{company}:{req_id}",
                    external_id=req_id,
                    company=company,
                    company_name=config.get("company_name") or company.replace("-", " ").capitalize(),
                    title=title,
                    location=location,
                    locations=[location] if location else [],
                    remote=is_remote,
                    hybrid=is_hybrid,
                    remote_status=remote_status,
                    department=item.get("Department", ""),
                    source_url=job_url,
                    apply_url=job_url,
                    canonical_url=job_url,
                    description=strip_html(item.get("ExternalDescriptionStr", "")),
                    updated_at=posted,
                    first_published=posted,
                    employment_type=item.get("RegularOrTemporary", "Full-time"),
                    source="oracle",
                    source_type="ats",
                    source_priority=95,
                    source_quality=95,
                    extraction_method="oracle_hcm_api",
                    provenance_sources=["oracle"],
                    source_metadata={"requisition_id": req_id},
                )
                jobs.append(normalized)

            duration = (time.perf_counter() - start_time) * 1000
            self.record_success(len(jobs), duration)
            return jobs
        except Exception as exc:
            self.record_failure(exc)
            return []
