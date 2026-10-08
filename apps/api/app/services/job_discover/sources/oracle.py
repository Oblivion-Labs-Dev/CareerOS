"""Oracle Cloud Recruiting / Taleo JobSourceAdapter for CareerOS Job Ingestion V2."""

from __future__ import annotations

import time
from datetime import datetime
from typing import Any

import httpx

from app.services.job_discover.sources.base import JobSourceAdapter, NormalizedJob

_PAGE_SIZE = 100


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
        keyword = config.get("keyword") or ""
        max_results = int(config.get("max_results") or 500)
        self.last_total: int | None = None

        # The search returns one wrapper item per call whose requisitionList
        # holds the page of postings; TotalJobsCount is the full match count.
        requisitions: list[dict[str, Any]] = []
        offset = 0
        try:
            while len(requisitions) < max_results:
                finder = f"findReqs;siteNumber={site},limit={_PAGE_SIZE},offset={offset},sortBy=POSTING_DATES_DESC"
                if keyword:
                    finder += f",keyword={keyword}"
                resp = await self.execute_request(
                    client,
                    f"https://{host}/hcmRestApi/resources/latest/recruitingCEJobRequisitions",
                    params={"onlyData": "true", "expand": "requisitionList.secondaryLocations", "finder": finder},
                    timeout=20.0,
                )
                if not resp or resp.status_code != 200:
                    if not requisitions:
                        self.record_failure(f"HTTP {resp.status_code if resp else 'No response'}")
                        return []
                    break
                wrapper = (resp.json().get("items") or [{}])[0]
                if self.last_total is None and wrapper.get("TotalJobsCount") is not None:
                    self.last_total = int(wrapper["TotalJobsCount"])
                page = wrapper.get("requisitionList") or []
                requisitions.extend(page)
                offset += len(page)
                if not page or (self.last_total is not None and offset >= self.last_total):
                    break

            jobs: list[NormalizedJob] = []
            for item in requisitions[:max_results]:
                title = item.get("Title", "")
                if compiled_patterns and not matches_title(title, compiled_patterns):
                    continue

                req_id = s(item.get("Id", ""))
                location = item.get("PrimaryLocation", "")
                secondary = [loc.get("Name") for loc in item.get("secondaryLocations") or [] if isinstance(loc, dict) and loc.get("Name")]
                locations = [loc for loc in [location, *secondary] if loc]
                posted = item.get("PostedDate", "")

                combined = f"{' '.join(locations)} {title} {item.get('WorkplaceType') or ''}".lower()
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
                    location=" | ".join(locations),
                    locations=locations,
                    remote=is_remote,
                    hybrid=is_hybrid,
                    remote_status=remote_status,
                    department=item.get("Department") or "",
                    source_url=job_url,
                    apply_url=job_url,
                    canonical_url=job_url,
                    description=strip_html(item.get("ExternalDescriptionStr") or item.get("ShortDescriptionStr") or ""),
                    updated_at=posted,
                    first_published=posted,
                    employment_type=item.get("RegularOrTemporary") or "Full-time",
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
