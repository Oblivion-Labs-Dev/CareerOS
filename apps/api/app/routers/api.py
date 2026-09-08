import json
import logging
import os
from collections.abc import Generator
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Depends, File, HTTPException, Query, Request, UploadFile
from fastapi.responses import HTMLResponse, Response
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.config import settings
from app.db.store import (
    EntityStore,
    delete_entity,
    get_entity,
    get_kv,
    import_legacy_db,
    legacy_db_snapshot,
    list_entities,
    new_id,
    now_iso,
    patch_entity,
    session_scope,
    set_kv,
    tracker_summary,
    upsert_entity,
)
from app.services.answer_engine import generate_answer, load_custom_answers
from app.services.api_dashboard import render_api_dashboard
from app.services.error_investigation import investigation_for_error_id, investigation_for_open_errors
from app.services.extension_packager import build_extension_zip, extension_info
from app.services.gmail_imap import GmailImapClient
from app.services.gmail_sender import SendEmailPayload, build_gmail_sender
from app.services.job_discover import relevancy_engine
from app.services.job_discover import store as job_discover
from app.services.job_discover.url_import import autoextract_job_from_url
from app.services.application_assistant.persistence import get_settings as get_aa_settings
from app.services.llm import analyze_accomplishment, generate_resume_bullets_for_job
from app.services.log_store import append_client_log, clear_client_logs, read_client_logs
from app.services.outreach_campaign_store import load_campaigns
from app.services.resume_intelligence.ats_score import compute_ats_score
from app.services.resume_intelligence import resume_profiles as resume_profiles_service
from app.services.resume_intelligence.tailoring import (
    TAILORING_TONE_BY_MODE,
    build_tailoring_diff,
    passthrough_diff,
)
from app.services.resume_parser import parse_resume_into_profile
from app.services.runtime_metrics import metrics_snapshot_with_logs
from app.services.tracker import inbox as tracker_inbox
from app.services.tracker import pipeline as tracker_pipeline
from app.services.target_company_jobs import (
    filter_jobs,
    format_whatsapp,
    get_snapshot,
    merge_oracle_seed_entries,
    refresh_and_store,
    should_refresh_weekly,
)

logger = logging.getLogger("career_os.api")

router = APIRouter()


def require_legacy_sync_auth(request: Request) -> None:
    """Guard full DB overwrite when not in local dev mode."""
    if settings.career_os_dev_mode:
        return
    if not settings.career_os_api_key:
        raise HTTPException(status_code=503, detail="Legacy sync is disabled until CAREER_OS_API_KEY is set")
    provided = request.headers.get("x-career-os-api-key", "")
    if provided != settings.career_os_api_key:
        raise HTTPException(status_code=401, detail="Invalid API key")


def require_protected_action_auth(request: Request) -> None:
    """Guard sensitive write actions when not in local dev mode."""
    if settings.career_os_dev_mode:
        return
    if not settings.career_os_api_key:
        raise HTTPException(status_code=503, detail="Action disabled until CAREER_OS_API_KEY is set")
    provided = request.headers.get("x-career-os-api-key", "")
    if provided != settings.career_os_api_key:
        raise HTTPException(status_code=401, detail="Invalid API key")


def require_gmail_configured() -> tuple[str, str]:
    if not settings.gmail_user or not settings.gmail_app_password:
        raise HTTPException(
            status_code=503,
            detail="Gmail is not configured. Set GMAIL_USER and GMAIL_APP_PASSWORD in apps/api/.env",
        )
    return settings.gmail_user, settings.gmail_app_password


def db_session() -> Generator[Session, None, None]:
    with session_scope() as db:
        yield db


class ProfilePayload(BaseModel):
    profile: dict[str, Any]


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


class ApplicationPayload(BaseModel):
    application: dict[str, Any]


class ApplicationPatchPayload(BaseModel):
    patch: dict[str, Any]


class FieldMappingPayload(BaseModel):
    mapping: dict[str, Any]


class ResumePayload(BaseModel):
    resume: dict[str, Any]


class CoverLetterGeneratePayload(BaseModel):
    jobId: str | None = None
    companyName: str | None = None
    roleTitle: str | None = None
    jobDescription: str | None = None
    tone: str | None = "professional"


class QuestionAnswerPayload(BaseModel):
    question: str
    context: dict[str, Any] | None = None


class AnalyticsEventPayload(BaseModel):
    type: str
    module: str | None = None
    message: str
    metadata: dict[str, Any] | None = None


class ReferralPayload(BaseModel):
    referral: dict[str, Any]


class ReferralPatchPayload(BaseModel):
    patch: dict[str, Any]


class ReferralAskMessagePayload(BaseModel):
    message: str


class TargetCompanyOracleSeedPayload(BaseModel):
    jobs: list[dict[str, Any]] = Field(default_factory=list)


class TargetCompanyRefreshPayload(BaseModel):
    verifyOracle: bool = True


class JobGapAnalysisPayload(BaseModel):
    jobId: str = Field(min_length=1)


class RescoreJobsPayload(BaseModel):
    jobIds: list[str] = Field(default_factory=list)


DEFAULT_REFERRAL_ASK_MESSAGE = """I hope you're doing well! I came across a job that aligns closely with my background and was wondering if you'd be open to referring me. I have 7+ years of experience at Microsoft and Amazon building distributed systems, AI infrastructure, and cloud-native platforms, and I've recently been focused on agentic AI and developer tooling.

I believe my experience is a strong match for the role. If you're comfortable referring me, I'd really appreciate it. I've attached the job link and my resume for context. Thanks for taking the time to consider my request!"""


@router.get("/", response_class=HTMLResponse)
def root(db: Session = Depends(db_session)) -> HTMLResponse:
    return HTMLResponse(render_api_dashboard(db))


@router.get("/metrics")
def metrics() -> dict[str, Any]:
    client_errors = sum(
        1 for entry in read_client_logs(limit=200) if str(entry.get("level") or "").lower() == "error"
    )
    return metrics_snapshot_with_logs(client_log_errors=client_errors)


@router.get("/errors/{error_id}/investigate")
def get_error_investigation(error_id: str) -> dict[str, Any]:
    try:
        payload = investigation_for_error_id(error_id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return {"success": True, **payload}


@router.post("/errors/{error_id}/investigate")
def request_error_investigation(error_id: str) -> dict[str, Any]:
    try:
        payload = investigation_for_error_id(error_id, mark_requested=True)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return {"success": True, **payload}


@router.post("/errors/investigate-open")
def request_open_errors_investigation() -> dict[str, Any]:
    try:
        payload = investigation_for_open_errors()
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return {"success": True, **payload}


@router.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok", "service": "career-os-api"}


@router.get("/profile")
def get_profile(db: Session = Depends(db_session)) -> dict[str, Any]:
    return {"profile": get_kv(db, "profile")}


@router.post("/profile")
def upsert_profile(payload: ProfilePayload, db: Session = Depends(db_session)) -> dict[str, Any]:
    set_kv(db, "profile", payload.profile)
    return {"success": True, "profile": payload.profile}


@router.get("/api/db")
def get_api_db(db: Session = Depends(db_session)) -> dict[str, Any]:
    return {
        "success": True,
        "profile": get_kv(db, "profile"),
        "documents": get_kv(db, "documents") or {"defaultResume": None, "defaultCoverLetter": None},
        "applications": list_entities(db, "application"),
        "jobs": list_entities(db, "job"),
        "learnedAnswers": list_entities(db, "learned_answer"),
        "sessions": list_entities(db, "autofill_session"),
        "fieldMappings": list_entities(db, "field_mapping"),
        "activityEvents": list_entities(db, "career_event"),
    }


@router.post("/api/db")
def upsert_api_db(payload: dict[str, Any], db: Session = Depends(db_session)) -> dict[str, Any]:
    if "profile" in payload and payload["profile"] is not None:
        set_kv(db, "profile", payload["profile"])
    if "documents" in payload and payload["documents"] is not None:
        set_kv(db, "documents", payload["documents"])
    return {"success": True}


@router.post("/api/parse-resume")
def parse_resume_route(db: Session = Depends(db_session)) -> dict[str, Any]:
    docs = get_kv(db, "documents") or {}
    resume = docs.get("defaultResume") or {}
    text = resume.get("text") or resume.get("content") or ""
    if text:
        parsed = parse_resume_into_profile(text)
        current = get_kv(db, "profile") or {}
        merged = {**current, **parsed}
        set_kv(db, "profile", merged)
        return {"success": True, "parsed": True, "profile": merged}
    return {"success": True, "parsed": False, "reason": "No resume text found"}


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


@router.get("/jobs/companies")
def list_target_companies() -> dict[str, Any]:
    from app.services.job_discover.discovery.company_registry import CompanyRegistry
    reg = CompanyRegistry()
    return {"success": True, "companies": reg.list_companies()}


@router.post("/jobs/companies")
def upsert_target_company(payload: CompanyRegistryPayload) -> dict[str, Any]:
    from app.services.job_discover.discovery.company_registry import CompanyRegistry
    reg = CompanyRegistry()
    reg.upsert_company(payload.company, payload.source, payload.config or {"careersUrl": payload.careersUrl})
    return {"success": True, "company": payload.company, "source": payload.source}


@router.post("/jobs/companies/discover")
async def discover_company_source(payload: CompanyDiscoverPayload) -> dict[str, Any]:
    import httpx
    from app.services.job_discover.discovery.company_registry import JobSourceDiscoveryService
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
    from app.services.job_discover.aggregation import job_aggregation_service
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


@router.get("/jobs/discover")
def list_discovered_jobs(
    db: Session = Depends(db_session),
    q: str = Query(default=""),
    company: str = Query(default=""),
    location: str = Query(default=""),
    role: str = Query(default=""),
    source: str = Query(default="all"),
    freshness: str = Query(default="all"),
    sponsorship: str = Query(default="all"),
    sort: str = Query(default="relevancy"),
    page: int = Query(default=1, ge=1),
    per_page: int = Query(default=30, ge=1, le=100),
) -> dict[str, Any]:
    snapshot = job_discover.get_snapshot(db)
    freshness_filter = freshness if freshness in {"12", "24", "48", "72", "168", "336", "720", "all"} else "all"
    sort_option = sort if sort in {"relevancy", "date", "company", "recent", "most_recent"} else "relevancy"
    from app.services.application_assistant.scraper_import import get_synced_scraper_job_ids

    synced_ids = get_synced_scraper_job_ids(db)
    dismissed_ids = set(snapshot.get("dismissedIds") or [])
    available_jobs = [
        job for job in (snapshot.get("jobs") or [])
        if job.get("id") not in synced_ids and job.get("id") not in dismissed_ids
    ]
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
    from app.services.application_assistant.scraper_import import get_synced_scraper_job_ids

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


class JobDiscoverMessagePayload(BaseModel):
    contactName: str = "[Name]"


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


@router.post("/applications")
def create_application(payload: ApplicationPayload, db: Session = Depends(db_session)) -> dict[str, Any]:
    saved = upsert_entity(db, "application", payload.application)
    return {"success": True, "application": saved}


@router.get("/applications")
def list_applications(db: Session = Depends(db_session)) -> dict[str, Any]:
    return {"applications": list_entities(db, "application")}


@router.get("/tracker/summary")
def get_tracker_summary(db: Session = Depends(db_session)) -> dict[str, Any]:
    return tracker_summary(db)


@router.post("/tracker/sync-gmail")
def sync_gmail_tracker(db: Session = Depends(db_session)) -> dict[str, Any]:
    """Scan Gmail for application-confirmation emails from jobs applied to
    outside CareerOS, and track genuinely new ones alongside Autopilot's own."""
    from app.services.tracker.gmail_applications import sync_gmail_applications

    return sync_gmail_applications(db)


@router.get("/tracker/pipeline")
def get_tracker_pipeline(db: Session = Depends(db_session)) -> dict[str, Any]:
    """Kanban view of the post-apply funnel: Applied -> Ghosted -> Interviewing -> Rejected -> Offer."""
    return tracker_pipeline.build_pipeline(db)


@router.get("/applications/export.csv")
def export_applications(db: Session = Depends(db_session)) -> Response:
    csv_text = tracker_pipeline.export_applications_csv(db)
    return Response(
        content=csv_text,
        media_type="text/csv",
        headers={"Content-Disposition": "attachment; filename=careeros-applications.csv"},
    )


@router.post("/applications/import")
async def import_applications(file: UploadFile = File(...), db: Session = Depends(db_session)) -> dict[str, Any]:
    raw = await file.read()
    try:
        content = raw.decode("utf-8-sig")
    except UnicodeDecodeError:
        content = raw.decode("latin-1")
    result = tracker_pipeline.import_applications_csv(db, content)
    return {"success": True, **result}


@router.patch("/applications/{application_id}")
def update_application(
    application_id: str,
    payload: ApplicationPatchPayload,
    db: Session = Depends(db_session),
) -> dict[str, Any]:
    updated = patch_entity(db, "application", application_id, payload.patch)
    if not updated:
        raise HTTPException(status_code=404, detail="Application not found")
    return {"success": True, "application": updated}


@router.post("/autofill/map-field")
def map_field(payload: FieldMappingPayload, db: Session = Depends(db_session)) -> dict[str, Any]:
    mapping = upsert_entity(
        db,
        "field_mapping",
        {
            **payload.mapping,
            "id": payload.mapping.get("id") or new_id("map_"),
            "lastUsedAt": now_iso(),
        },
    )
    return {"success": True, "mapping": mapping}


@router.get("/autofill/mappings")
def list_mappings(db: Session = Depends(db_session)) -> dict[str, Any]:
    return {"mappings": list_entities(db, "field_mapping")}


@router.post("/documents/resume")
def upload_resume(payload: ResumePayload, db: Session = Depends(db_session)) -> dict[str, Any]:
    documents = get_kv(db, "documents") or {"defaultResume": None, "defaultCoverLetter": None}
    resume = {
        **payload.resume,
        "id": payload.resume.get("id") or new_id("resume_"),
        "updatedAt": now_iso(),
    }
    documents["defaultResume"] = resume
    set_kv(db, "documents", documents)
    return {"success": True, "resume": resume}


@router.get("/documents/resume")
def get_resume(db: Session = Depends(db_session)) -> dict[str, Any]:
    documents = get_kv(db, "documents") or {}
    return {"resume": documents.get("defaultResume")}


@router.post("/cover-letter/generate")
async def generate_cover_letter(payload: CoverLetterGeneratePayload, db: Session = Depends(db_session)) -> dict[str, Any]:
    from app.services.job_search.cover_letter_pipeline import generate_cover_letter_with_review

    profile = get_kv(db, "profile") or {}
    company = payload.companyName or "the company"
    role = payload.roleTitle or profile.get("targetRole") or "the role"
    result = await generate_cover_letter_with_review(
        profile,
        company=company,
        role=role,
        job_description=payload.jobDescription or "",
        tone=payload.tone or "professional",
        use_llm=True,
    )
    letter = {
        "id": new_id("cl_"),
        "jobId": payload.jobId,
        "title": result["title"],
        "content": result["content"],
        "tone": payload.tone,
        "pipelineMode": result["pipelineMode"],
        "reviewerNotes": result["reviewerNotes"],
        "styleIssues": result["styleIssues"],
        "createdAt": now_iso(),
    }
    upsert_entity(db, "cover_letter", letter)
    return {"success": True, "coverLetter": letter}


@router.post("/questions/answer")
def answer_question(payload: QuestionAnswerPayload, db: Session = Depends(db_session)) -> dict[str, Any]:
    learned = list_entities(db, "learned_answer")
    normalized = payload.question.strip().lower()
    for item in learned:
        if item.get("question", "").strip().lower() == normalized:
            return {"success": True, "answer": item.get("answer"), "source": "learned"}
    profile = get_kv(db, "profile") or {}
    context = payload.context or {}
    company = str(context.get("companyName") or context.get("company") or "")
    role = str(context.get("roleTitle") or context.get("role") or profile.get("targetRole") or "")
    engine_answer = generate_answer(payload.question, company=company, role_title=role, profile=profile)
    if engine_answer:
        return {"success": True, "answer": engine_answer, "source": "answer_engine"}
    fallback = (
        f"Based on my experience as {profile.get('currentTitle', 'a professional')}, "
        f"I would approach this thoughtfully and align with {profile.get('targetRole', 'the role')} expectations."
    )
    return {"success": True, "answer": fallback, "source": "generated"}


@router.get("/questions/answer-bank")
def get_answer_bank() -> dict[str, Any]:
    return {"success": True, "answers": load_custom_answers()}


@router.post("/analytics/event")
def track_event(payload: AnalyticsEventPayload, db: Session = Depends(db_session)) -> dict[str, Any]:
    event = upsert_entity(
        db,
        "career_event",
        {
            "id": new_id("evt_"),
            "type": payload.type,
            "module": payload.module,
            "message": payload.message,
            "metadata": payload.metadata or {},
            "createdAt": now_iso(),
        },
    )
    return {"success": True, "event": event}


@router.get("/referrals")
def list_referrals(db: Session = Depends(db_session)) -> dict[str, Any]:
    return {"referrals": list_entities(db, "referral")}


@router.get("/referrals/ask-message")
def get_referral_ask_message(db: Session = Depends(db_session)) -> dict[str, Any]:
    stored = get_kv(db, "referral_ask_message")
    message = stored if isinstance(stored, str) and stored.strip() else DEFAULT_REFERRAL_ASK_MESSAGE
    return {"message": message}


@router.put("/referrals/ask-message")
def save_referral_ask_message(
    payload: ReferralAskMessagePayload,
    db: Session = Depends(db_session),
) -> dict[str, Any]:
    message = payload.message.strip()
    if not message:
        raise HTTPException(status_code=400, detail="Message cannot be empty")
    set_kv(db, "referral_ask_message", message)
    return {"success": True, "message": message}


@router.post("/referrals")
def create_referral(payload: ReferralPayload, db: Session = Depends(db_session)) -> dict[str, Any]:
    saved = upsert_entity(
        db,
        "referral",
        {
            **payload.referral,
            "id": payload.referral.get("id") or new_id("ref_"),
            "status": payload.referral.get("status") or "active",
        },
    )
    return {"success": True, "referral": saved}


@router.patch("/referrals/{referral_id}")
def update_referral(
    referral_id: str,
    payload: ReferralPatchPayload,
    db: Session = Depends(db_session),
) -> dict[str, Any]:
    updated = patch_entity(db, "referral", referral_id, payload.patch)
    if not updated:
        raise HTTPException(status_code=404, detail="Referral contact not found")
    return {"success": True, "referral": updated}


@router.delete("/referrals/{referral_id}")
def delete_referral(referral_id: str, db: Session = Depends(db_session)) -> dict[str, Any]:
    row = (
        db.query(EntityStore)
        .filter(EntityStore.entity_type == "referral", EntityStore.id == referral_id)
        .one_or_none()
    )
    if not row:
        raise HTTPException(status_code=404, detail="Referral contact not found")
    db.delete(row)
    return {"success": True}


# Gmail / recruiter email (migrated from Arsenal scripts/email)
@router.get("/email/verify")
def verify_gmail_connection() -> dict[str, Any]:
    if not settings.gmail_user or not settings.gmail_app_password:
        return {
            "success": False,
            "configured": False,
            "user": None,
            "message": "Gmail is not configured. Set GMAIL_USER and GMAIL_APP_PASSWORD in apps/api/.env",
        }
    sender = build_gmail_sender(settings.gmail_user, settings.gmail_app_password)
    return {
        "success": sender.verify_connection(),
        "configured": True,
        "user": settings.gmail_user,
    }


@router.post("/email/send")
def send_email(payload: SendEmailPayload, request: Request) -> dict[str, Any]:
    require_protected_action_auth(request)
    user, app_password = require_gmail_configured()
    sender = build_gmail_sender(user, app_password)
    try:
        result = sender.send(payload)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc
    return {"success": True, **result}


@router.get("/email/recruiter-threads")
def list_recruiter_threads(limit: int = Query(default=10, ge=1, le=150)) -> dict[str, Any]:
    user, app_password = require_gmail_configured()
    client = GmailImapClient(user, app_password)
    threads = client.fetch_threads(limit=limit)
    return {"success": True, "threads": threads, "count": len(threads)}


@router.get("/email/recruiter-threads/classified")
async def list_classified_recruiter_threads(limit: int = Query(default=20, ge=1, le=100), db: Session = Depends(db_session)) -> dict[str, Any]:
    """Inbox view: recruiter threads auto-tagged Verification/Rejection/Interview/Assessment/
    Reminder/Offer/Applied (rule-based, cached per IMAP UID; LLM fallback only when ambiguous
    and OPENROUTER_API_KEY is set)."""
    user, app_password = require_gmail_configured()
    client = GmailImapClient(user, app_password)
    threads = await tracker_inbox.fetch_and_classify_threads(db, client, limit=limit)
    counts: dict[str, int] = {}
    for thread in threads:
        category = thread.get("category") or "uncategorized"
        counts[category] = counts.get(category, 0) + 1
    return {"success": True, "threads": threads, "count": len(threads), "categoryCounts": counts}


@router.get("/email/recruiter-conversations")
def get_cached_recruiter_conversations() -> dict[str, Any]:
    path = Path(__file__).resolve().parents[2] / "data" / "recruiter_conversations.json"
    if not path.exists():
        return {"success": True, "conversations": [], "count": 0, "source": "cache-missing"}
    conversations = json.loads(path.read_text(encoding="utf-8"))
    return {"success": True, "conversations": conversations, "count": len(conversations), "source": str(path)}


def _load_bounced_email_details() -> tuple[dict[str, dict[str, Any]], int, dict[str, int]]:
    path = Path(__file__).resolve().parents[2] / "data" / "bounced_recruiter_emails.json"
    if not path.exists():
        return {}, 0, {}
    payload = json.loads(path.read_text(encoding="utf-8"))
    details: dict[str, dict[str, Any]] = {}
    for item in payload.get("invalidEmails", []):
        email = str(item.get("email", "")).lower()
        if not email:
            continue
        details[email] = {
            "bounceCategory": item.get("bounceCategory") or "other",
            "bounceCategoryLabel": item.get("bounceCategoryLabel") or "Other bounce",
            "bounceReason": item.get("bounceReason") or "Delivery failed",
        }
    category_counts = {
        str(key): int(value)
        for key, value in (payload.get("categoryCounts") or {}).items()
        if key
    }
    return details, int(payload.get("bounceMessages", 0) or 0), category_counts


def _load_bounced_email_set() -> tuple[set[str], int]:
    details, bounce_messages, _ = _load_bounced_email_details()
    return set(details), bounce_messages


def _compute_delivery_stats(
    results: list[dict[str, Any]],
    bounce_details: dict[str, dict[str, Any]],
) -> dict[str, Any]:
    sent = [result for result in results if result.get("status") == "sent"]
    failed = [result for result in results if result.get("status") == "failed"]
    bounced_sent = [result for result in sent if str(result.get("email", "")).lower() in bounce_details]
    category_counts: dict[str, int] = {}
    for result in bounced_sent:
        email = str(result.get("email", "")).lower()
        category = bounce_details.get(email, {}).get("bounceCategory") or "other"
        category_counts[category] = category_counts.get(category, 0) + 1
    return {
        "delivered": len(sent) - len(bounced_sent),
        "bounced": len(bounced_sent),
        "undelivered": len(bounced_sent) + len(failed),
        "invalid": category_counts.get("invalid_address", 0),
        "notDelivered": category_counts.get("not_delivered", 0),
        "mailboxFull": category_counts.get("mailbox_full", 0),
        "mailboxUnavailable": category_counts.get("mailbox_unavailable", 0),
        "messageBlocked": category_counts.get("message_blocked", 0),
        "temporaryFailure": category_counts.get("temporary_failure", 0),
        "otherBounce": category_counts.get("other", 0),
        "bounceCategories": category_counts,
        "sendFailed": len(failed),
        "pending": len([result for result in results if result.get("status") in {"pending", "retrying", "paused"}]),
    }


def _enrich_outreach_result(
    result: dict[str, Any],
    bounce_details: dict[str, dict[str, Any]],
) -> dict[str, Any]:
    enriched = dict(result)
    email = str(enriched.get("email", "")).lower()
    status = enriched.get("status")
    detail = bounce_details.get(email)
    if status == "sent" and detail:
        category = detail.get("bounceCategory") or "other"
        enriched["deliveryStatus"] = category if category != "other" else "bounced"
        enriched["bounceCategory"] = category
        enriched["bounceCategoryLabel"] = detail.get("bounceCategoryLabel") or "Bounced"
        enriched["bounceReason"] = detail.get("bounceReason") or "Delivery failed"
        enriched["error"] = detail.get("bounceReason") or enriched.get("error")
    elif status == "sent":
        enriched["deliveryStatus"] = "delivered"
        enriched["bounceCategory"] = "delivered"
        enriched["bounceCategoryLabel"] = "Delivered"
    elif status == "failed":
        enriched["deliveryStatus"] = "failed"
        enriched["bounceCategory"] = "send_failed"
        enriched["bounceCategoryLabel"] = "Send failed"
        # keep original SMTP error under error
    else:
        enriched["deliveryStatus"] = "pending"
        enriched["bounceCategory"] = "pending"
        enriched["bounceCategoryLabel"] = "Pending"
    return enriched


def _prepare_outreach_campaign(
    campaign: dict[str, Any],
    bounce_details: dict[str, dict[str, Any]],
    bounce_messages: int,
    recent_limit: int,
) -> dict[str, Any]:
    prepared = dict(campaign)
    results = list(prepared.get("results") or [])
    prepared["deliveryStats"] = {
        **_compute_delivery_stats(results, bounce_details),
        "bounceMessages": bounce_messages,
    }
    recent = sorted(
        results,
        key=lambda result: str(result.get("sentAt") or ""),
        reverse=True,
    )[:recent_limit]
    prepared["results"] = [_enrich_outreach_result(result, bounce_details) for result in recent]
    prepared["recentLimit"] = recent_limit
    prepared["resultsTotal"] = len(results)
    return prepared


@router.get("/email/outreach-campaigns")
def get_recruiter_outreach_campaigns(
    limit: int = Query(default=20, ge=1, le=100),
    recent_limit: int = Query(default=10, ge=1, le=100),
) -> dict[str, Any]:
    path = Path(__file__).resolve().parents[2] / "data" / "recruiter_outreach_campaigns.json"
    if not path.exists():
        return {"success": True, "campaigns": [], "count": 0, "source": "cache-missing"}
    loaded = load_campaigns(path)
    raw_campaigns = loaded.campaigns
    bounce_details, bounce_messages, _ = _load_bounced_email_details()
    full_campaigns = raw_campaigns[:limit]
    campaigns = [
        _prepare_outreach_campaign(campaign, bounce_details, bounce_messages, recent_limit)
        for campaign in full_campaigns
    ]
    all_full_results = [result for campaign in full_campaigns for result in (campaign.get("results") or [])]
    aggregate_stats = {
        **_compute_delivery_stats(all_full_results, bounce_details),
        "bounceMessages": bounce_messages,
    }
    return {
        "success": True,
        "campaigns": campaigns,
        "count": len(campaigns),
        "aggregateDeliveryStats": aggregate_stats,
        "source": str(path),
        "recovered": loaded.recovered,
        "warning": loaded.warning,
        "discardedIncompleteItems": loaded.discarded_incomplete_items,
    }


# Legacy extension compatibility
@router.get("/api/db")
def legacy_get_db(db: Session = Depends(db_session)) -> dict[str, Any]:
    return legacy_db_snapshot(db)


@router.post("/api/db")
def legacy_post_db(
    payload: dict[str, Any],
    request: Request,
    db: Session = Depends(db_session),
) -> dict[str, Any]:
    require_legacy_sync_auth(request)
    import_legacy_db(db, payload)
    return {"success": True}


class ParseResumePayload(BaseModel):
    force: bool = False


@router.post("/api/parse-resume")
async def legacy_parse_resume(payload: ParseResumePayload | None = None, db: Session = Depends(db_session)) -> dict[str, Any]:
    profile = get_kv(db, "profile") or {}
    documents = get_kv(db, "documents") or {}
    try:
        result = parse_resume_into_profile(profile, documents, force=bool(payload and payload.force))
        set_kv(db, "profile", result["profile"])
        db.commit()
        tier1 = await job_discover.start_tier1_rescore_background(force=True)
        return {"success": True, **result, "tier1Rescore": tier1}
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.get("/api/logs")
def legacy_get_logs(limit: int = 100) -> dict[str, Any]:
    logs = read_client_logs(limit)
    return {"success": True, "logs": logs}


@router.post("/api/logs")
def legacy_post_log(payload: dict[str, Any]) -> dict[str, Any]:
    if not payload.get("message"):
        raise HTTPException(status_code=400, detail="message is required")
    append_client_log(payload)
    return {"success": True}


@router.delete("/api/logs")
def legacy_delete_logs() -> dict[str, Any]:
    clear_client_logs()
    return {"success": True}


@router.get("/extension/info")
def get_extension_info() -> dict[str, Any]:
    return extension_info()


@router.get("/extension/download")
def download_extension(browser: str = Query(default="chrome")) -> Response:
    normalized = browser.lower().strip()
    engine = "firefox" if normalized == "firefox" else "chromium"
    try:
        payload, filename = build_extension_zip(engine)  # type: ignore[arg-type]
    except FileNotFoundError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    return Response(
        content=payload,
        media_type="application/zip",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


class AccomplishmentPayload(BaseModel):
    accomplishment: dict[str, Any]


class AiGeneratePayload(BaseModel):
    description: str
    currentData: dict[str, Any] | None = None


class ResumeGeneratePayload(BaseModel):
    accomplishmentIds: list[str]
    targetCompany: str
    targetRole: str
    jobDescription: str
    experienceLevel: str = "Senior"
    tone: str = "professional"
    maxPages: int = 1
    targetAtsScore: int = 85


class ResumeTailorPayload(BaseModel):
    accomplishmentIds: list[str] | None = None
    jobId: str | None = None
    targetCompany: str = ""
    targetRole: str = ""
    jobDescription: str = ""
    experienceLevel: str = "Senior"
    tone: str = "professional"
    maxPages: int = 1
    targetAtsScore: int = 85
    mode: str | None = None


class ResumeTailorApprovePayload(BaseModel):
    mode: str
    jobId: str | None = None
    targetCompany: str = ""
    targetRole: str = ""
    bullets: list[dict[str, Any]] = Field(default_factory=list)
    skillsList: list[str] = Field(default_factory=list)


class ResumeProfileCreatePayload(BaseModel):
    name: str
    resume: dict[str, Any] | None = None


class ResumeProfilePatchPayload(BaseModel):
    name: str | None = None
    resume: dict[str, Any] | None = None


@router.get("/accomplishments")
def list_accomplishments_route(db: Session = Depends(db_session)) -> dict[str, Any]:
    return {"accomplishments": list_entities(db, "accomplishment")}


@router.post("/accomplishments")
def save_accomplishment_route(payload: AccomplishmentPayload, db: Session = Depends(db_session)) -> dict[str, Any]:
    saved = upsert_entity(db, "accomplishment", payload.accomplishment)
    return {"success": True, "accomplishment": saved}


@router.delete("/accomplishments/{accomplishment_id}")
def delete_accomplishment_route(accomplishment_id: str, db: Session = Depends(db_session)) -> dict[str, Any]:
    deleted = delete_entity(db, "accomplishment", accomplishment_id)
    if not deleted:
        raise HTTPException(status_code=404, detail="Accomplishment not found")
    return {"success": True}


@router.post("/accomplishments/ai-generate")
async def ai_generate_accomplishment_route(payload: AiGeneratePayload) -> dict[str, Any]:
    result = await analyze_accomplishment(payload.description, payload.currentData)
    return {"success": True, "accomplishment": result}


@router.post("/resume/generate")
async def generate_resume_route(payload: ResumeGeneratePayload, db: Session = Depends(db_session)) -> dict[str, Any]:
    requested_ids = list(dict.fromkeys(payload.accomplishmentIds))
    if not requested_ids:
        raise HTTPException(status_code=422, detail="Select at least one accomplishment before generating a resume")

    all_accs = list_entities(db, "accomplishment")
    selected_accs = [a for a in all_accs if a.get("id") in requested_ids]
    selected_ids = {str(accomplishment.get("id")) for accomplishment in selected_accs}
    missing_ids = [accomplishment_id for accomplishment_id in requested_ids if accomplishment_id not in selected_ids]
    if missing_ids:
        raise HTTPException(
            status_code=422,
            detail={
                "message": "One or more selected accomplishments no longer exist",
                "missingAccomplishmentIds": missing_ids,
            },
        )

    result = await generate_resume_bullets_for_job(
        accomplishments=selected_accs,
        target_company=payload.targetCompany,
        target_role=payload.targetRole,
        job_description=payload.jobDescription,
        experience_level=payload.experienceLevel,
        tone=payload.tone,
        max_pages=payload.maxPages,
        target_ats=payload.targetAtsScore
    )
    if result is None:
        raise HTTPException(
            status_code=503,
            detail="Resume generation is temporarily unavailable. No synthetic fallback content was returned.",
        )
    return {"success": True, "result": result}


@router.post("/resume/tailor")
async def tailor_resume_route(payload: ResumeTailorPayload, db: Session = Depends(db_session)) -> dict[str, Any]:
    """Job-specific bullet tailoring, gated by the Off/Honest/Aggressive dial.

    Always returns a diff (original vs. tailored, per bullet) — never writes
    anything. The caller applies the result explicitly via a separate accept step.
    """
    mode = payload.mode or get_aa_settings(db).get("tailoringMode", "honest")
    if mode not in TAILORING_TONE_BY_MODE:
        mode = "honest"

    all_accs = list_entities(db, "accomplishment")
    if payload.accomplishmentIds:
        requested_ids = set(payload.accomplishmentIds)
        selected_accs = [a for a in all_accs if a.get("id") in requested_ids]
    else:
        selected_accs = all_accs

    if mode == "off":
        return {"success": True, "result": passthrough_diff(selected_accs)}

    target_company = payload.targetCompany
    target_role = payload.targetRole
    job_description = payload.jobDescription
    if payload.jobId and not (target_company and target_role and job_description):
        job = get_entity(db, "job", payload.jobId) or get_entity(db, "aa_discovered_job", payload.jobId)
        if job:
            target_company = target_company or str(job.get("companyName") or job.get("company") or "")
            target_role = target_role or str(job.get("title") or job.get("roleTitle") or "")
            job_description = job_description or str(job.get("description") or "")

    if not selected_accs:
        raise HTTPException(status_code=422, detail="No accomplishments available to tailor")

    from app.services.settings.memory import active_memory_text

    result = await generate_resume_bullets_for_job(
        accomplishments=selected_accs,
        target_company=target_company,
        target_role=target_role,
        job_description=job_description,
        experience_level=payload.experienceLevel,
        tone=TAILORING_TONE_BY_MODE[mode],
        max_pages=payload.maxPages,
        target_ats=payload.targetAtsScore,
        extra_instructions=active_memory_text(db),
    )
    if result is None:
        raise HTTPException(
            status_code=503,
            detail="Resume tailoring is temporarily unavailable. No synthetic fallback content was returned.",
        )
    return {"success": True, "result": build_tailoring_diff(selected_accs, result, mode)}


@router.post("/resume/tailor/approve")
def approve_resume_tailoring_route(payload: ResumeTailorApprovePayload, db: Session = Depends(db_session)) -> dict[str, Any]:
    """Persist an explicitly-approved tailoring result. Never called implicitly by /resume/tailor."""
    record = upsert_entity(
        db,
        "resume_tailoring",
        {
            "id": new_id("tailor_"),
            "mode": payload.mode,
            "jobId": payload.jobId,
            "targetCompany": payload.targetCompany,
            "targetRole": payload.targetRole,
            "bullets": payload.bullets,
            "skillsList": payload.skillsList,
            "approvedAt": now_iso(),
        },
    )
    return {"success": True, "tailoring": record}


@router.get("/resume/tailor/history")
def list_resume_tailoring_route(db: Session = Depends(db_session)) -> dict[str, Any]:
    records = sorted(list_entities(db, "resume_tailoring"), key=lambda r: r.get("approvedAt", ""), reverse=True)
    return {"success": True, "tailorings": records}


@router.get("/profile/resume-profiles")
def list_resume_profiles_route(db: Session = Depends(db_session)) -> dict[str, Any]:
    return {"success": True, "profiles": resume_profiles_service.list_resume_profiles(db)}


@router.post("/profile/resume-profiles")
def create_resume_profile_route(payload: ResumeProfileCreatePayload, db: Session = Depends(db_session)) -> dict[str, Any]:
    profile = resume_profiles_service.create_resume_profile(db, payload.name, payload.resume)
    return {"success": True, "profile": profile}


@router.patch("/profile/resume-profiles/{profile_id}")
def patch_resume_profile_route(profile_id: str, payload: ResumeProfilePatchPayload, db: Session = Depends(db_session)) -> dict[str, Any]:
    patch = payload.model_dump(exclude_none=True)
    updated = resume_profiles_service.update_resume_profile(db, profile_id, patch)
    if not updated:
        raise HTTPException(status_code=404, detail="Resume profile not found")
    return {"success": True, "profile": updated}


@router.delete("/profile/resume-profiles/{profile_id}")
def delete_resume_profile_route(profile_id: str, db: Session = Depends(db_session)) -> dict[str, Any]:
    deleted = resume_profiles_service.delete_resume_profile(db, profile_id)
    if not deleted:
        raise HTTPException(status_code=404, detail="Resume profile not found")
    return {"success": True}


@router.post("/profile/resume-profiles/{profile_id}/set-default")
def set_default_resume_profile_route(profile_id: str, db: Session = Depends(db_session)) -> dict[str, Any]:
    updated = resume_profiles_service.set_default_resume_profile(db, profile_id)
    if not updated:
        raise HTTPException(status_code=404, detail="Resume profile not found")
    return {"success": True, "profile": updated}


@router.get("/resume/ats-score")
def resume_ats_score_route(profileId: str = "", jobId: str = "", db: Session = Depends(db_session)) -> dict[str, Any]:
    if profileId:
        profile = resume_profiles_service.get_resume_profile(db, profileId)
        if not profile:
            raise HTTPException(status_code=404, detail="Resume profile not found")
        resume = profile.get("resume")
    else:
        documents = get_kv(db, "documents") or {}
        resume = documents.get("defaultResume")

    job = None
    if jobId:
        job = get_entity(db, "job", jobId) or get_entity(db, "aa_discovered_job", jobId)

    return {"success": True, **compute_ats_score(resume, job)}


class AnswerQuestionPayload(BaseModel):
    questionId: str
    answer: str


@router.post("/accomplishments/{accomplishment_id}/answer-question")
async def answer_question_route(
    accomplishment_id: str,
    payload: AnswerQuestionPayload,
    db: Session = Depends(db_session)
) -> dict[str, Any]:
    from app.db.store import get_entity
    acc = get_entity(db, "accomplishment", accomplishment_id)
    if not acc:
        raise HTTPException(status_code=404, detail="Accomplishment not found")

    questions = acc.get("missingQuestions", [])
    question_text = ""
    for q in questions:
        if q.get("id") == payload.questionId:
            q["answer"] = payload.answer
            question_text = q.get("question", "")
            break

    description_addon = f"\n\nQuestion: {question_text}\nAnswer: {payload.answer}"

    raw_desc = (
        acc.get("problemContext", {}).get("what", "") + "\n" +
        acc.get("roleDetails", {}).get("responsibility", "")
    )
    new_desc = raw_desc + description_addon

    result = await analyze_accomplishment(new_desc, acc)
    saved = upsert_entity(db, "accomplishment", result)
    return {"success": True, "accomplishment": saved}


@router.get("/benchmarks")
async def get_benchmarks_route() -> dict[str, Any]:
    """Retrieve saved LLM benchmark results."""
    bench_file = Path(__file__).resolve().parent.parent.parent / "data" / "benchmark_results.json"
    if bench_file.exists():
        try:
            return json.loads(bench_file.read_text(encoding="utf-8"))
        except Exception:
            pass
    return {"leaderboard": [], "recommendation": {}, "totalTestCases": 0}


@router.post("/benchmarks/run")
async def run_benchmarks_route() -> dict[str, Any]:
    """Execute full sequential benchmark comparing Ollama local models and Gemini API."""
    from app.services.application_assistant.benchmark_suite import run_full_sequential_benchmark
    gemini_key = os.environ.get("GEMINI_API_KEY", settings.gemini_api_key)
    results = await run_full_sequential_benchmark(
        gemini_api_key=gemini_key,
        output_path="data/benchmark_results.json",
    )
    return results


class TestResolveRequest(BaseModel):
    question: str
    options: list[str] = Field(default_factory=list)
    fieldId: str = "test_field"
    profile: dict[str, Any] = Field(default_factory=dict)
    model: str = "qwen2.5:3b"


@router.post("/benchmarks/test-resolve")
async def test_resolve_field_route(payload: TestResolveRequest) -> dict[str, Any]:
    """Test resolution of a specific question variation with rule resolver and model resolution."""
    import time
    from app.services.application_assistant.benchmark_dataset import BENCHMARK_PROFILE, BENCHMARK_RESUME_TEXT
    from app.services.application_assistant.profile_answer_resolver import resolve_profile_answer
    from app.services.application_assistant.question_classifier import classify_question, QuestionType
    from app.services.application_assistant.cross_field_validator import validate_answers
    from app.services.application_assistant.submission_policy import SubmissionPolicy

    active_profile = payload.profile if payload.profile else BENCHMARK_PROFILE
    start_t = time.perf_counter()

    # 1. Deterministic Rule Classifier & Resolver
    qtype = classify_question(payload.question)
    resolution = resolve_profile_answer(
        field_id=payload.fieldId,
        question_text=payload.question,
        profile=active_profile,
        options=payload.options,
    )

    # 2. Cross-field validation & risk-based policy check
    val_report = validate_answers([resolution], active_profile)
    policy_res = SubmissionPolicy.evaluate([resolution], val_report, profile=active_profile)

    latency_ms = int((time.perf_counter() - start_t) * 1000)

    return {
        "success": True,
        "question": payload.question,
        "questionType": qtype.value,
        "resolutionMethod": resolution.resolution_method,
        "resolvedAnswer": resolution.answer,
        "confidence": resolution.confidence,
        "sourceKey": resolution.profile_key,
        "sourceValue": resolution.source_value,
        "validationStatus": val_report.status,
        "policyDecision": policy_res.decision.value,
        "riskTier": policy_res.risk_tier.value,
        "canAutoSubmit": policy_res.can_auto_submit,
        "blockingIssues": policy_res.blocking_issues,
        "warnings": policy_res.warnings,
        "latencyMs": latency_ms,
    }


# ── Settings: memory, public portfolio, job boards ─────────────────────────────

class MemoryNotePayload(BaseModel):
    text: str


class PortfolioSettingsPayload(BaseModel):
    isPublic: bool | None = None
    slug: str | None = None


@router.get("/settings/memory")
def list_assistant_memory(db: Session = Depends(db_session)) -> dict[str, Any]:
    from app.services.settings.memory import list_memory_notes

    return {"success": True, "notes": list_memory_notes(db)}


@router.post("/settings/memory")
def add_assistant_memory(payload: MemoryNotePayload, db: Session = Depends(db_session)) -> dict[str, Any]:
    from app.services.settings.memory import add_memory_note

    try:
        note = add_memory_note(db, payload.text)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return {"success": True, "note": note}


@router.delete("/settings/memory/{note_id}")
def delete_assistant_memory(note_id: str, db: Session = Depends(db_session)) -> dict[str, Any]:
    from app.services.settings.memory import delete_memory_note

    deleted = delete_memory_note(db, note_id)
    if not deleted:
        raise HTTPException(status_code=404, detail="Memory note not found")
    return {"success": True}


@router.get("/settings/portfolio")
def get_portfolio_settings_route(db: Session = Depends(db_session)) -> dict[str, Any]:
    from app.services.settings.portfolio import get_portfolio_settings

    return {"success": True, "settings": get_portfolio_settings(db)}


@router.patch("/settings/portfolio")
def update_portfolio_settings_route(payload: PortfolioSettingsPayload, db: Session = Depends(db_session)) -> dict[str, Any]:
    from app.services.settings.portfolio import save_portfolio_settings

    try:
        updated = save_portfolio_settings(db, payload.model_dump(exclude_none=True))
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return {"success": True, "settings": updated}


@router.get("/settings/job-boards")
def list_job_boards() -> dict[str, Any]:
    return {
        "success": True,
        "boards": [
            {"id": "indeed", "name": "Indeed", "connected": False},
            {"id": "naukri", "name": "Naukri", "connected": False},
        ],
    }


@router.get("/public/portfolio/{slug}")
def get_public_portfolio(slug: str, db: Session = Depends(db_session)) -> dict[str, Any]:
    from app.services.settings.portfolio import build_public_portfolio

    portfolio = build_public_portfolio(db, slug)
    if portfolio is None:
        raise HTTPException(status_code=404, detail="This portfolio isn't public.")
    return {"success": True, "portfolio": portfolio}



