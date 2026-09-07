"""Universal Structured Career Page Adapter with Schema.org/JobPosting JSON-LD and Sitemap Discovery."""

from __future__ import annotations

import json
import logging
import re
import xml.etree.ElementTree as ET
from datetime import UTC, datetime
from typing import Any
from urllib.parse import urljoin, urlparse

import httpx

from app.services.job_discover.sources.base import (
    JobSourceAdapter,
    NormalizedJob,
    SourceRole,
)

logger = logging.getLogger("career_os.job_discover.sources.structured_career_page")


def _clean_html_text(raw_html: str) -> str:
    """Clean HTML formatting into plain text while preserving paragraph structure."""
    if not raw_html:
        return ""
    text = re.sub(r"<(br|p|div|li)[^>]*>", "\n", raw_html, flags=re.I)
    text = re.sub(r"<[^>]+>", " ", text)
    text = re.sub(r"&nbsp;", " ", text)
    text = re.sub(r"&amp;", "&", text)
    text = re.sub(r"&lt;", "<", text)
    text = re.sub(r"&gt;", ">", text)
    text = re.sub(r"&quot;", '"', text)
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n\s*\n+", "\n\n", text)
    return text.strip()


def parse_jsonld_job_postings(html: str, base_url: str, company: str) -> list[NormalizedJob]:
    """Parse Schema.org JobPosting JSON-LD objects from raw HTML.

    Handles single objects, lists, and @graph hierarchies.
    Extracts title, description, datePosted, validThrough, employmentType, hiringOrganization,
    jobLocation, applicantLocationRequirements, jobLocationType, baseSalary, identifier, directApply.
    """
    jobs: list[NormalizedJob] = []
    script_pattern = re.compile(
        r'<script[^>]*type=["\']application/ld\+json["\'][^>]*>(.*?)</script>',
        re.DOTALL | re.IGNORECASE,
    )

    for match in script_pattern.finditer(html):
        content = match.group(1).strip()
        if not content:
            continue
        try:
            parsed = json.loads(content)
        except Exception:
            continue

        raw_items: list[dict[str, Any]] = []
        if isinstance(parsed, dict):
            if "@graph" in parsed and isinstance(parsed["@graph"], list):
                raw_items.extend([i for i in parsed["@graph"] if isinstance(i, dict)])
            else:
                raw_items.append(parsed)
        elif isinstance(parsed, list):
            raw_items.extend([i for i in parsed if isinstance(i, dict)])

        for item in raw_items:
            item_type = item.get("@type", "")
            is_job = False
            if isinstance(item_type, str) and item_type.lower() == "jobposting":
                is_job = True
            elif isinstance(item_type, list) and any(str(t).lower() == "jobposting" for t in item_type):
                is_job = True

            if not is_job:
                continue

            title = str(item.get("title") or item.get("name") or "").strip()
            if not title:
                continue

            job_url = urljoin(base_url, str(item.get("url") or base_url))
            direct_apply = bool(item.get("directApply", False))
            apply_url = str(item.get("applyUrl") or job_url)

            # Hiring Organization
            org = item.get("hiringOrganization")
            company_name = company
            if isinstance(org, dict):
                company_name = str(org.get("name") or company).strip()
            elif isinstance(org, str) and org.strip():
                company_name = org.strip()

            # Location parsing
            loc_parts: list[str] = []
            country = "US"
            city = ""
            state = ""
            job_loc = item.get("jobLocation")
            if isinstance(job_loc, dict):
                addr = job_loc.get("address")
                if isinstance(addr, dict):
                    city = str(addr.get("addressLocality") or "")
                    state = str(addr.get("addressRegion") or "")
                    country = str(addr.get("addressCountry") or "US")
                    if city:
                        loc_parts.append(city)
                    if state:
                        loc_parts.append(state)
                    if country and country != "US":
                        loc_parts.append(country)
                elif isinstance(addr, str) and addr.strip():
                    loc_parts.append(addr.strip())
            elif isinstance(job_loc, list):
                for l in job_loc:
                    if isinstance(l, dict) and "address" in l:
                        a = l["address"]
                        if isinstance(a, dict) and a.get("addressLocality"):
                            loc_parts.append(str(a["addressLocality"]))

            location = ", ".join(loc_parts) or "United States"

            # Remote / Telecommute
            job_loc_type = str(item.get("jobLocationType") or "").upper()
            applicant_reqs = str(item.get("applicantLocationRequirements") or "")
            remote = (
                "TELECOMMUTE" in job_loc_type
                or "remote" in location.lower()
                or "remote" in title.lower()
                or bool(applicant_reqs and "remote" in applicant_reqs.lower())
            )
            remote_status = "REMOTE" if remote else ("HYBRID" if "hybrid" in location.lower() else "ONSITE")

            # Salary extraction
            salary_min: float | None = None
            salary_max: float | None = None
            salary_currency = "USD"
            base_sal = item.get("baseSalary")
            if isinstance(base_sal, dict):
                salary_currency = str(base_sal.get("currency") or "USD")
                val = base_sal.get("value")
                if isinstance(val, (int, float)):
                    salary_min = float(val)
                elif isinstance(val, dict):
                    if "minValue" in val and val["minValue"] is not None:
                        try:
                            salary_min = float(val["minValue"])
                        except (ValueError, TypeError):
                            pass
                    if "maxValue" in val and val["maxValue"] is not None:
                        try:
                            salary_max = float(val["maxValue"])
                        except (ValueError, TypeError):
                            pass

            salary_range = ""
            if salary_min and salary_max:
                salary_range = f"${salary_min:,.0f} - ${salary_max:,.0f} {salary_currency}"
            elif salary_min:
                salary_range = f"${salary_min:,.0f}+ {salary_currency}"

            # Identifier
            ident = item.get("identifier")
            job_id = ""
            if isinstance(ident, dict):
                job_id = str(ident.get("value") or "")
            elif ident:
                job_id = str(ident)
            if not job_id:
                job_id = str(abs(hash(f"{title}:{job_url}")))

            # Dates
            date_posted = str(item.get("datePosted") or "")
            valid_through = str(item.get("validThrough") or "")

            # Description
            raw_desc = str(item.get("description") or "")
            clean_desc = _clean_html_text(raw_desc)

            jobs.append(
                NormalizedJob(
                    id=f"{company.lower()}:{job_id}",
                    external_id=job_id,
                    company=company.lower(),
                    company_name=company_name,
                    title=title,
                    location=location,
                    city=city,
                    state=state,
                    country=country,
                    remote=remote,
                    remote_status=remote_status,
                    salary_min=salary_min,
                    salary_max=salary_max,
                    salary_currency=salary_currency,
                    salary_range=salary_range,
                    description=clean_desc,
                    description_format="text",
                    employment_type=str(item.get("employmentType") or "FULL_TIME"),
                    source="structured_career_page",
                    source_type="ats",
                    source_priority=75,
                    source_quality=80,
                    source_url=job_url,
                    apply_url=apply_url,
                    canonical_url=job_url,
                    first_published=date_posted,
                    updated_at=date_posted,
                    extraction_method="jsonld",
                    source_metadata={
                        "validThrough": valid_through,
                        "directApply": direct_apply,
                        "jobLocationType": job_loc_type,
                    },
                )
            )

    return jobs


async def discover_sitemap_urls(client: httpx.AsyncClient, base_url: str) -> list[str]:
    """Discover job URLs via robots.txt and sitemap.xml inspection."""
    parsed = urlparse(base_url)
    root_origin = f"{parsed.scheme}://{parsed.netloc}"
    job_urls: list[str] = []

    sitemap_candidates: list[str] = []

    # 1. Check robots.txt for Sitemap directives
    try:
        robots_resp = await client.get(f"{root_origin}/robots.txt", timeout=8)
        if robots_resp.status_code == 200:
            for line in robots_resp.text.splitlines():
                if line.lower().startswith("sitemap:"):
                    sm_url = line.split(":", 1)[1].strip()
                    if sm_url.startswith("http"):
                        sitemap_candidates.append(sm_url)
    except Exception:
        pass

    # 2. Add standard sitemap locations
    standard_sitemaps = [
        f"{root_origin}/jobs-sitemap.xml",
        f"{root_origin}/careers-sitemap.xml",
        f"{root_origin}/sitemap-jobs.xml",
        f"{root_origin}/sitemap.xml",
    ]
    for sm in standard_sitemaps:
        if sm not in sitemap_candidates:
            sitemap_candidates.append(sm)

    # 3. Probe candidate sitemaps
    for sm_url in sitemap_candidates[:3]:
        try:
            resp = await client.get(sm_url, timeout=10)
            if resp.status_code == 200 and ("<urlset" in resp.text or "<sitemapindex" in resp.text):
                root = ET.fromstring(resp.content)
                # XML namespace handling
                namespaces = {"ns": "http://www.sitemaps.org/schemas/sitemap/0.9"}
                for loc in root.findall(".//ns:loc", namespaces) or root.findall(".//loc"):
                    loc_text = (loc.text or "").strip()
                    if any(kw in loc_text.lower() for kw in ("/job/", "/jobs/", "/career/", "/careers/", "/opening/", "/position/")):
                        job_urls.append(loc_text)
                    if len(job_urls) >= 25:
                        break
                if job_urls:
                    break
        except Exception:
            continue

    return job_urls


class StructuredCareerPageAdapter(JobSourceAdapter):
    """Universal employer career page adapter leveraging Schema.org/JobPosting JSON-LD and sitemap discovery."""

    id = "structured_career_page"
    name = "Structured Career Page (Schema.org / Sitemap)"
    role = SourceRole.FALLBACK
    source_type = "ats"
    priority = 75

    def supports(self, source_type: str, config: dict[str, Any] | None = None) -> bool:
        return source_type.lower() in {
            "structured_career_page",
            "generic",
            "jsonld",
            "sitemap",
            "generic_jsonld",
        }

    async def fetch_jobs(
        self,
        client: httpx.AsyncClient,
        company: str,
        config: dict[str, Any],
        compiled_patterns: list[Any],
        cutoff: datetime,
        role_keys: list[str] | None = None,
    ) -> list[NormalizedJob]:
        start_time = datetime.now(UTC)
        careers_url = config.get("careersUrl") or config.get("url") or f"https://{company}.com/careers"

        from app.services.job_discover.scraper_service import is_recent, matches_title

        discovered_jobs: list[NormalizedJob] = []

        try:
            # 1. Fetch main careers page
            resp = await self.execute_request(client, careers_url, timeout=15.0)
            if resp and resp.status_code == 200:
                html = resp.text
                jsonld_jobs = parse_jsonld_job_postings(html, careers_url, company)
                for j in jsonld_jobs:
                    if matches_title(j.title, compiled_patterns) and is_recent(j.updated_at, cutoff):
                        discovered_jobs.append(j)

            # 2. If no jobs found on main page, attempt sitemap discovery
            if not discovered_jobs:
                sitemap_job_urls = await discover_sitemap_urls(client, careers_url)
                for job_url in sitemap_job_urls[:8]:
                    job_page_resp = await self.execute_request(client, job_url, timeout=10.0)
                    if job_page_resp and job_page_resp.status_code == 200:
                        parsed_page_jobs = parse_jsonld_job_postings(job_page_resp.text, job_url, company)
                        for pj in parsed_page_jobs:
                            if matches_title(pj.title, compiled_patterns) and is_recent(pj.updated_at, cutoff):
                                discovered_jobs.append(pj)
                                if len(discovered_jobs) >= 20:
                                    break
                    if len(discovered_jobs) >= 20:
                        break

            duration_ms = (datetime.now(UTC) - start_time).total_seconds() * 1000.0
            self.record_success(len(discovered_jobs), duration_ms)
            return discovered_jobs
        except Exception as exc:
            duration_ms = (datetime.now(UTC) - start_time).total_seconds() * 1000.0
            self.record_failure(exc, duration_ms)
            return []
