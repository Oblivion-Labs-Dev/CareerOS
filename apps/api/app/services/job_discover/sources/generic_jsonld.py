"""Generic career page crawler supporting JSON-LD and HTML link extraction."""

from __future__ import annotations

import json
import re
from datetime import datetime
from typing import Any
from urllib.parse import urljoin, urlparse

import httpx

from app.services.job_discover.sources.base import JobSource, NormalizedJob


def parse_jsonld_job_postings(html: str, base_url: str, company: str) -> list[NormalizedJob]:
    """Extract Schema.org JobPosting json-ld objects from HTML."""
    from app.services.job_discover.scraper_service import strip_html

    jobs: list[NormalizedJob] = []
    pattern = re.compile(r'<script[^>]*type=["\']application/ld\+json["\'][^>]*>(.*?)</script>', re.DOTALL | re.IGNORECASE)

    for match in pattern.finditer(html):
        try:
            data = json.loads(match.group(1).strip())
            items = data if isinstance(data, list) else [data]
            for item in items:
                if not isinstance(item, dict):
                    continue
                if item.get("@type") == "JobPosting" or "JobPosting" in item.get("@type", []):
                    title = str(item.get("title") or "").strip()
                    if not title:
                        continue

                    job_url = urljoin(base_url, str(item.get("url") or base_url))
                    desc = strip_html(str(item.get("description") or ""))

                    # Location extraction
                    loc_parts = []
                    job_loc = item.get("jobLocation")
                    if isinstance(job_loc, dict):
                        address = job_loc.get("address")
                        if isinstance(address, dict):
                            loc_parts.extend([
                                address.get("addressLocality"),
                                address.get("addressRegion"),
                                address.get("addressCountry"),
                            ])
                    location = ", ".join(p for p in loc_parts if p)

                    job_id = str(item.get("identifier", {}).get("value") if isinstance(item.get("identifier"), dict) else item.get("identifier") or hash(job_url))

                    jobs.append(
                        NormalizedJob(
                            id=f"{company}:{job_id}",
                            external_id=str(job_id),
                            company=company,
                            company_name=company.capitalize(),
                            title=title,
                            location=location,
                            source_url=job_url,
                            description=desc,
                            updated_at=str(item.get("datePosted") or ""),
                            first_published=str(item.get("datePosted") or ""),
                            employment_type=str(item.get("employmentType") or ""),
                            source="generic_jsonld",
                            extraction_method="jsonld",
                        )
                    )
        except Exception:
            continue
    return jobs


class GenericCareerPageSource(JobSource):
    """Fallback source extracting jobs via JSON-LD or static HTML anchor patterns."""

    id = "generic"
    name = "Generic Career Page"

    def supports(self, source_type: str, config: dict[str, Any] | None = None) -> bool:
        return source_type.lower() in {"generic", "auto", "jsonld", "html"}

    async def fetch_jobs(
        self,
        client: httpx.AsyncClient,
        company: str,
        config: dict[str, Any],
        compiled_patterns: list[Any],
        cutoff: datetime,
        role_keys: list[str] | None = None,
    ) -> list[NormalizedJob]:
        from app.services.job_discover.scraper_service import is_recent, matches_title

        careers_url = config.get("careersUrl") or config.get("url") or f"https://{company}.com/careers"

        try:
            resp = await client.get(careers_url, timeout=15)
            if resp.status_code != 200:
                return []

            html = resp.text
            jsonld_jobs = parse_jsonld_job_postings(html, careers_url, company)

            valid_jobs: list[NormalizedJob] = []
            for j in jsonld_jobs:
                if matches_title(j.title, compiled_patterns) and is_recent(j.updated_at, cutoff):
                    valid_jobs.append(j)

            return valid_jobs
        except Exception:
            return []
