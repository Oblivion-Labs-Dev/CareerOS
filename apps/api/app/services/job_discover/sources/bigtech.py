"""Big Tech Direct Employer JobSourceAdapter for CareerOS Job Ingestion V2."""

from __future__ import annotations

import time
from datetime import datetime
from typing import Any

import httpx

from app.services.job_discover import bigtech_scrapers
from app.services.job_discover.sources.base import JobSourceAdapter, NormalizedJob


class BigTechSourceAdapter(JobSourceAdapter):
    """Ingest jobs directly from Big Tech career systems: Google, Apple, Meta, Amazon, Microsoft, Netflix."""

    id = "bigtech"
    name = "Big Tech Direct (Google, Apple, Meta, Amazon, Microsoft, Netflix)"
    source_type = "company_api"
    priority = 100
    supports_incremental_sync = True

    def supports(self, source_type: str, config: dict[str, Any] | None = None) -> bool:
        return source_type.lower() in (
            "bigtech",
            "google",
            "apple",
            "meta",
            "amazon",
            "microsoft",
            "netflix",
        )

    async def fetch_jobs(
        self,
        client: httpx.AsyncClient,
        company: str = "all",
        config: dict[str, Any] | None = None,
        compiled_patterns: list[Any] | None = None,
        cutoff: datetime | None = None,
        role_keys: list[str] | None = None,
    ) -> list[NormalizedJob]:
        start_time = time.perf_counter()
        search_terms = None
        if role_keys:
            role_map = {
                "pm": "Product Manager",
                "swe": "Software Engineer",
                "ux": "UX Designer",
                "tpm": "Program Manager",
                "product": "Product",
                "presales": "Solutions Engineer",
            }
            search_terms = [role_map[k] for k in role_keys if k in role_map]

        try:
            target = company.lower() if company and company != "all" else None
            raw_jobs: list[dict[str, Any]] = []

            if target == "google":
                raw_jobs = await bigtech_scrapers.scrape_google(client, search_terms=search_terms)
            elif target == "apple":
                raw_jobs = await bigtech_scrapers.scrape_apple(client, search_terms=search_terms)
            elif target == "meta":
                raw_jobs = await bigtech_scrapers.scrape_meta(client, search_terms=search_terms)
            elif target == "amazon":
                raw_jobs = await bigtech_scrapers.scrape_amazon(client, search_terms=search_terms)
            elif target == "microsoft":
                raw_jobs = await bigtech_scrapers.scrape_microsoft(client, search_terms=search_terms)
            elif target == "netflix":
                raw_jobs = await bigtech_scrapers.scrape_netflix(client, search_terms=search_terms)
            else:
                raw_jobs = await bigtech_scrapers.scrape_bigtech(search_terms=search_terms)

            jobs: list[NormalizedJob] = []
            for item in raw_jobs:
                title = item.get("title", "")
                comp = item.get("company", target or "bigtech")
                loc = item.get("location", "United States")
                url = item.get("url", "")
                ext_id = str(item.get("greenhouse_id") or item.get("id") or hash(url))

                combined = f"{loc} {title}".lower()
                is_remote = any(k in combined for k in ("remote", "virtual", "wfh"))
                is_hybrid = "hybrid" in combined
                remote_status = "REMOTE" if is_remote else ("HYBRID" if is_hybrid else "ONSITE")

                normalized = NormalizedJob(
                    id=f"{comp}:{ext_id}",
                    external_id=ext_id,
                    company=comp,
                    company_name=comp.capitalize(),
                    title=title,
                    location=loc,
                    locations=[loc],
                    remote=is_remote,
                    hybrid=is_hybrid,
                    remote_status=remote_status,
                    source_url=url,
                    apply_url=url,
                    canonical_url=url,
                    description=item.get("description", ""),
                    updated_at=item.get("updated_at", ""),
                    first_published=item.get("first_published", ""),
                    employment_type=item.get("employment_type", "Full-time"),
                    salary_range=item.get("salary_range", ""),
                    source=f"{comp}_careers" if target else "bigtech",
                    source_type="company_api",
                    source_priority=100,
                    source_quality=100,
                    extraction_method="direct_career_site",
                    provenance_sources=[f"{comp}_careers"],
                )
                jobs.append(normalized)

            duration = (time.perf_counter() - start_time) * 1000
            self.record_success(len(jobs), duration)
            return jobs
        except Exception as exc:
            self.record_failure(exc)
            return []
