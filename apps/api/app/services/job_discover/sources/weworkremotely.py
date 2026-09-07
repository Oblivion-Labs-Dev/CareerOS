"""We Work Remotely (WWR) RSS Feed Adapter for CareerOS Job Ingestion V2."""

from __future__ import annotations

import logging
import re
import xml.etree.ElementTree as ET
from datetime import UTC, datetime
from email.utils import parsedate_to_datetime
from typing import Any

import httpx

from app.services.job_discover.sources.base import (
    JobSourceAdapter,
    NormalizedJob,
    SourceRole,
)

logger = logging.getLogger("career_os.job_discover.sources.weworkremotely")


class WeWorkRemotelySource(JobSourceAdapter):
    """We Work Remotely official RSS developer jobs feed adapter."""

    id = "weworkremotely"
    name = "We Work Remotely Feed"
    role = SourceRole.DISCOVERY
    source_type = "direct_feed"
    priority = 85

    FEED_URLS = [
        "https://weworkremotely.com/categories/remote-programming-jobs.rss",
        "https://weworkremotely.com/categories/remote-devops-sysadmin-jobs.rss",
    ]

    def supports(self, source_type: str, config: dict[str, Any] | None = None) -> bool:
        return source_type.lower() in ("weworkremotely", "wwr", "weworkremotely_feed")

    async def fetch_jobs(
        self,
        client: httpx.AsyncClient,
        company: str,
        config: dict[str, Any],
        compiled_patterns: list[Any],
        cutoff: datetime,
        role_keys: list[str] | None = None,
    ) -> list[NormalizedJob]:
        from app.services.job_discover.scraper_service import is_recent, matches_title, strip_html

        start_time = datetime.now(UTC)
        discovered_jobs: list[NormalizedJob] = []
        seen_ids: set[str] = set()

        headers = {
            "User-Agent": "CareerOS-JobIngestion/2.0 (+https://careeros.dev)",
            "Accept": "application/rss+xml, application/xml, text/xml",
        }

        urls_to_fetch = [config.get("feedUrl")] if config.get("feedUrl") else self.FEED_URLS

        for feed_url in urls_to_fetch:
            try:
                resp = await self.execute_request(client, feed_url, headers=headers, timeout=15.0)
                if not resp or resp.status_code != 200:
                    continue

                root = ET.fromstring(resp.content)
                channel = root.find("channel")
                items = channel.findall("item") if channel is not None else root.findall(".//item")

                for item in items:
                    raw_title = (item.findtext("title") or "").strip()
                    link = (item.findtext("link") or "").strip()
                    guid = (item.findtext("guid") or link or hash(raw_title)).strip()
                    if guid in seen_ids:
                        continue
                    seen_ids.add(guid)
                    pub_date_raw = item.findtext("pubDate") or ""
                    description_raw = item.findtext("description") or ""

                    # WWR titles are structured as "CompanyName: JobTitle"
                    if ":" in raw_title:
                        comp_part, title_part = raw_title.split(":", 1)
                        company_name = comp_part.strip()
                        job_title = title_part.strip()
                    else:
                        company_name = "WWR Employer"
                        job_title = raw_title

                    if not job_title or not matches_title(job_title, compiled_patterns):
                        continue

                    # Date parsing
                    pub_date_iso = ""
                    if pub_date_raw:
                        try:
                            dt = parsedate_to_datetime(pub_date_raw)
                            pub_date_iso = dt.astimezone(UTC).isoformat()
                        except Exception:
                            pub_date_iso = pub_date_raw

                    if not is_recent(pub_date_iso, cutoff):
                        continue

                    clean_desc = strip_html(description_raw)

                    discovered_jobs.append(
                        NormalizedJob(
                            id=f"wwr:{guid.split('/')[-1]}",
                            external_id=guid,
                            company=company_name.lower().replace(" ", "-"),
                            company_name=company_name,
                            title=job_title,
                            location="Remote",
                            remote=True,
                            remote_status="REMOTE",
                            description=clean_desc,
                            employment_type="FULL_TIME",
                            source="weworkremotely",
                            source_type="direct_feed",
                            source_priority=85,
                            source_quality=85,
                            source_url=link,
                            apply_url=link,
                            canonical_url=link,
                            first_published=pub_date_iso,
                            updated_at=pub_date_iso,
                            extraction_method="feed",
                        )
                    )

            except Exception as exc:
                logger.warning("Error fetching WWR feed %s: %s", feed_url, exc)
                continue

        duration_ms = (datetime.now(UTC) - start_time).total_seconds() * 1000.0
        self.record_success(len(discovered_jobs), duration_ms)
        return discovered_jobs
