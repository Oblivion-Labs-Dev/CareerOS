"""Arbeitnow JobSourceAdapter implementation for CareerOS Job Ingestion V2."""

from __future__ import annotations

import time
from datetime import datetime
from typing import Any

import httpx

from app.services.job_discover.sources.base import JobSourceAdapter, NormalizedJob


class ArbeitnowSource(JobSourceAdapter):
    """Ingest jobs from Arbeitnow public keyless API."""

    id = "arbeitnow"
    name = "Arbeitnow Jobs"
    source_type = "public_api"
    priority = 80
    supports_incremental_sync = True

    def supports(self, source_type: str, config: dict[str, Any] | None = None) -> bool:
        return source_type.lower() in ("arbeitnow", "arbeitnow_api")

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
        url = "https://www.arbeitnow.com/api/job-board-api"

        resp = await self.execute_request(client, url, timeout=20.0)
        if not resp or resp.status_code != 200:
            self.record_failure(f"HTTP {resp.status_code if resp else 'No response'}")
            return []

        try:
            data = resp.json()
            postings = data.get("data", [])
            jobs: list[NormalizedJob] = []

            for item in postings:
                title = item.get("title", "")
                created_ts = item.get("created_at")
                ts = datetime.fromtimestamp(created_ts).isoformat() if isinstance(created_ts, (int, float)) else str(created_ts or "")

                if compiled_patterns and not matches_title(title, compiled_patterns):
                    continue
                if cutoff and ts and not is_recent(ts, cutoff):
                    continue

                slug = s(item.get("slug", ""))
                comp_name = item.get("company_name", "Unknown Company")
                raw_url = item.get("url", "")
                loc = item.get("location", "Remote")
                is_remote = bool(item.get("remote")) or "remote" in loc.lower()
                is_hybrid = "hybrid" in loc.lower()
                remote_status = "REMOTE" if is_remote else ("HYBRID" if is_hybrid else "ONSITE")

                # Sponsorship detection in tags or description
                tags = item.get("tags") or []
                desc = strip_html(item.get("description", ""))
                sponsorship_mention = bool(item.get("visa_sponsorship")) or any("visa" in str(t).lower() for t in tags)
                sponsorship_status = "yes" if item.get("visa_sponsorship") else None

                normalized = NormalizedJob(
                    id=f"arbeitnow:{slug or hash(raw_url)}",
                    external_id=slug,
                    company=comp_name.lower().replace(" ", "-"),
                    company_name=comp_name,
                    title=title,
                    location=loc,
                    locations=[loc],
                    remote=is_remote,
                    hybrid=is_hybrid,
                    remote_status=remote_status,
                    source_url=raw_url,
                    apply_url=raw_url,
                    canonical_url=raw_url,
                    description=desc,
                    updated_at=ts,
                    first_published=ts,
                    employment_type=", ".join(item.get("job_types") or ["Full-time"]),
                    skills=[str(t) for t in tags],
                    sponsorship_mention=sponsorship_mention,
                    sponsorship_status=sponsorship_status,
                    source="arbeitnow",
                    source_type="public_api",
                    source_priority=80,
                    source_quality=80,
                    extraction_method="arbeitnow_api",
                    provenance_sources=["arbeitnow"],
                )
                jobs.append(normalized)

            duration = (time.perf_counter() - start_time) * 1000
            self.record_success(len(jobs), duration)
            return jobs
        except Exception as exc:
            self.record_failure(exc)
            return []
