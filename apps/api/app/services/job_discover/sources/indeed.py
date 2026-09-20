"""Indeed ingestion via its mobile GraphQL endpoint.

Indeed is treated as a *discovery* source, not a payload source: almost every
result carries `recruit.viewJobUrl`, the employer's own application URL, which
is what the ATS scrapers and the Greenhouse/Lever handling downstream actually
want. Measured on a live pull of 300 postings, 100% had one, and a large share
resolved to `job-boards.greenhouse.io/...` either directly or through Indeed's
`grnh.se` short links.

Request mechanics adapted from JobSpy (MIT) — see `_vendored_jobspy/`.
"""

from __future__ import annotations

import time
from datetime import datetime
from typing import Any

import httpx

from app.services.job_discover.sources._vendored_jobspy import (
    INDEED_API_HEADERS,
    INDEED_API_URL,
    INDEED_JOB_SEARCH_QUERY,
    build_indeed_date_filter,
)
from app.services.job_discover.sources.base import JobSourceAdapter, NormalizedJob, SourceRole

# Indeed's relevance ranking is loose, so several narrow queries beat one broad
# one. Every result is still put through the shared title filter below.
DEFAULT_SEARCH_TERMS = (
    "Senior Software Engineer",
    "Staff Software Engineer",
    "Principal Software Engineer",
    "Software Development Engineer",
    "Backend Engineer",
    "Machine Learning Engineer",
)

_MAX_PAGES_PER_TERM = 3
_RESULTS_PER_PAGE = 100


class IndeedSource(JobSourceAdapter):
    """Ingest US postings from Indeed's public mobile GraphQL API."""

    id = "indeed"
    name = "Indeed"
    role = SourceRole.AGGREGATOR
    source_type = "aggregator"
    priority = 60
    supports_incremental_sync = True
    rate_limit_delay_sec = 0.5

    def supports(self, source_type: str, config: dict[str, Any] | None = None) -> bool:
        return source_type.lower() in ("indeed", "indeed_graphql")

    async def fetch_jobs(
        self,
        client: httpx.AsyncClient,
        company: str = "all",
        config: dict[str, Any] | None = None,
        compiled_patterns: list[Any] | None = None,
        cutoff: datetime | None = None,
        role_keys: list[str] | None = None,
    ) -> list[NormalizedJob]:
        from app.services.job_discover.scraper_service import matches_title, strip_html

        started = time.perf_counter()
        cfg = config or {}
        search_terms = cfg.get("searchTerms") or DEFAULT_SEARCH_TERMS
        location = cfg.get("location") or "United States"
        hours_old = int(cfg.get("hoursOld") or 168)

        jobs: list[NormalizedJob] = []
        seen_keys: set[str] = set()

        for term in search_terms:
            cursor: str | None = None
            for _ in range(_MAX_PAGES_PER_TERM):
                page, cursor = await self._fetch_page(client, term, location, hours_old, cursor)
                if not page:
                    break
                for raw in page:
                    job = raw.get("job") or {}
                    key = str(job.get("key") or "")
                    if not key or key in seen_keys:
                        continue
                    title = str(job.get("title") or "")
                    if compiled_patterns and not matches_title(title, compiled_patterns):
                        continue
                    seen_keys.add(key)
                    normalized = self._normalize(job, key, title, strip_html)
                    if normalized:
                        jobs.append(normalized)
                if not cursor:
                    break

        await self._resolve_tracking_links(client, jobs)

        duration = (time.perf_counter() - started) * 1000
        self.record_success(len(jobs), duration)
        return jobs

    @staticmethod
    async def _resolve_tracking_links(client: httpx.AsyncClient, jobs: list[NormalizedJob]) -> None:
        """Replace tracking hops with the employer URL they land on.

        Done in one batch after the pages are in, so the redirect requests are
        bounded and de-duplicated rather than issued per posting mid-scrape.
        Without this, `grnh.se`/appcast/recruitics links reach the queue as
        opaque hops: the ATS handling cannot recognise them, and the same job
        arrives repeatedly under different tracking ids because there is no ATS
        id in the URL for dedup to key on.
        """
        from app.services.job_discover.redirect_resolver import is_redirector, resolve_all

        candidates = [j.apply_url for j in jobs if is_redirector(j.apply_url)]
        if not candidates:
            return
        resolved = await resolve_all(client, candidates)
        for job in jobs:
            final = resolved.get(job.apply_url)
            if final and final != job.apply_url:
                job.source_metadata["trackingUrl"] = job.apply_url
                job.apply_url = final
                job.canonical_url = final

    async def _fetch_page(
        self,
        client: httpx.AsyncClient,
        search_term: str,
        location: str,
        hours_old: int,
        cursor: str | None,
    ) -> tuple[list[dict[str, Any]], str | None]:
        safe_term = search_term.replace('"', '\\"')
        query = INDEED_JOB_SEARCH_QUERY.format(
            what=f'what: "{safe_term}"',
            location=f'location: {{where: "{location}", radius: 50, radiusUnit: MILES}}',
            limit=_RESULTS_PER_PAGE,
            cursor=f'cursor: "{cursor}"' if cursor else "",
            filters=build_indeed_date_filter(hours_old),
        )
        resp = await self.execute_request(
            client,
            INDEED_API_URL,
            method="POST",
            headers=INDEED_API_HEADERS,
            json_data={"query": query},
            timeout=20.0,
        )
        if not resp or resp.status_code != 200:
            self.record_failure(f"HTTP {resp.status_code if resp else 'no response'}")
            return [], None
        try:
            search = (resp.json().get("data") or {}).get("jobSearch") or {}
        except Exception as exc:
            self.record_failure(exc)
            return [], None
        results = search.get("results") or []
        next_cursor = (search.get("pageInfo") or {}).get("nextCursor")
        return results, next_cursor

    def _normalize(self, job: dict[str, Any], key: str, title: str, strip_html: Any) -> NormalizedJob | None:
        employer = job.get("employer") or {}
        company_name = str(employer.get("name") or "").strip()
        if not company_name:
            return None

        loc = job.get("location") or {}
        formatted = loc.get("formatted") or {}
        location_str = str(formatted.get("long") or formatted.get("short") or "").strip()

        attributes = [str((a or {}).get("label") or "") for a in (job.get("attributes") or [])]
        attr_blob = " ".join(attributes).lower()
        is_remote = "remote" in attr_blob or "remote" in location_str.lower()
        is_hybrid = "hybrid" in attr_blob or "hybrid" in location_str.lower()

        recruit = job.get("recruit") or {}
        # The employer's own apply URL is the entire point of this source. A
        # posting without one is dropped rather than stored under its Indeed
        # listing URL: that page is a description with no form, so the executor
        # can only open it, fill nothing and park the job in MANUAL_REVIEW.
        # Falling back to it put 293 unapplyable jobs into the pipeline.
        direct_url = str(recruit.get("viewJobUrl") or "").strip()
        if not direct_url:
            return None
        indeed_url = f"https://www.indeed.com/viewjob?jk={key}"
        apply_url = direct_url

        published = job.get("datePublished") or job.get("dateOnIndeed")
        try:
            ts = datetime.fromtimestamp(int(published) / 1000).isoformat() if published else ""
        except (TypeError, ValueError, OSError):
            ts = ""

        description = ""
        try:
            description = strip_html(((job.get("description") or {}).get("html")) or "")
        except Exception:
            description = ""

        return NormalizedJob(
            id=f"indeed:{key}",
            # Deliberately not Indeed's listing key. That id is source-local and
            # unique per row, and it flows through to `externalJobId`, which the
            # dedup key falls back to whenever the URL carries no recognisable
            # ATS id (amazon.jobs, careers.google.com). Feeding it in made every
            # row's key unique by construction — 578 rows produced 578 keys, so
            # nothing could ever match. Kept in source_metadata for traceability;
            # dedup falls through to the URL, which is stable per posting.
            external_id="",
            company=company_name.lower().replace(" ", "-"),
            company_name=company_name,
            title=title,
            location=location_str,
            locations=[location_str] if location_str else [],
            city=str(loc.get("city") or ""),
            state=str(loc.get("admin1Code") or ""),
            country=str(loc.get("countryCode") or "US"),
            remote=is_remote,
            hybrid=is_hybrid,
            remote_status="REMOTE" if is_remote else ("HYBRID" if is_hybrid else "ONSITE"),
            source_url=indeed_url,
            apply_url=apply_url,
            canonical_url=apply_url,
            description=description,
            updated_at=ts,
            first_published=ts,
            skills=attributes,
            source="indeed",
            source_type="aggregator",
            source_priority=60,
            source_quality=60,
            extraction_method="indeed_graphql",
            provenance_sources=["indeed"],
            source_metadata={"hasDirectEmployerUrl": bool(direct_url), "indeedKey": key},
        )
