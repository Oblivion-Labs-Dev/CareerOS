"""FastAPI routes for the jobs service.

Paths are kept identical to the pre-refactor routers (no service prefix is added
here); ``main.py`` includes this router without a prefix so existing
frontend/extension calls keep resolving. The core job + discovery handlers were
moved verbatim out of ``apps/api/app/routers/api.py``; the job-search workflow
routes come from ``jobs.search_routes`` and the external batch import from
``jobs.import_routes``.
"""

from __future__ import annotations

import logging
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.db.store import (
    get_kv,
    list_entities,
    new_id,
    now_iso,
    session_scope,
    upsert_entity,
)
from jobs.discovery import relevancy_engine
from jobs.discovery import store as job_discover
from jobs.discovery.url_import import autoextract_job_from_url
from jobs.import_routes import router as job_import_router
from jobs.search_routes import router as job_search_router
from jobs.target_companies import (
    filter_jobs,
    format_whatsapp,
    get_snapshot,
    merge_oracle_seed_entries,
    refresh_and_store,
    should_refresh_weekly,
)
from shared.deps import db_session

logger = logging.getLogger("career_os.api")

router = APIRouter()


class JobExtractPayload(BaseModel):
    url: str
    html: str | None = None
    title: str | None = None
    company: str | None = None
    location: str | None = None
    description: str | None = None
    platform: str | None = None


class JobSavePayload(BaseModel):
    job: dict[str, Any]


class TargetCompanyOracleSeedPayload(BaseModel):
    jobs: list[dict[str, Any]] = Field(default_factory=list)


class TargetCompanyRefreshPayload(BaseModel):
    verifyOracle: bool = True


class JobGapAnalysisPayload(BaseModel):
    jobId: str = Field(min_length=1)


class RescoreJobsPayload(BaseModel):
    jobIds: list[str] = Field(default_factory=list)


class JobDiscoverScrapePayload(BaseModel):
    hours: int = Field(default=168, ge=1, le=2160)
    roles: str = ""
    mode: str = "ats"


class CompanyRegistryPayload(BaseModel):
    company: str
    source: str = "auto"
    careersUrl: str = ""
    config: dict[str, Any] = Field(default_factory=dict)


class CompanyDiscoverPayload(BaseModel):
    company: str
    careersUrl: str


class JobDiscoverMessagePayload(BaseModel):
    contactName: str = "[Name]"


@router.post("/jobs/extract")
def extract_job(payload: JobExtractPayload) -> dict[str, Any]:
    auto: dict[str, Any] | None = None
    # Only attempt a live fetch when the caller hasn't already supplied a
    # description (the extension sends scraped `html` separately; a manual
    # "paste a job link" flow from the dashboard sends just the URL).
    if not payload.html and not payload.description and payload.url:
        auto = autoextract_job_from_url(payload.url)

    job = {
        "id": new_id("job_"),
        "companyName": payload.company or (auto or {}).get("company") or "Unknown company",
        "title": payload.title or (auto or {}).get("title") or "Unknown role",
        "location": payload.location or (auto or {}).get("location") or "",
        "description": payload.description or (auto or {}).get("description") or "",
        "url": payload.url,
        "platform": payload.platform or "",
        "extractedAt": now_iso(),
        "autoExtracted": bool(auto),
    }
    return {"success": True, "job": job}


@router.post("/jobs/save")
def save_job(payload: JobSavePayload, db: Session = Depends(db_session)) -> dict[str, Any]:
    saved = upsert_entity(db, "job", {**payload.job, "savedAt": payload.job.get("savedAt") or now_iso()})
    return {"success": True, "job": saved}


@router.get("/jobs")
def list_jobs(db: Session = Depends(db_session)) -> dict[str, Any]:
    return {"jobs": list_entities(db, "job")}


@router.get("/jobs/target-companies")
def get_target_company_jobs(
    db: Session = Depends(db_session),
    company: str = Query(default="all"),
    location: str = Query(default="all"),
    activeOnly: bool = Query(default=True),
) -> dict[str, Any]:
    snapshot = get_snapshot(db)
    location_filter = location if location in {"all", "remote", "washington"} else "all"
    jobs = filter_jobs(snapshot.get("jobs") or [], company=company, location=location_filter, active_only=activeOnly)
    return {
        "success": True,
        "refreshedAt": snapshot.get("refreshedAt"),
        "needsWeeklyRefresh": should_refresh_weekly(snapshot),
        "companies": snapshot.get("companies") or {},
        "jobs": jobs,
        "total": len(jobs),
    }


@router.post("/jobs/target-companies/refresh")
def refresh_target_company_jobs_route(
    payload: TargetCompanyRefreshPayload | None = None,
    db: Session = Depends(db_session),
) -> dict[str, Any]:
    verify_oracle = True if payload is None else payload.verifyOracle
    snapshot = refresh_and_store(db, verify_oracle=verify_oracle)
    return {
        "success": True,
        "refreshedAt": snapshot.get("refreshedAt"),
        "companies": snapshot.get("companies") or {},
        "totalJobs": len(snapshot.get("jobs") or []),
    }


@router.get("/jobs/target-companies/whatsapp")
def target_company_jobs_whatsapp(
    db: Session = Depends(db_session),
    company: str = Query(default="all"),
    location: str = Query(default="all"),
) -> dict[str, Any]:
    snapshot = get_snapshot(db)
    location_filter = location if location in {"all", "remote", "washington"} else "all"
    jobs = filter_jobs(snapshot.get("jobs") or [], company=company, location=location_filter, active_only=True)
    label_parts = ["Target company jobs"]
    if company != "all":
        label_parts.append(company)
    if location != "all":
        label_parts.append(location.title())
    text = format_whatsapp(jobs, title=" · ".join(label_parts))
    return {"success": True, "text": text, "count": len(jobs)}


@router.post("/jobs/target-companies/oracle-seed")
def update_oracle_seed(payload: TargetCompanyOracleSeedPayload, db: Session = Depends(db_session)) -> dict[str, Any]:
    merge_oracle_seed_entries(payload.jobs)
    snapshot = refresh_and_store(db, verify_oracle=True)
    return {
        "success": True,
        "merged": len(payload.jobs),
        "refreshedAt": snapshot.get("refreshedAt"),
        "oracleTotal": snapshot.get("companies", {}).get("Oracle", {}).get("total", 0),
    }


@router.get("/jobs/companies")
def list_target_companies() -> dict[str, Any]:
    from jobs.discovery.discovery.company_registry import CompanyRegistry
    reg = CompanyRegistry()
    return {"success": True, "companies": reg.list_companies()}


@router.post("/jobs/companies")
def upsert_target_company(payload: CompanyRegistryPayload) -> dict[str, Any]:
    from jobs.discovery.discovery.company_registry import CompanyRegistry
    reg = CompanyRegistry()
    reg.upsert_company(payload.company, payload.source, payload.config or {"careersUrl": payload.careersUrl})
    return {"success": True, "company": payload.company, "source": payload.source}


@router.post("/jobs/companies/discover")
async def discover_company_source(payload: CompanyDiscoverPayload) -> dict[str, Any]:
    import httpx
    from jobs.discovery.discovery.company_registry import JobSourceDiscoveryService
    async with httpx.AsyncClient(timeout=10.0) as client:
        res = await JobSourceDiscoveryService.discover_source(client, payload.company, payload.careersUrl)
        return {
            "success": True,
            "detectedSource": res.detected_source,
            "confidence": res.confidence,
            "sourceConfig": res.source_config,
        }


@router.get("/jobs/discover/sources/health")
def job_sources_health() -> dict[str, Any]:
    """Phase 19 Observability: Return runtime health status for all registered JobSourceAdapters."""
    from jobs.discovery.aggregation import job_aggregation_service
    return {
        "success": True,
        "sources": job_aggregation_service.get_health_summary(),
    }


@router.get("/jobs/discover/status")
def job_discover_status(db: Session = Depends(db_session)) -> dict[str, Any]:
    status = job_discover.get_status()
    snapshot = job_discover.get_snapshot(db)
    return {
        "success": True,
        **status,
        "indexedJobs": status.get("indexedJobs") or snapshot.get("totalJobs", 0),
    }


@router.get("/jobs/discover/sources/report")
def job_discover_sources_report() -> dict[str, Any]:
    """Per-source outcome of the most recent scrape: jobs kept and any error.

    Complements /sources/health, which reports the V2 registry's own counters.
    This reports what the scrape actually run by /jobs/discover/scrape did,
    including sources that failed — those used to vanish into a bare except.
    """
    from jobs.discovery.scraper_service import LAST_SOURCE_REPORT

    counts = LAST_SOURCE_REPORT.get("counts") or {}
    errors = LAST_SOURCE_REPORT.get("errors") or {}
    by_platform: dict[str, int] = {}
    for label, count in counts.items():
        platform = label.split("/", 1)[0]
        by_platform[platform] = by_platform.get(platform, 0) + count
    return {
        "success": True,
        "scrapedAt": LAST_SOURCE_REPORT.get("scrapedAt"),
        "byPlatform": dict(sorted(by_platform.items(), key=lambda kv: -kv[1])),
        "bySource": dict(sorted(counts.items(), key=lambda kv: -kv[1])),
        "errors": errors,
        "totalKept": sum(counts.values()),
        "failingSources": len(errors),
    }


@router.post("/jobs/discover/scrape/cancel")
def cancel_job_discover_scrape() -> dict[str, Any]:
    return job_discover.cancel_scrape()


@router.post("/jobs/discover/scrape")
async def start_job_discover_scrape(payload: JobDiscoverScrapePayload | None = None) -> dict[str, Any]:
    try:
        body = payload or JobDiscoverScrapePayload()
        mode = body.mode if body.mode in {"ats", "bigtech", "apify", "all"} else "ats"
        result = await job_discover.start_scrape_background(hours=body.hours, roles=body.roles, mode=mode)  # type: ignore[arg-type]
        if not result.get("success"):
            raise HTTPException(status_code=409, detail=result.get("error", "Scrape already running"))
        return result
    except HTTPException:
        raise
    except Exception as exc:
        return {"success": False, "error": str(exc)}


@router.post("/jobs/discover/rescore")
async def rescore_discovered_jobs(
    db: Session = Depends(db_session),
    force: bool = Query(default=False),
) -> dict[str, Any]:
    """Tier 1: refresh heuristic match scores for all indexed jobs (background)."""
    return await job_discover.start_tier1_rescore_background(force=force)


@router.post("/jobs/discover/analyze")
async def analyze_discovered_jobs(
    payload: RescoreJobsPayload,
    db: Session = Depends(db_session),
    use_qwen: bool = Query(default=True),
) -> dict[str, Any]:
    """Tier 2/3: gap analysis for specific jobs (gap click, add to assistant)."""
    if not payload.jobIds:
        raise HTTPException(status_code=400, detail="No jobs selected to analyze")
    return await job_discover.analyze_jobs_async(db, payload.jobIds, use_qwen=use_qwen)


@router.post("/jobs/discover/gap-analysis")
async def job_discover_gap_analysis(payload: JobGapAnalysisPayload, db: Session = Depends(db_session)) -> dict[str, Any]:
    """Return gap analysis; computes Tier 2 on demand if missing or stale."""
    from app.db.store import list_entities

    job = job_discover.get_job_by_id(db, payload.jobId)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")

    profile = get_kv(db, "profile") or {}
    documents = get_kv(db, "documents") or {}
    accomplishments = list_entities(db, "accomplishment")
    profile_hash = job_discover.compute_match_profile_hash(
        profile,
        documents=documents,
        accomplishments=accomplishments,
    )
    analysis = job.get("gapAnalysis")
    if analysis and job.get("gapProfileHash") == profile_hash:
        return {
            "success": True,
            "job": {
                "id": job.get("id"),
                "title": job.get("title"),
                "companyName": job.get("companyName"),
                "location": job.get("location"),
                "url": job.get("url"),
            },
            "analysis": analysis,
        }

    result = await job_discover.analyze_jobs_async(db, [payload.jobId], use_qwen=True)
    if not result.get("success"):
        raise HTTPException(status_code=404, detail=result.get("error") or "Analysis failed")
    refreshed = job_discover.get_job_by_id(db, payload.jobId)
    analysis = (refreshed or {}).get("gapAnalysis")
    if not analysis:
        raise HTTPException(status_code=500, detail="Analysis completed but gap data missing")

    return {
        "success": True,
        "job": {
            "id": refreshed.get("id"),
            "title": refreshed.get("title"),
            "companyName": refreshed.get("companyName"),
            "location": refreshed.get("location"),
            "url": refreshed.get("url"),
        },
        "analysis": analysis,
        "qwenStarted": result.get("qwenStarted", False),
    }


def _processed_autopilot_identity(db: Session) -> tuple[set[str], set[str]]:
    """Two identities for every job Autopilot already holds, in any status.

    Browse is for postings that have not been dealt with yet, so a job that
    Autopilot has queued, applied to, submitted, is reviewing, or has ruled out
    must not appear here. `get_synced_scraper_job_ids` only catches the ones
    added from this page, and Autopilot's own scraper finds postings Browse
    never touched, so the queue itself has to be consulted. Every status counts:
    there is nothing for the user to do on this page with a job that is already
    somewhere in the pipeline.

    Two identities are returned because neither is sufficient alone:

    * the **composite key**, which prefers the ATS's own posting id and so
      folds together the several host/path shapes one posting is published
      under; and
    * the **normalised URL**, which catches the case the key misses — the same
      URL with and without a query string, where one side can read an id off it
      and the other cannot.

    Matching on company and title alone is deliberately *not* done: two
    different posting ids at one employer are two different openings, and
    collapsing them would hide real jobs.
    """
    from autopilot.job_filter_ranker import (
        generate_composite_job_key,
        normalize_application_url,
    )
    from autopilot.persistence import AUTOPILOT_JOBS_CACHE_KEY, list_autopilot_jobs
    from shared.cache import read_cache

    def _load_all_autopilot_jobs() -> list[dict[str, Any]]:
        with session_scope() as inner_db:
            return list_autopilot_jobs(inner_db)

    all_jobs = read_cache.get(AUTOPILOT_JOBS_CACHE_KEY, 30.0, _load_all_autopilot_jobs)
    keys = {
        generate_composite_job_key(
            job.get("company") or "",
            job.get("title") or "",
            job.get("applicationUrl") or "",
            job.get("externalJobId") or "",
            job.get("location") or "",
        )
        for job in all_jobs
    }
    urls = {normalize_application_url(job.get("applicationUrl") or "") for job in all_jobs}
    urls.discard("")
    return keys, urls


def _is_unprocessed(job: dict[str, Any], processed_keys: set[str], processed_urls: set[str]) -> bool:
    """Whether this discovered posting is absent from the Autopilot pipeline."""
    from autopilot.job_filter_ranker import (
        generate_composite_job_key,
        normalize_application_url,
    )

    key = generate_composite_job_key(
        job.get("companyName") or "",
        job.get("title") or "",
        job.get("url") or "",
        str(job.get("externalJobId") or job.get("externalId") or ""),
        job.get("location") or "",
    )
    if key in processed_keys:
        return False
    return normalize_application_url(job.get("url") or "") not in processed_urls


@router.get("/jobs/discover")
def list_discovered_jobs(
    db: Session = Depends(db_session),
    q: str = Query(default=""),
    company: str = Query(default=""),
    location: str = Query(default=""),
    role: str = Query(default=""),
    source: str = Query(default="all"),
    specialties: str = Query(default=""),
    seniorities: str = Query(default=""),
    work_modes: str = Query(default=""),
    experience: str = Query(default=""),
    companies: str = Query(default=""),
    freshness: str = Query(default="all"),
    sponsorship: str = Query(default="all"),
    sort: str = Query(default="relevancy"),
    page: int = Query(default=1, ge=1),
    per_page: int = Query(default=30, ge=1, le=100),
) -> dict[str, Any]:
    snapshot = job_discover.get_snapshot(db)
    freshness_filter = freshness if freshness in {"12", "24", "48", "72", "168", "336", "720", "all"} else "all"
    sort_option = sort if sort in {"relevancy", "date", "company", "recent", "most_recent"} else "relevancy"
    from autopilot.scraper_import import get_synced_scraper_job_ids

    synced_ids = get_synced_scraper_job_ids(db)
    dismissed_ids = set(snapshot.get("dismissedIds") or [])
    processed_keys, processed_urls = _processed_autopilot_identity(db)
    available_jobs = [
        job for job in (snapshot.get("jobs") or [])
        if job.get("id") not in synced_ids
        and job.get("id") not in dismissed_ids
        and _is_unprocessed(job, processed_keys, processed_urls)
    ]
    from jobs.discovery.browse_filters import filter_facets
    available_jobs = filter_facets(available_jobs, specialties=specialties, seniorities=seniorities, work_modes=work_modes, experience=experience, companies=companies)
    jobs, total = job_discover.filter_jobs(
        available_jobs,
        q=q,
        company=company,
        location=location,
        role=role,
        source=source,
        freshness=freshness_filter,  # type: ignore[arg-type]
        sponsorship=sponsorship,
        sort=sort_option,  # type: ignore[arg-type]
        page=page,
        per_page=per_page,
    )
    total_pages = (total + per_page - 1) // per_page if per_page else 0
    logger.info(
        "[API] GET /jobs/discover: returned %d/%d jobs (page=%d, per_page=%d, q='%s', company='%s', loc='%s', source='%s', sort='%s')",
        len(jobs), total, page, per_page, q, company, location, source, sort_option,
    )
    return {
        "success": True,
        "jobs": jobs,
        "total": total,
        "indexedTotal": snapshot.get("totalJobs", 0),
        "assistantTotal": len(synced_ids),
        "dismissedTotal": len(dismissed_ids),
        "page": page,
        "perPage": per_page,
        "totalPages": total_pages,
        "scrapedAt": snapshot.get("scrapedAt"),
        "indexedCompanies": snapshot.get("companies", 0),
        "status": job_discover.get_status(),
    }


@router.get("/jobs/discover/filter-options")
def browse_filter_options(db: Session = Depends(db_session)):
    from jobs.discovery.browse_filters import filter_options
    from autopilot.scraper_import import get_synced_scraper_job_ids
    snapshot = job_discover.get_snapshot(db)
    excluded = get_synced_scraper_job_ids(db) | set(snapshot.get("dismissedIds") or [])
    processed_keys, processed_urls = _processed_autopilot_identity(db)
    jobs = [
        job for job in snapshot.get("jobs", [])
        if job.get("id") not in excluded
        and _is_unprocessed(job, processed_keys, processed_urls)
    ]
    result = filter_options(jobs)
    result["freshness"] = [value for value in ["24", "168", "720"] if job_discover.filter_jobs(jobs, freshness=value, per_page=1)[1]]
    result["sponsorship"] = [value for value in ["likely", "friendly", "unlikely"] if job_discover.filter_jobs(jobs, sponsorship=value, per_page=1)[1]]
    return result


@router.get("/jobs/discover/lookup")
def job_discover_lookup(url: str = Query(...), db: Session = Depends(db_session)) -> dict[str, Any]:
    job = job_discover.get_job_by_url(db, url)
    if not job:
        return {"success": False, "error": "Job not found in CareerOS scraper index"}
    freshness_meta = relevancy_engine.compute_freshness(job.get("updatedAt", ""))
    return {"success": True, "job": {**job, "freshness": freshness_meta}}


@router.get("/jobs/discover/stats")
def job_discover_stats(db: Session = Depends(db_session)) -> dict[str, Any]:
    return {"success": True, **job_discover.get_stats(db)}


@router.get("/jobs/discover/locations")
def job_discover_locations(db: Session = Depends(db_session)) -> dict[str, Any]:
    from autopilot.scraper_import import get_synced_scraper_job_ids

    snapshot = job_discover.get_snapshot(db)
    synced_ids = get_synced_scraper_job_ids(db)
    dismissed_ids = set(snapshot.get("dismissedIds") or [])
    available_jobs = [
        job for job in (snapshot.get("jobs") or [])
        if job.get("id") not in synced_ids and job.get("id") not in dismissed_ids
    ]
    return {
        "success": True,
        "locations": job_discover.get_location_options(available_jobs),
    }


@router.get("/jobs/discover/{job_id}/recruiter")
def job_discover_recruiter(job_id: str, db: Session = Depends(db_session)) -> dict[str, Any]:
    result = job_discover.job_recruiter_urls(db, job_id)
    if not result.get("success"):
        raise HTTPException(status_code=404, detail=result.get("error", "Job not found"))
    return result


@router.post("/jobs/discover/{job_id}/message")
def job_discover_message(
    job_id: str,
    payload: JobDiscoverMessagePayload | None = None,
    db: Session = Depends(db_session),
) -> dict[str, Any]:
    body = payload or JobDiscoverMessagePayload()
    result = job_discover.job_outreach(db, job_id, body.contactName)
    if not result.get("success"):
        raise HTTPException(status_code=404, detail=result.get("error", "Job not found"))
    return result


@router.post("/jobs/discover/{job_id}/save")
def job_discover_save(job_id: str, db: Session = Depends(db_session)) -> dict[str, Any]:
    result = job_discover.save_job_to_tracker(db, job_id)
    if not result.get("success"):
        raise HTTPException(status_code=404, detail=result.get("error", "Job not found"))
    return result


@router.post("/jobs/discover/{job_id}/dismiss")
def job_discover_dismiss(job_id: str, db: Session = Depends(db_session)) -> dict[str, Any]:
    return job_discover.dismiss_job(db, job_id)


@router.post("/jobs/discover/{job_id}/undismiss")
def job_discover_undismiss(job_id: str, db: Session = Depends(db_session)) -> dict[str, Any]:
    return job_discover.undismiss_job(db, job_id)


@router.get("/settings/job-boards")
def list_job_boards() -> dict[str, Any]:
    return {
        "success": True,
        "boards": [
            {"id": "indeed", "name": "Indeed", "connected": False},
            {"id": "naukri", "name": "Naukri", "connected": False},
        ],
    }


# ── Job-search workflow (fit, rank, outcomes, analytics) and external import ───
router.include_router(job_search_router)
router.include_router(job_import_router)
