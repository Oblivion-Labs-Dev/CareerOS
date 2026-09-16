"""The Muse JobSourceAdapter implementation for CareerOS Job Ingestion V2."""

from __future__ import annotations

import time
from datetime import datetime
from typing import Any

import httpx

from app.services.job_discover.sources.base import JobSourceAdapter, NormalizedJob


class TheMuseSource(JobSourceAdapter):
    """Ingest jobs from The Muse's public, keyless jobs API.

    Verified 2026-09-15: `https://www.themuse.com/api/public/jobs` is real and
    documented (https://www.themuse.com/developers/api/v2), works without an
    api_key up to 500 requests/hour (live-tested, 400K+ total postings). The
    `category` query param's exact controlled-vocabulary values weren't
    reliably reproducible in testing, so this fetches unfiltered pages and
    relies on the same title-pattern matching every other source uses.
    """

    id = "themuse"
    name = "The Muse"
    source_type = "public_api"
    priority = 80
    MAX_PAGES = 5

    def supports(self, source_type: str, config: dict[str, Any] | None = None) -> bool:
        return source_type.lower() in ("themuse", "the_muse")

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
        base_url = "https://www.themuse.com/api/public/jobs"
        jobs: list[NormalizedJob] = []
        seen_ids: set[str] = set()

        try:
            for page in range(self.MAX_PAGES):
                resp = await self.execute_request(
                    client, base_url, params={"page": page}, timeout=20.0,
                )
                if not resp or resp.status_code != 200:
                    if page == 0:
                        self.record_failure(f"HTTP {resp.status_code if resp else 'No response'}")
                        return []
                    break

                data = resp.json()
                results = data.get("results", [])
                if not results:
                    break

                for item in results:
                    item_id = s(item.get("id", ""))
                    if not item_id or item_id in seen_ids:
                        continue
                    seen_ids.add(item_id)

                    title = (item.get("name") or "").strip()
                    pub_date = item.get("publication_date", "")

                    if compiled_patterns and not matches_title(title, compiled_patterns):
                        continue
                    if cutoff and pub_date and not is_recent(pub_date, cutoff):
                        continue

                    locations = item.get("locations") or []
                    loc_names = [loc.get("name", "") for loc in locations if isinstance(loc, dict) and loc.get("name")]
                    location = loc_names[0] if loc_names else "Remote"
                    is_remote = any("remote" in name.lower() or "flexible" in name.lower() for name in loc_names)

                    company_info = item.get("company") or {}
                    comp_name = company_info.get("name") or "Unknown Company"
                    comp_slug = company_info.get("short_name") or comp_name.lower().replace(" ", "-")

                    levels = item.get("levels") or []
                    level_name = levels[0].get("name", "") if levels and isinstance(levels[0], dict) else ""

                    landing_page = (item.get("refs") or {}).get("landing_page", "")

                    normalized = NormalizedJob(
                        id=f"themuse:{item_id}",
                        external_id=item_id,
                        company=comp_slug,
                        company_name=comp_name,
                        title=title,
                        location=location,
                        locations=loc_names,
                        remote=is_remote,
                        remote_status="REMOTE" if is_remote else "UNKNOWN",
                        workplace_type="remote" if is_remote else "",
                        seniority=(level_name.replace(" Level", "").upper() or "MID"),
                        source_url=landing_page,
                        apply_url=landing_page,
                        canonical_url=landing_page,
                        description=strip_html(item.get("contents", "")),
                        first_published=pub_date,
                        updated_at=pub_date,
                        source="themuse",
                        source_type="public_api",
                        source_priority=80,
                        source_quality=80,
                        extraction_method="themuse_api",
                        provenance_sources=["themuse"],
                    )
                    jobs.append(normalized)

                if page + 1 >= data.get("page_count", 1):
                    break

            duration = (time.perf_counter() - start_time) * 1000
            self.record_success(len(jobs), duration)
            return jobs
        except Exception as exc:
            self.record_failure(exc)
            return []
