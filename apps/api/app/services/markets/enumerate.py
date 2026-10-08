"""Enumerate a company's open jobs through the adapter its source detection chose.

Every path returns an ``Enumeration`` whose ``ok`` says whether the source was
actually read. A failed read is never reported as zero jobs: ``ok=False`` with
the reason, and the caller keeps the last good counts.

ATS boards are read in full (no title filter), so ``total_open`` is every open
posting. Proprietary portals (Amazon, Microsoft, ...) are far too large to read
in full; they are searched for software roles in the market's state and the
counts are labelled as that search (``scope="search"``).
"""

from __future__ import annotations

import logging
import re
import time
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

import httpx

from app.services.job_discover import bigtech_scrapers
from app.services.job_discover.sources.ashby import AshbySource
from app.services.job_discover.sources.base import JobSourceAdapter, NormalizedJob
from app.services.job_discover.sources.greenhouse import GreenhouseSource
from app.services.job_discover.sources.icims import ICIMSSource
from app.services.job_discover.sources.lever import LeverSource
from app.services.job_discover.sources.oracle import OracleSource
from app.services.job_discover.sources.personio import PersonioSource
from app.services.job_discover.sources.recruitee import RecruiteeSource
from app.services.job_discover.sources.smartrecruiters import SmartRecruitersSource
from app.services.job_discover.sources.structured_career_page import parse_jsonld_job_postings
from app.services.job_discover.sources.workable import WorkableSource
from app.services.job_discover.sources.workday import WorkdaySource
from app.services.markets.config import Market
from app.services.markets.detector import BROWSER_HEADERS
from app.services.markets.geo import match_location
from app.services.markets.relevance import assess

logger = logging.getLogger("career_os.markets.enumerate")

ADAPTERS: dict[str, type[JobSourceAdapter]] = {
    "greenhouse": GreenhouseSource,
    "lever": LeverSource,
    "ashby": AshbySource,
    "smartrecruiters": SmartRecruitersSource,
    "workable": WorkableSource,
    "recruitee": RecruiteeSource,
    "personio": PersonioSource,
    "workday": WorkdaySource,
    "icims": ICIMSSource,
    "oracle": OracleSource,
}
PROPRIETARY = {"amazon", "microsoft", "google", "apple", "netflix"}
# Boards too large to always read in full: (search parameter, search cap).
_PAGED = {"workday": ("searchText", 400), "oracle": ("keyword", 1100)}
SEARCH_TERMS = ["software engineer", "software development engineer"]
_EPOCH = datetime(2000, 1, 1, tzinfo=UTC)
_MULTI_LOCATION = re.compile(r"^\s*\d+\s+locations?\s*$", re.I)


@dataclass
class Enumeration:
    ok: bool
    provider: str
    error: str = ""
    http_status: int | None = None
    total_open: int | None = None
    scope: str = "all"
    scope_label: str = "All open postings"
    truncated: bool = False
    jobs: list[dict[str, Any]] = field(default_factory=list)
    duration_ms: int = 0

    @property
    def market_jobs(self) -> list[dict[str, Any]]:
        return [j for j in self.jobs if j["_market"]["inMarket"]]

    @property
    def relevant_jobs(self) -> list[dict[str, Any]]:
        return [j for j in self.market_jobs if j["_relevance"]["relevant"]]

    def counts(self) -> dict[str, Any]:
        return {
            "totalOpen": self.total_open,
            "fetched": len(self.jobs),
            "inMarket": len(self.market_jobs),
            "relevant": len(self.relevant_jobs),
            "scope": self.scope,
            "scopeLabel": self.scope_label,
            "truncated": self.truncated,
        }


def _annotate(raw: dict[str, Any], market: Market) -> dict[str, Any]:
    locations = [raw.get("location") or "", *(raw.get("locations") or [])]
    match = match_location(" | ".join(l for l in locations if l), market)
    raw["_market"] = match.to_dict()
    raw["_relevance"] = assess(raw.get("title") or "", raw.get("description") or "").to_dict()
    return raw


def _store_dict(job: NormalizedJob, company: dict[str, Any], market: Market) -> dict[str, Any]:
    data = job.to_dict()
    data["company"] = company["name"]
    data["companyName"] = company["name"]
    data["datePosted"] = job.first_published or job.updated_at or ""
    data["discovery_sources"] = [job.source, f"markets:{market.id}"]
    return data


async def _run_adapter(
    client: httpx.AsyncClient,
    provider: str,
    company: dict[str, Any],
    config: dict[str, Any],
) -> tuple[JobSourceAdapter, list[NormalizedJob]]:
    adapter = ADAPTERS[provider]()  # fresh: its health reflects this call only
    jobs = await adapter.fetch_jobs(client, company["id"], {**config, "company_name": company["name"]}, [], _EPOCH)
    return adapter, jobs


async def _workday_locations(client: httpx.AsyncClient, config: dict[str, Any], jobs: list[dict[str, Any]], limit: int = 30) -> None:
    """Resolve "3 Locations" (or a blank location) for relevant-looking Workday postings from the posting detail."""
    host, tenant, board = config.get("host"), config.get("tenant") or config.get("company"), config.get("board")
    pending = [
        j for j in jobs
        if (not (j.get("location") or "").strip() or _MULTI_LOCATION.match(j.get("location") or "")) and j["_relevance"]["relevant"]
    ][:limit]
    for job in pending:
        path = (job.get("source_metadata") or {}).get("external_path") or ""
        if not path:
            continue
        try:
            resp = await client.get(f"https://{host}/wday/cxs/{tenant}/{board}{path}", headers={"Accept": "application/json"}, timeout=15)
            if resp.status_code != 200:
                continue
            info = (resp.json() or {}).get("jobPostingInfo") or {}
            places = [info.get("location") or "", *(info.get("additionalLocations") or [])]
            job["locations"] = [p for p in places if p]
            job["location"] = " | ".join(job["locations"]) or job["location"]
        except (httpx.HTTPError, ValueError):
            continue


async def _enumerate_ats(client: httpx.AsyncClient, provider: str, company: dict[str, Any], config: dict[str, Any], market: Market) -> Enumeration:
    paged = _PAGED.get(provider)
    if paged:
        config = {**config, "max_results": max(int(config.get("max_results") or 0), 600)}
    adapter, jobs = await _run_adapter(client, provider, company, config)
    error = adapter.health.last_error
    if error:
        return Enumeration(ok=False, provider=provider, error=str(error), http_status=_status_from(str(error)))
    raws = [_annotate(_store_dict(j, company, market), market) for j in jobs]
    result = Enumeration(ok=True, provider=provider, total_open=len(raws), jobs=raws)
    if paged:
        search_param, search_cap = paged
        total = getattr(adapter, "last_total", None)
        result.total_open = total if total is not None else len(raws)
        if total and total > len(raws):
            # Too many postings to page through: add a software search so the
            # relevant slice is complete even when the full list is not.
            searched_adapter, searched = await _run_adapter(client, provider, company, {**config, search_param: "software", "max_results": search_cap})
            seen = {r.get("url") for r in raws}
            for job in searched:
                data = _store_dict(job, company, market)
                if data.get("url") not in seen:
                    raws.append(_annotate(data, market))
            result.truncated = (getattr(searched_adapter, "last_total", 0) or 0) > len(searched)
            result.scope_label = f"{len(raws)} of {total} postings read (all software roles included)"
    if provider == "workday":
        await _workday_locations(client, config, raws)
        for job in raws:
            _annotate(job, market)
    return result


def _status_from(error: str) -> int | None:
    match = re.search(r"HTTP (\d{3})", error or "")
    return int(match.group(1)) if match else None


def _bigtech_job(item: dict[str, Any], provider: str, company: dict[str, Any], market: Market) -> dict[str, Any]:
    url = item.get("url", "")
    ext_id = str(item.get("greenhouse_id") or item.get("id") or url)
    location = item.get("location", "")
    job = NormalizedJob(
        id=f"{provider}:{ext_id}",
        external_id=ext_id,
        company=provider,
        company_name=company["name"],
        title=item.get("title", ""),
        location=location,
        locations=[location] if location else [],
        source_url=url,
        apply_url=url,
        canonical_url=url,
        department=item.get("department", ""),
        description=item.get("description", ""),
        updated_at=item.get("updated_at", ""),
        first_published=item.get("first_published", ""),
        employment_type=item.get("employment_type", "") or "Full-time",
        source=f"{provider}_careers",
        source_type="company_api",
        source_priority=100,
        source_quality=100,
        extraction_method="direct_career_site",
        provenance_sources=[f"{provider}_careers"],
    )
    return _annotate(_store_dict(job, company, market), market)


async def _enumerate_proprietary(client: httpx.AsyncClient, provider: str, company: dict[str, Any], market: Market, cap: int) -> Enumeration:
    hints = market.provider_hints.get(provider) or {}
    diag: dict[str, Any] = {}
    if provider == "amazon":
        items = await bigtech_scrapers.scrape_amazon(client, SEARCH_TERMS, location="", max_results=cap, extra_params=hints.get("params"), diagnostics=diag)
    elif provider == "microsoft":
        items = await bigtech_scrapers.scrape_microsoft(client, SEARCH_TERMS[:1], max_results=cap, location=hints.get("location") or market.anchor_location, diagnostics=diag)
    elif provider == "google":
        items = await bigtech_scrapers.scrape_google(client, SEARCH_TERMS[:1], location=hints.get("location") or market.anchor_location, max_results=cap, diagnostics=diag)
    elif provider == "apple":
        items = await bigtech_scrapers.scrape_apple(client, SEARCH_TERMS[:1], location=hints.get("location") or "united-states-USA", max_results=cap, diagnostics=diag)
    else:
        items = await bigtech_scrapers.scrape_netflix(client, SEARCH_TERMS[:1], max_results=cap, diagnostics=diag)

    if not diag.get("ok"):
        errors = diag.get("errors") or ["No successful response from the career API"]
        return Enumeration(ok=False, provider=provider, error="; ".join(errors[:3]), http_status=diag.get("status"))
    raws = [_bigtech_job(item, provider, company, market) for item in items]
    total = diag.get("total")
    result = Enumeration(
        ok=True,
        provider=provider,
        total_open=int(total) if total is not None else len(raws),
        scope="search",
        scope_label=f"Software roles searched in {market.state_name or market.name}",
        jobs=raws,
        truncated=bool(diag.get("truncated")) or (total is not None and int(total) > len(raws)),
    )
    if diag.get("errors"):
        result.error = "Partial: " + "; ".join(diag["errors"][:2])
    return result


async def _enumerate_jsonld(client: httpx.AsyncClient, company: dict[str, Any], config: dict[str, Any], market: Market) -> Enumeration:
    url = config.get("careersUrl") or (company.get("career") or {}).get("url") or ""
    try:
        resp = await client.get(url, headers=BROWSER_HEADERS, timeout=15, follow_redirects=True)
    except (httpx.HTTPError, TimeoutError) as exc:
        return Enumeration(ok=False, provider="jsonld", error=f"{type(exc).__name__}: {exc}")
    if resp.status_code != 200:
        return Enumeration(ok=False, provider="jsonld", error=f"HTTP {resp.status_code}", http_status=resp.status_code)
    jobs = parse_jsonld_job_postings(resp.text, str(resp.url), company["id"])
    raws = [_annotate(_store_dict(j, company, market), market) for j in jobs]
    # A page can carry a handful of JobPosting blocks without being the full list.
    return Enumeration(ok=True, provider="jsonld", total_open=len(raws), jobs=raws,
                       scope="page", scope_label="Postings embedded on the career page")


async def _jibe_pages(client: httpx.AsyncClient, host: str, max_pages: int, **params: Any) -> tuple[int | None, int | None, list[dict[str, Any]]]:
    """(http status of a failure or None, total, job data) for an iCIMS Jibe /api/jobs listing."""
    total: int | None = None
    out: list[dict[str, Any]] = []
    for page in range(1, max_pages + 1):
        resp = await client.get(f"https://{host}/api/jobs", params={"page": page, "limit": 100, **params}, headers=BROWSER_HEADERS, timeout=20)
        if resp.status_code != 200:
            return resp.status_code, total, out
        data = resp.json() or {}
        total = int(data.get("totalCount") or 0)
        batch = [j.get("data") or {} for j in data.get("jobs") or []]
        out.extend(batch)
        if not batch or len(out) >= total:
            break
    return None, total, out


def _jibe_job(data: dict[str, Any], host: str, jobs_path: str, company: dict[str, Any], market: Market) -> dict[str, Any]:
    slug = str(data.get("slug") or data.get("req_id") or "")
    places = [p.strip() for p in (data.get("full_location") or "").split(";") if p.strip()]
    location = data.get("short_location") or (places[0] if places else ", ".join(p for p in (data.get("city"), data.get("state")) if p))
    url = f"https://{host}{jobs_path}/{slug}?lang=en-us"
    job = NormalizedJob(
        id=f"jibe:{host}:{slug}",
        external_id=slug,
        company=company["id"],
        company_name=company["name"],
        title=data.get("title") or "",
        location=" | ".join(places) or location,
        locations=places or ([location] if location else []),
        source_url=url,
        apply_url=data.get("apply_url") or url,
        canonical_url=url,
        department=", ".join(c.get("name", "") for c in data.get("categories") or [] if isinstance(c, dict)),
        description=re.sub(r"<[^>]+>", " ", " ".join(str(data.get(k) or "") for k in ("description", "qualifications", "responsibilities"))),
        updated_at=data.get("update_date") or "",
        first_published=data.get("posted_date") or data.get("create_date") or "",
        employment_type=(data.get("employment_type") or "Full-time").replace("_", "-").title(),
        source="jibe",
        source_type="ats",
        source_priority=95,
        source_quality=90,
        extraction_method="jibe_api",
        provenance_sources=["jibe"],
    )
    return _annotate(_store_dict(job, company, market), market)


async def _enumerate_jibe(client: httpx.AsyncClient, company: dict[str, Any], config: dict[str, Any], market: Market) -> Enumeration:
    host, jobs_path = config.get("host") or "", config.get("jobsPath") or "/jobs"
    status, total, items = await _jibe_pages(client, host, max_pages=10)
    if status is not None and not items:
        return Enumeration(ok=False, provider="jibe", error=f"HTTP {status}", http_status=status)
    raws = [_jibe_job(d, host, jobs_path, company, market) for d in items]
    result = Enumeration(ok=True, provider="jibe", total_open=total if total is not None else len(raws), jobs=raws)
    if total and total > len(raws):
        _, searched_total, searched = await _jibe_pages(client, host, max_pages=3, keywords="software")
        seen = {r.get("url") for r in raws}
        raws.extend(j for j in (_jibe_job(d, host, jobs_path, company, market) for d in searched) if j.get("url") not in seen)
        result.truncated = (searched_total or 0) > len(searched)
        result.scope_label = f"{len(raws)} of {total} postings read (all software roles included)"
    if status is not None:
        result.error = f"Partial: HTTP {status} part-way through the listing"
    return result


async def enumerate_company(
    client: httpx.AsyncClient,
    company: dict[str, Any],
    market: Market,
    *,
    proprietary_cap: int = 400,
) -> Enumeration:
    career = company.get("career") or {}
    provider = career.get("provider") or ""
    config = career.get("config") or {}
    started = time.perf_counter()
    try:
        if provider in ADAPTERS:
            result = await _enumerate_ats(client, provider, company, config, market)
        elif provider in PROPRIETARY:
            result = await _enumerate_proprietary(client, provider, company, market, proprietary_cap)
        elif provider == "jsonld":
            result = await _enumerate_jsonld(client, company, config, market)
        elif provider == "jibe":
            result = await _enumerate_jibe(client, company, config, market)
        else:
            result = Enumeration(ok=False, provider=provider or "none", error="No automatic reader for this source")
    except Exception as exc:  # an adapter bug must not take the refresh down
        logger.exception("Enumeration failed for %s", company.get("name"))
        result = Enumeration(ok=False, provider=provider, error=f"{type(exc).__name__}: {exc}")
    result.duration_ms = int((time.perf_counter() - started) * 1000)
    return result
