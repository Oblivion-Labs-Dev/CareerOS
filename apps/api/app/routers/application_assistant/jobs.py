"""Application Assistant API routes — jobs domain."""

from ._common import *  # noqa: F401,F403

from app.db.store import session_scope
from app.services.read_cache import read_cache

# How stale a dashboard aggregate may get before a background refresh is
# kicked off. The page polls every 15s, so a few seconds of drift is
# invisible, and it keeps the expensive recompute off the request path.
DASHBOARD_STATS_TTL_SECONDS = 10.0

router = APIRouter(prefix="/application-assistant", tags=["application-assistant"])


# ── Jobs ──────────────────────────────────────────────────────────────────────

@router.get("/jobs")
def list_jobs(
    db: Session = Depends(db_session),
    run_id: str | None = Query(default=None),
    min_score: float = Query(default=0),
    include: str = Query(default=""),
    exclude: str = Query(default=""),
    source: str = Query(default="all"),
    q: str = Query(default=""),
    page: int = Query(default=1, ge=1),
    per_page: int = Query(default=30, ge=1, le=100),
) -> dict[str, Any]:
    from app.services.application_assistant.scraper_import import SCRAPER_DISCOVERY_RUN_ID

    jobs = list_discovered_jobs(db, discovery_run_id=run_id)
    matches = {}
    for job in jobs:
        match = get_job_match(db, job["id"])
        if match:
            matches[job["id"]] = match

    include_kw = [k.strip() for k in include.split(",") if k.strip()]
    exclude_kw = [k.strip() for k in exclude.split(",") if k.strip()]

    filtered = filter_jobs(
        jobs,
        matches,
        min_match_score=min_score,
        include_keywords=include_kw or None,
        exclude_keywords=exclude_kw or None,
    )

    scraper_jobs = [
        j
        for j in filtered
        if (j.get("discoveryRunId") == SCRAPER_DISCOVERY_RUN_ID or j.get("scraperJobId"))
        and j.get("addedToAssistant")
    ]
    discovery_jobs = [
        j
        for j in filtered
        if j.get("discoveryRunId") != SCRAPER_DISCOVERY_RUN_ID
        and not j.get("scraperJobId")
    ]
    counts = {
        "all": len([j for j in filtered if not j.get("scraperJobId") or j.get("addedToAssistant")]),
        "scraper": len(scraper_jobs),
        "discovery": len(discovery_jobs),
    }

    if source == "scraper":
        filtered = scraper_jobs
    elif source == "discovery":
        filtered = discovery_jobs
    else:
        filtered = [
            j
            for j in filtered
            if not j.get("scraperJobId") or j.get("addedToAssistant")
        ]

    if q.strip():
        needle = q.strip().lower()
        filtered = [
            j
            for j in filtered
            if needle in j.get("title", "").lower()
            or needle in j.get("company", "").lower()
            or needle in j.get("location", "").lower()
        ]

    total = len(filtered)
    start = (page - 1) * per_page
    page_jobs = filtered[start : start + per_page]
    total_pages = (total + per_page - 1) // per_page if per_page else 0

    return {
        "success": True,
        "jobs": page_jobs,
        "total": total,
        "page": page,
        "perPage": per_page,
        "totalPages": total_pages,
        "counts": counts,
    }


@router.post("/jobs/import-scraper")
async def import_scraper_job(payload: ScraperImportPayload, db: Session = Depends(db_session)) -> dict[str, Any]:
    """Import a scraper job into Application Assistant, add to queue, and start Qwen prep."""
    from app.services.application_assistant.agent import start_autonomous_prepare
    from app.services.application_assistant.scraper_import import import_scraper_job_by_id

    try:
        result = import_scraper_job_by_id(db, payload.scraperJobId)
        db.commit()
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc

    application_id = str(result.get("applicationId") or "")
    prep: dict[str, Any] = {"success": False}
    if application_id:
        prep = await start_autonomous_prepare(application_id)

    return {
        **result,
        "applicationId": application_id or prep.get("applicationId"),
        "prepStarted": bool(prep.get("success")),
        "prepError": prep.get("error"),
        "queue": prep.get("queue"),
    }


@router.post("/jobs/sync-scraper")
def sync_scraper_jobs_route(
    db: Session = Depends(db_session),
    min_score: float = Query(default=0, ge=0, le=100),
    limit: int | None = Query(default=None, ge=1),
    rescore: bool = Query(default=False),
) -> dict[str, Any]:
    """Bulk-import scraped jobs from Job Scraper into Application Assistant."""
    from app.services.application_assistant.scraper_import import sync_scraper_jobs

    return sync_scraper_jobs(db, min_relevancy_score=min_score, limit=limit, rescore=rescore)


@router.get("/jobs/scraper-status")
def scraper_jobs_status(db: Session = Depends(db_session)) -> dict[str, Any]:
    from app.services.application_assistant.scraper_import import scraper_sync_status

    return {"success": True, **scraper_sync_status(db)}


@router.get("/dashboard/stats")
def dashboard_stats() -> dict[str, Any]:
    # Served from a background-refreshed cache. Every number here is an
    # aggregate over the drafts table and the discovery snapshot, and none of
    # them has to be exact at the instant the page renders — so the request
    # returns whatever was last computed and a refresh runs on its own thread.
    # Recomputing inline made this endpoint take ~1.2s, which is what the user
    # felt as a lag when switching pages.
    return read_cache.get("dashboard_stats", DASHBOARD_STATS_TTL_SECONDS, _compute_dashboard_stats)


def _compute_dashboard_stats() -> dict[str, Any]:
    from app.services.application_assistant.qwen_activity import get_active_prep_from_logs, get_logs, get_metrics
    from app.services.application_assistant.agent import get_agent_run
    from app.services.application_assistant.scraper_import import scraper_sync_status

    # Opens its own session: this runs on a background thread, and a SQLAlchemy
    # Session belongs to the thread that created it.
    with session_scope() as db:
        return _dashboard_stats_payload(db)


def _dashboard_stats_payload(db: Session) -> dict[str, Any]:
    from app.services.application_assistant.qwen_activity import get_active_prep_from_logs, get_logs, get_metrics
    from app.services.application_assistant.agent import get_agent_run
    from app.services.application_assistant.scraper_import import scraper_sync_status

    drafts = list_application_drafts(db)
    status_counts: dict[str, int] = {}
    total_verified = 0
    total_missing = 0
    total_review = 0
    for draft in drafts:
        status = draft.get("status") or "unknown"
        status_counts[status] = status_counts.get(status, 0) + 1
        total_verified += draft.get("verifiedCount", 0) or 0
        total_missing += draft.get("missingCount", 0) or 0
        total_review += draft.get("reviewCount", 0) or 0

    active = get_active_prep_from_logs(db)
    agent_run = None
    if active and active.get("applicationId"):
        agent_run = get_agent_run(db, str(active["applicationId"]))

    return {
        "success": True,
        "statusCounts": status_counts,
        "totalApplications": len(drafts),
        "fieldTotals": {
            "verified": total_verified,
            "missing": total_missing,
            "needsReview": total_review,
        },
        "activePrep": active,
        "agentRun": agent_run,
        "recentLogs": get_logs(db, limit=10),
        "metrics": get_metrics(db),
        "scraper": scraper_sync_status(db),
    }


@router.get("/jobs/{job_id}")
def get_job(job_id: str, db: Session = Depends(db_session)) -> dict[str, Any]:
    job = get_discovered_job(db, job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    match = get_job_match(db, job_id)
    return {"success": True, "job": job, "match": match}


@router.post("/jobs/{job_id}/match")
async def refresh_match(job_id: str, db: Session = Depends(db_session)) -> dict[str, Any]:
    job = get_discovered_job(db, job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    profile = get_kv(db, "profile") or {}
    from app.services.application_assistant.candidate_match_context import match_job_with_context_async

    match = await match_job_with_context_async(db, job, profile)
    saved = save_job_match(db, match)
    return {"success": True, "match": saved}


