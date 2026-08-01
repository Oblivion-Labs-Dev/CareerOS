import json
from pathlib import Path
from typing import Any, Generator

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import HTMLResponse, Response
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.config import settings
from app.db.store import (
    EntityStore,
    delete_entity,
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
from app.services.api_dashboard import render_api_dashboard
from app.services.target_company_jobs import (
    filter_jobs,
    format_whatsapp,
    get_snapshot,
    merge_oracle_seed_entries,
    refresh_and_store,
    should_refresh_weekly,
)
from app.services.job_discover import store as job_discover
from app.services.job_discover import relevancy_engine
from app.services.answer_engine import generate_answer, load_custom_answers
from app.services.error_investigation import investigation_for_error_id, investigation_for_open_errors
from app.services.runtime_metrics import metrics_snapshot_with_logs
from app.services.llm import analyze_accomplishment, generate_resume_bullets_for_job
from app.services.extension_packager import build_extension_zip, extension_info
from app.services.gmail_imap import GmailImapClient
from app.services.gmail_sender import SendEmailPayload, build_gmail_sender
from app.services.log_store import append_client_log, clear_client_logs, read_client_logs
from app.services.resume_parser import parse_resume_into_profile

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


@router.post("/jobs/extract")
def extract_job(payload: JobExtractPayload) -> dict[str, Any]:
    job = {
        "id": new_id("job_"),
        "companyName": payload.company or "Unknown company",
        "title": payload.title or "Unknown role",
        "location": payload.location or "",
        "description": payload.description or "",
        "url": payload.url,
        "platform": payload.platform or "",
        "extractedAt": now_iso(),
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
    hours: int = Field(default=168, ge=1, le=720)
    roles: str = ""
    mode: str = "ats"


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
    freshness: str = Query(default="all"),
    sponsorship: str = Query(default="all"),
    sort: str = Query(default="relevancy"),
    page: int = Query(default=1, ge=1),
    per_page: int = Query(default=30, ge=1, le=100),
) -> dict[str, Any]:
    snapshot = job_discover.get_snapshot(db)
    freshness_filter = freshness if freshness in {"12", "24", "48", "72", "168", "336", "720", "all"} else "all"
    sort_option = sort if sort in {"relevancy", "date", "company"} else "relevancy"
    from app.services.application_assistant.scraper_import import get_synced_scraper_job_ids

    synced_ids = get_synced_scraper_job_ids(db)
    available_jobs = [job for job in (snapshot.get("jobs") or []) if job.get("id") not in synced_ids]
    jobs, total = job_discover.filter_jobs(
        available_jobs,
        q=q,
        company=company,
        location=location,
        role=role,
        freshness=freshness_filter,  # type: ignore[arg-type]
        sponsorship=sponsorship,
        sort=sort_option,  # type: ignore[arg-type]
        page=page,
        per_page=per_page,
    )
    total_pages = (total + per_page - 1) // per_page if per_page else 0
    return {
        "success": True,
        "jobs": jobs,
        "total": total,
        "indexedTotal": snapshot.get("totalJobs", 0),
        "assistantTotal": len(synced_ids),
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
    available_jobs = [job for job in (snapshot.get("jobs") or []) if job.get("id") not in synced_ids]
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
    raw_campaigns = json.loads(path.read_text(encoding="utf-8"))
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

