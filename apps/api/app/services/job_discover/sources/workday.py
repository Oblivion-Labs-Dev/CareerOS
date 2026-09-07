"""Workday JobSourceAdapter implementation for CareerOS Job Ingestion V2."""

from __future__ import annotations

import re
import time
from datetime import datetime
from typing import Any

import httpx

from app.services.job_discover.sources.base import JobSourceAdapter, NormalizedJob


class WorkdaySource(JobSourceAdapter):
    """Ingest jobs from Workday CXS JSON endpoints."""

    id = "workday"
    name = "Workday"
    source_type = "ats"
    priority = 95

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

        start_time = time.perf_counter()
        host = config.get("host", "")
        wd_company = config.get("company") or config.get("tenant") or company
        board = config.get("board") or config.get("site") or "careers"

        if not host:
            self.record_failure("Missing host in Workday config")
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
            resp = await self.execute_request(
                client,
                url,
                method="POST",
                headers=wd_headers,
                json_data=payload,
                timeout=20.0,
            )
            if not resp or resp.status_code not in (200, 201):
                if not all_jobs:
                    self.record_failure(f"HTTP {resp.status_code if resp else 'No response'}")
                break

            try:
                data = resp.json()
                postings = data.get("jobPostings", [])
                if not postings:
                    break

                for job in postings:
                    title = job.get("title", "")
                    if compiled_patterns and not matches_title(title, compiled_patterns):
                        continue

                    ext_path = job.get("externalPath", "")
                    job_url = f"https://{host}{ext_path}" if ext_path else ""

                    # Requisition ID extraction from bulletFields or path
                    bullets = job.get("bulletFields") or []
                    req_id = ""
                    for b in bullets:
                        # Requisition IDs typically look like "R-12345", "JR-001", "REQ-10" or digits
                        if re.search(r"\b(?:[A-Z]{1,4}[-_])?\d{4,9}\b", str(b)):
                            req_id = str(b).strip()
                            break
                    if not req_id and ext_path:
                        match = re.search(r"/(?:job/)?([^/]+)$", ext_path)
                        if match:
                            req_id = match.group(1)

                    location_parts = [loc.strip() for loc in (job.get("locationsText") or "").split("|") if loc.strip()]
                    primary_location = location_parts[0] if location_parts else ""

                    # Remote / workplace type detection
                    loc_text = " ".join(location_parts).lower()
                    combined_text = f"{loc_text} {title.lower()} {str(job.get('timeType') or '').lower()}"
                    is_remote = any(k in combined_text for k in ("remote", "virtual", "wfh", "telecommute"))
                    is_hybrid = "hybrid" in combined_text
                    remote_status = "REMOTE" if is_remote else ("HYBRID" if is_hybrid else "ONSITE")

                    job_identifier = req_id or ext_path or title
                    normalized = NormalizedJob(
                        id=f"{company}:{job_identifier}",
                        external_id=req_id or job_identifier,
                        company=company,
                        company_name=config.get("company_name") or company.replace("-", " ").capitalize(),
                        title=title,
                        location=primary_location,
                        locations=location_parts,
                        remote=is_remote,
                        hybrid=is_hybrid,
                        remote_status=remote_status,
                        department="",
                        source_url=job_url,
                        apply_url=job_url,
                        canonical_url=job_url,
                        description="",  # Workday list API does not include full description
                        updated_at="",
                        first_published=job.get("postedOn", ""),
                        employment_type=job.get("timeType", "Full-time"),
                        salary_range="",
                        source="workday",
                        source_type="ats",
                        source_priority=95,
                        source_quality=95,
                        extraction_method="workday_cxs_api",
                        provenance_sources=["workday"],
                        source_metadata={
                            "requisition_id": req_id,
                            "external_path": ext_path,
                            "tenant": wd_company,
                            "site": board,
                        },
                    )
                    all_jobs.append(normalized)

                total = data.get("total", 0)
                offset += limit
                if offset >= total or offset >= 200:  # Workday cap per sync
                    break

            except Exception as exc:
                self.record_failure(exc)
                break

        duration = (time.perf_counter() - start_time) * 1000
        if all_jobs:
            self.record_success(len(all_jobs), duration)
        return all_jobs
