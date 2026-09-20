"""LinkedIn ingestion via its logged-out guest search endpoint.

Deliberately discovery-only. The guest endpoint returns search cards, which
carry company, title, location and the LinkedIn posting URL — but never the
employer's own application URL. Getting that means one extra request per job
against the detail page, which is exactly the fan-out that gets an IP
rate-limited, so it is not done here. The value of this source is the
company + title pair, which the ATS scrapers can then look up at the source.

Measured live: 20 results in ~7s, every one with `job_url_direct` absent.

Request mechanics adapted from JobSpy (MIT) — see `_vendored_jobspy/`.
"""

from __future__ import annotations

import logging
import time
from datetime import datetime
from typing import Any

import httpx

from app.services.job_discover.sources._vendored_jobspy import (
    LINKEDIN_HEADERS,
    LINKEDIN_MAX_START_OFFSET,
    LINKEDIN_RESULTS_PER_PAGE,
    LINKEDIN_SEARCH_URL,
)
from app.services.job_discover.sources.base import JobSourceAdapter, NormalizedJob, SourceRole

logger = logging.getLogger("career_os.job_discover.linkedin")

DEFAULT_SEARCH_TERMS = (
    "Senior Software Engineer",
    "Staff Software Engineer",
    "Machine Learning Engineer",
)

_MAX_PAGES_PER_TERM = 3


class LinkedInSource(JobSourceAdapter):
    """Ingest company/title discovery signal from LinkedIn's guest job search."""

    id = "linkedin"
    name = "LinkedIn (discovery)"
    role = SourceRole.DISCOVERY
    source_type = "scraper"
    priority = 40
    supports_incremental_sync = True
    # LinkedIn rate-limits hard; this source is slow on purpose.
    rate_limit_delay_sec = 3.0
    max_retries = 2

    def supports(self, source_type: str, config: dict[str, Any] | None = None) -> bool:
        return source_type.lower() in ("linkedin", "linkedin_guest")

    async def fetch_jobs(
        self,
        client: httpx.AsyncClient,
        company: str = "all",
        config: dict[str, Any] | None = None,
        compiled_patterns: list[Any] | None = None,
        cutoff: datetime | None = None,
        role_keys: list[str] | None = None,
    ) -> list[NormalizedJob]:
        from app.services.job_discover.scraper_service import matches_title

        started = time.perf_counter()
        cfg = config or {}
        search_terms = cfg.get("searchTerms") or DEFAULT_SEARCH_TERMS
        location = cfg.get("location") or "United States"
        hours_old = int(cfg.get("hoursOld") or 168)

        jobs: list[NormalizedJob] = []
        seen_ids: set[str] = set()

        for term in search_terms:
            start = 0
            for _ in range(_MAX_PAGES_PER_TERM):
                if start >= LINKEDIN_MAX_START_OFFSET:
                    break
                cards = await self._fetch_page(client, term, location, hours_old, start)
                if not cards:
                    break
                for card in cards:
                    job_id = card["job_id"]
                    if job_id in seen_ids:
                        continue
                    if compiled_patterns and not matches_title(card["title"], compiled_patterns):
                        continue
                    seen_ids.add(job_id)
                    jobs.append(self._normalize(card))
                start += LINKEDIN_RESULTS_PER_PAGE

        await self._upgrade_to_ats_postings(jobs)
        await self._upgrade_residue_via_google(client, jobs)

        # Only postings that were successfully resolved to an employer board are
        # returned. A LinkedIn card that could not be resolved still carries a
        # linkedin.com URL, which is a description with no application form —
        # queuing one guarantees a MANUAL_REVIEW and a wasted browser session.
        # 33 such jobs reached the pipeline before this was enforced.
        applyable = [j for j in jobs if j.source_metadata.get("hasDirectEmployerUrl")]
        dropped = len(jobs) - len(applyable)
        if dropped:
            logger.debug(
                "LinkedIn: dropped %d unresolved discovery-only cards (no employer URL)",
                dropped,
            )

        duration = (time.perf_counter() - started) * 1000
        self.record_success(len(applyable), duration)
        return applyable

    @staticmethod
    async def _upgrade_residue_via_google(
        client: httpx.AsyncClient, jobs: list[NormalizedJob]
    ) -> None:
        """Search-index fallback for what the free ATS lookup could not resolve.

        Deliberately runs only over the residue. The public board APIs handle
        Greenhouse/Lever/Ashby for free; what is left is mostly enterprises on
        Workday/Taleo/iCIMS, which publish no open listing endpoint. The Google
        free tier is 100 queries/day, so it is spent only on those, and only
        when credentials are configured.
        """
        from app.services.job_discover.google_cse_resolver import (
            get_usage,
            is_configured,
            resolve_via_google,
        )

        if not is_configured():
            return
        residue = [j for j in jobs if not j.source_metadata.get("hasDirectEmployerUrl")]
        if not residue:
            return

        from app.db.store import session_scope

        with session_scope() as db:
            used, budget = get_usage(db)
            remaining = max(0, budget - used)
            if not remaining:
                return
            for job in residue[:remaining]:
                hit = await resolve_via_google(client, db, job.company_name, job.title)
                if not hit or not hit.get("applicationUrl"):
                    continue
                job.source_metadata["linkedinUrl"] = job.source_url
                job.source_metadata["discoveryOnly"] = False
                job.source_metadata["hasDirectEmployerUrl"] = True
                job.source_metadata["resolvedVia"] = hit["source"]
                job.apply_url = hit["applicationUrl"]
                job.canonical_url = hit["applicationUrl"]

    @staticmethod
    async def _upgrade_to_ats_postings(jobs: list[NormalizedJob]) -> None:
        """Turn discoveries into applyable postings where the board is public.

        A LinkedIn card is company + title and nothing applyable, but that pair
        is enough to find the posting on the employer's own board. Measured on
        20 live results, 6 resolved — the rest are mostly enterprises on
        Workday/Taleo/iCIMS, which publish no open listing endpoint, so they
        stay flagged discovery-only rather than being guessed at.

        The board lookups are synchronous and cached per board, so they run in a
        worker thread rather than blocking the event loop mid-scrape.
        """
        import asyncio

        from app.services.job_discover.aggregator_resolve import resolve_by_company_and_title

        def _resolve_all() -> dict[str, dict[str, Any]]:
            out: dict[str, dict[str, Any]] = {}
            for job in jobs:
                hit = resolve_by_company_and_title(job.company_name, job.title)
                if hit:
                    out[job.id] = hit
            return out

        try:
            resolved = await asyncio.to_thread(_resolve_all)
        except Exception:
            return

        for job in jobs:
            hit = resolved.get(job.id)
            if not hit:
                continue
            job.source_metadata["linkedinUrl"] = job.source_url
            job.source_metadata["discoveryOnly"] = False
            job.source_metadata["hasDirectEmployerUrl"] = True
            job.source_metadata["resolvedVia"] = hit["source"]
            job.apply_url = hit["applicationUrl"]
            job.canonical_url = hit["applicationUrl"]

    async def _fetch_page(
        self,
        client: httpx.AsyncClient,
        search_term: str,
        location: str,
        hours_old: int,
        start: int,
    ) -> list[dict[str, str]]:
        params: dict[str, Any] = {
            "keywords": search_term,
            "location": location,
            "pageNum": 0,
            "start": start,
        }
        if hours_old:
            params["f_TPR"] = f"r{int(hours_old) * 3600}"

        resp = await self.execute_request(
            client,
            LINKEDIN_SEARCH_URL,
            headers=LINKEDIN_HEADERS,
            params=params,
            timeout=20.0,
        )
        if not resp or resp.status_code != 200:
            # 429 here means the IP is being throttled; back off rather than
            # hammering, since LinkedIn escalates quickly.
            self.record_failure(f"HTTP {resp.status_code if resp else 'no response'}")
            return []
        return self._parse_cards(resp.text)

    @staticmethod
    def _parse_cards(html: str) -> list[dict[str, str]]:
        from bs4 import BeautifulSoup

        soup = BeautifulSoup(html, "html.parser")
        cards: list[dict[str, str]] = []
        for card in soup.find_all("div", class_="base-search-card"):
            link = card.find("a", class_="base-card__full-link")
            href = (link.get("href") or "").split("?")[0] if link else ""
            if not href:
                continue
            job_id = href.rstrip("/").split("-")[-1]
            if not job_id.isdigit():
                continue
            title_el = card.find("span", class_="sr-only") or card.find("h3")
            company_el = card.find("h4") or card.find("a", class_="hidden-nested-link")
            location_el = card.find("span", class_="job-search-card__location")
            date_el = card.find("time")
            cards.append({
                "job_id": job_id,
                "url": href,
                "title": (title_el.get_text(strip=True) if title_el else ""),
                "company": (company_el.get_text(strip=True) if company_el else ""),
                "location": (location_el.get_text(strip=True) if location_el else ""),
                "date": (date_el.get("datetime") if date_el else "") or "",
            })
        return cards

    @staticmethod
    def _normalize(card: dict[str, str]) -> NormalizedJob:
        company_name = card["company"] or "Unknown Company"
        location_str = card["location"]
        low = location_str.lower()
        is_remote = "remote" in low
        is_hybrid = "hybrid" in low
        return NormalizedJob(
            id=f"linkedin:{card['job_id']}",
            external_id=card["job_id"],
            company=company_name.lower().replace(" ", "-"),
            company_name=company_name,
            title=card["title"],
            location=location_str,
            locations=[location_str] if location_str else [],
            remote=is_remote,
            hybrid=is_hybrid,
            remote_status="REMOTE" if is_remote else ("HYBRID" if is_hybrid else "ONSITE"),
            source_url=card["url"],
            apply_url=card["url"],
            canonical_url=card["url"],
            updated_at=card["date"],
            first_published=card["date"],
            source="linkedin",
            source_type="scraper",
            source_priority=40,
            source_quality=40,
            extraction_method="linkedin_guest_search",
            provenance_sources=["linkedin"],
            # Flagged so downstream knows this needs an ATS lookup before it can
            # be applied to — the card has no employer application URL.
            source_metadata={"discoveryOnly": True, "hasDirectEmployerUrl": False},
        )
