"""Recruitee JobSourceAdapter implementation for CareerOS Job Ingestion V2."""

from __future__ import annotations

import time
from datetime import datetime
from typing import Any

import httpx

from app.services.job_discover.sources.base import JobSourceAdapter, NormalizedJob


class RecruiteeSource(JobSourceAdapter):
    """Ingest jobs from Recruitee's public, keyless per-company offers API.

    Verified 2026-09-15: `https://{slug}.recruitee.com/api/offers/` is Recruitee's
    own documented public feed (https://docs.recruitee.com/reference/offers) - no
    auth required, confirmed live against a real board (bunq.recruitee.com).
    """

    id = "recruitee"
    name = "Recruitee"
    source_type = "ats"
    priority = 95

    def supports(self, source_type: str, config: dict[str, Any] | None = None) -> bool:
        return source_type.lower() == "recruitee"

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
        url = f"https://{slug}.recruitee.com/api/offers/"

        resp = await self.execute_request(client, url, timeout=20.0)
        if not resp or resp.status_code != 200:
            self.record_failure(f"HTTP {resp.status_code if resp else 'No response'}")
            return []

        try:
            data = resp.json()
            raw_offers = data.get("offers", [])
            jobs: list[NormalizedJob] = []

            for offer in raw_offers:
                title = offer.get("title", "")
                ts = offer.get("published_at") or offer.get("updated_at") or offer.get("created_at", "")
                if compiled_patterns and not matches_title(title, compiled_patterns):
                    continue
                if not is_recent(ts, cutoff):
                    continue

                city = offer.get("city") or ""
                state = offer.get("state_name") or ""
                country = offer.get("country") or ""
                location_parts = [p for p in (city, state, country) if p]
                location = ", ".join(location_parts) or (offer.get("location") or "")

                extra_locations = offer.get("locations") or []
                all_locs = [location] if location else []
                for loc in extra_locations:
                    if isinstance(loc, dict):
                        name = ", ".join(p for p in (loc.get("city"), loc.get("state_name"), loc.get("country")) if p)
                    else:
                        name = str(loc or "")
                    if name and name not in all_locs:
                        all_locs.append(name)

                is_remote = bool(offer.get("remote"))
                is_hybrid = bool(offer.get("hybrid"))
                remote_status = "REMOTE" if is_remote else ("HYBRID" if is_hybrid else "ONSITE")
                workplace_type = "remote" if is_remote else ("hybrid" if is_hybrid else "")

                description = strip_html(offer.get("description") or "")
                requirements = strip_html(offer.get("requirements") or "")
                full_description = "\n\n".join(p for p in (description, requirements) if p)

                offer_id = s(offer.get("id", ""))
                offer_slug = offer.get("slug") or offer_id
                careers_url = offer.get("careers_url") or f"https://{slug}.recruitee.com/o/{offer_slug}"
                apply_url = offer.get("careers_apply_url") or careers_url

                normalized = NormalizedJob(
                    id=f"{company}:{offer_id}",
                    external_id=offer_id,
                    company=company,
                    company_name=offer.get("company_name") or config.get("company_name") or company.replace("-", " ").capitalize(),
                    title=title,
                    location=location,
                    locations=all_locs,
                    city=city,
                    state=state,
                    country=country or "US",
                    remote=is_remote,
                    hybrid=is_hybrid,
                    remote_status=remote_status,
                    workplace_type=workplace_type,
                    department=offer.get("department") or "",
                    team=offer.get("category_code") or "",
                    source_url=careers_url,
                    apply_url=apply_url,
                    canonical_url=careers_url,
                    description=full_description,
                    updated_at=offer.get("updated_at", ""),
                    first_published=offer.get("published_at") or offer.get("created_at", ""),
                    employment_type=offer.get("employment_type_code") or "Full-time",
                    source="recruitee",
                    source_type="ats",
                    source_priority=95,
                    source_quality=95,
                    extraction_method="recruitee_api",
                    provenance_sources=["recruitee"],
                )
                jobs.append(normalized)

            duration = (time.perf_counter() - start_time) * 1000
            self.record_success(len(jobs), duration)
            return jobs
        except Exception as exc:
            self.record_failure(exc)
            return []
