"""Discover recent job postings through Google Programmable Search.

The highest-leverage use of a 100-query/day free tier. A per-job lookup spends
one query to resolve one posting already known; one *discovery* query returns
up to ten postings that were not in the pipeline at all — and because the search
engine is restricted to applyable ATS hosts, each result URL is already a page
an application can be filed on, so no second mapping step is needed.

`dateRestrict` keeps it pointed at new listings rather than re-surfacing the
same indexed pages every run, which is what makes this worth spending a daily
quota on at all.

Inert unless `GOOGLE_CSE_API_KEY` and `GOOGLE_CSE_ENGINE_ID` are configured.
"""

from __future__ import annotations

import time
from datetime import datetime
from typing import Any

import httpx

from app.services.job_discover.sources.base import JobSourceAdapter, NormalizedJob, SourceRole

# Each term costs quota, so this is a deliberately short, high-yield list rather
# than every title variant the filters accept. The shared title filter still
# governs what actually enters the queue.
DEFAULT_SEARCH_TERMS = (
    "Senior Software Engineer",
    "Staff Software Engineer",
    "Principal Software Engineer",
    "Backend Engineer",
    "Machine Learning Engineer",
)

# Leaves room in the 100/day budget for the residue resolver in LinkedInSource.
DEFAULT_PAGES_PER_TERM = 2
DEFAULT_DAYS_OLD = 7


class GoogleCseJobSource(JobSourceAdapter):
    """Pull recent applyable postings out of Google's index."""

    id = "google_cse"
    name = "Google Programmable Search (recent postings)"
    role = SourceRole.DISCOVERY
    source_type = "aggregator"
    priority = 60
    supports_incremental_sync = True

    def supports(self, source_type: str, config: dict[str, Any] | None = None) -> bool:
        return source_type.lower() in ("google_cse", "google_programmable_search")

    async def fetch_jobs(
        self,
        client: httpx.AsyncClient,
        company: str = "all",
        config: dict[str, Any] | None = None,
        compiled_patterns: list[Any] | None = None,
        cutoff: datetime | None = None,
        role_keys: list[str] | None = None,
    ) -> list[NormalizedJob]:
        from app.services.job_discover.google_cse_resolver import (
            get_usage,
            is_configured,
            search_recent_postings,
        )
        from app.services.job_discover.scraper_service import matches_title

        if not is_configured():
            return []

        started = time.perf_counter()
        cfg = config or {}
        terms = cfg.get("searchTerms") or DEFAULT_SEARCH_TERMS
        pages = int(cfg.get("pagesPerTerm") or DEFAULT_PAGES_PER_TERM)
        days_old = int(cfg.get("daysOld") or DEFAULT_DAYS_OLD)

        jobs: list[NormalizedJob] = []
        seen_urls: set[str] = set()

        from app.db.store import session_scope

        with session_scope() as db:
            for term in terms:
                used, budget = get_usage(db)
                if used >= budget:
                    break
                results = await search_recent_postings(
                    client, db, term, days_old=days_old, max_pages=pages
                )
                for item in results:
                    url = item["url"]
                    if url in seen_urls:
                        continue
                    title = self._clean_title(item["title"])
                    if compiled_patterns and not matches_title(title, compiled_patterns):
                        continue
                    seen_urls.add(url)
                    jobs.append(self._normalize(item, title))

        duration = (time.perf_counter() - started) * 1000
        self.record_success(len(jobs), duration)
        return jobs

    @staticmethod
    def _clean_title(raw: str) -> str:
        """Search result titles carry board furniture the filters should not see.

        e.g. "Senior Software Engineer - Affirm - Greenhouse" or
        "Job Application for Senior Engineer at Acme".
        """
        title = (raw or "").strip()
        for marker in (" - Greenhouse", " | Greenhouse", " - Lever", " | Lever", " - Ashby"):
            title = title.replace(marker, "")
        if title.lower().startswith("job application for "):
            title = title[len("job application for "):]
        for sep in (" at ", " - ", " | "):
            if sep in title:
                head = title.split(sep)[0].strip()
                # Only trim when the head still looks like a job title.
                if len(head) > 8:
                    title = head
                break
        return title.strip()

    @staticmethod
    def _normalize(item: dict[str, Any], title: str) -> NormalizedJob:
        url = item["url"]
        slug = (item.get("company") or "").strip()
        display = slug.replace("-", " ").replace("_", " ").title() if slug else "Unknown Company"
        snippet = item.get("snippet") or ""
        low = f"{title} {snippet}".lower()
        is_remote = "remote" in low
        is_hybrid = "hybrid" in low

        return NormalizedJob(
            id=f"google_cse:{abs(hash(url))}",
            external_id=url,
            company=(slug or display).lower().replace(" ", "-"),
            company_name=display,
            title=title,
            remote=is_remote,
            hybrid=is_hybrid,
            remote_status="REMOTE" if is_remote else ("HYBRID" if is_hybrid else "UNKNOWN"),
            source_url=url,
            apply_url=url,
            canonical_url=url,
            description=snippet,
            source="google_cse",
            source_type="aggregator",
            source_priority=60,
            source_quality=60,
            extraction_method="google_programmable_search",
            provenance_sources=["google_cse"],
            source_metadata={"hasDirectEmployerUrl": True, "viaSearchIndex": True},
        )
