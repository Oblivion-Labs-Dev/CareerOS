"""Personio JobSourceAdapter implementation for CareerOS Job Ingestion V2."""

from __future__ import annotations

import time
import xml.etree.ElementTree as ET
from datetime import datetime
from typing import Any

import httpx

from app.services.job_discover.sources.base import JobSourceAdapter, NormalizedJob


class PersonioSource(JobSourceAdapter):
    """Ingest jobs from Personio's public, keyless per-company XML feed.

    Verified 2026-09-15: `https://{slug}.jobs.personio.de/xml?language=en` is
    Personio's own documented feed (https://developer.personio.de/v1.0/reference/get_xml)
    - no auth required, confirmed live against a real board (personio.jobs.personio.de).
    Opt-in per company (Settings > Recruiting > Career page > Activations), so not
    every Personio customer has it enabled; a 307/404 just means it isn't turned on.
    """

    id = "personio"
    name = "Personio"
    source_type = "ats"
    priority = 95

    def supports(self, source_type: str, config: dict[str, Any] | None = None) -> bool:
        return source_type.lower() == "personio"

    async def fetch_jobs(
        self,
        client: httpx.AsyncClient,
        company: str,
        config: dict[str, Any],
        compiled_patterns: list[Any],
        cutoff: datetime,
        role_keys: list[str] | None = None,
    ) -> list[NormalizedJob]:
        from app.services.job_discover.scraper_service import is_recent, matches_title, s, strip_html

        start_time = time.perf_counter()
        slug = config.get("slug") or config.get("boardId") or company
        url = f"https://{slug}.jobs.personio.de/xml?language=en"

        resp = await self.execute_request(client, url, timeout=20.0)
        if not resp or resp.status_code != 200:
            self.record_failure(f"HTTP {resp.status_code if resp else 'No response'}")
            return []

        try:
            root = ET.fromstring(resp.content)
            jobs: list[NormalizedJob] = []

            for position in root.findall(".//position"):
                position_id = s((position.findtext("id") or "").strip())
                title = (position.findtext("name") or "").strip()
                ts = (position.findtext("createdAt") or "").strip()
                if compiled_patterns and not matches_title(title, compiled_patterns):
                    continue
                if not is_recent(ts, cutoff):
                    continue

                office = (position.findtext("office") or "").strip()
                all_offices = [office] if office else []
                for extra in position.findall("additionalOffices/office"):
                    name = (extra.text or "").strip()
                    if name and name not in all_offices:
                        all_offices.append(name)

                combined_text = " ".join(all_offices).lower()
                is_remote = "remote" in combined_text
                is_hybrid = "hybrid" in combined_text
                remote_status = "REMOTE" if is_remote else ("HYBRID" if is_hybrid else "ONSITE")
                workplace_type = "remote" if is_remote else ("hybrid" if is_hybrid else "")

                description_parts = []
                for desc in position.findall("jobDescriptions/jobDescription"):
                    section_name = (desc.findtext("name") or "").strip()
                    section_value = strip_html((desc.findtext("value") or "").strip())
                    if section_value:
                        description_parts.append(f"{section_name}\n{section_value}" if section_name else section_value)
                description = "\n\n".join(description_parts)

                employment_type = (position.findtext("employmentType") or "Full-time").strip()
                department = (position.findtext("department") or position.findtext("recruitingCategory") or "").strip()
                apply_url = f"https://{slug}.jobs.personio.de/job/{position_id}"

                normalized = NormalizedJob(
                    id=f"{company}:{position_id}",
                    external_id=position_id,
                    company=company,
                    company_name=config.get("company_name") or company.replace("-", " ").capitalize(),
                    title=title,
                    location=office,
                    locations=all_offices,
                    remote=is_remote,
                    hybrid=is_hybrid,
                    remote_status=remote_status,
                    workplace_type=workplace_type,
                    department=department,
                    team=(position.findtext("occupationCategory") or "").strip(),
                    source_url=apply_url,
                    apply_url=apply_url,
                    canonical_url=apply_url,
                    description=description,
                    first_published=ts,
                    employment_type=employment_type,
                    seniority=(position.findtext("seniority") or "MID").upper(),
                    source="personio",
                    source_type="ats",
                    source_priority=95,
                    source_quality=95,
                    extraction_method="personio_xml",
                    provenance_sources=["personio"],
                )
                jobs.append(normalized)

            duration = (time.perf_counter() - start_time) * 1000
            self.record_success(len(jobs), duration)
            return jobs
        except ET.ParseError as exc:
            self.record_failure(exc)
            return []
        except Exception as exc:
            self.record_failure(exc)
            return []
