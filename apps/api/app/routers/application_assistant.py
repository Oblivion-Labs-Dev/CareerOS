"""Application Assistant API routes."""

from __future__ import annotations

import json
from typing import Any

from fastapi import APIRouter, Body, Depends, HTTPException, Query, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.db.store import get_kv, now_iso, session_scope
from app.services.application_assistant.browser_runner import close_session
from app.services.application_assistant.job_discovery import (
    cancel_discovery,
    filter_jobs,
    run_discovery,
)
from app.services.application_assistant.llm_client import create_llm_client
from app.services.application_assistant.persistence import (
    create_application_draft,
    create_discovery_run,
    delete_answer,
    get_active_browser_run_for_app,
    get_application_draft,
    get_discovered_job,
    get_discovery_run,
    get_job_match,
    get_settings,
    list_answer_library,
    list_application_drafts,
    list_discovered_jobs,
    list_discovery_runs,
    save_application_fields,
    save_job_match,
    save_settings,
    update_application_draft,
    update_browser_run,
    upsert_answer,
    upsert_discovered_job,
)
from app.services.application_assistant.providers import list_providers
from app.services.application_assistant.url_validation import validate_url
from app.services.application_assistant.worker import (
    is_app_locked,
    run_in_background,
    task_status,
)

router = APIRouter(prefix="/application-assistant", tags=["application-assistant"])


def db_session():
    with session_scope() as db:
        yield db


# ── Request Models ────────────────────────────────────────────────────────────

class DiscoveryStartPayload(BaseModel):
    careersUrl: str
    resumeId: str = ""
    locationPreferences: list[str] = Field(default_factory=list)
    workplacePreference: str = ""
    minMatchScore: float = 0
    includeKeywords: list[str] = Field(default_factory=list)
    excludeKeywords: list[str] = Field(default_factory=list)


class ApplicationCreatePayload(BaseModel):
    jobId: str
    resumeId: str = ""


class QuickAddApplicationPayload(BaseModel):
    url: str
    title: str | None = None
    company: str | None = None
    location: str | None = None
    description: str | None = None
    resumeId: str = ""


class FieldEditPayload(BaseModel):
    fieldId: str
    value: Any
    approved: bool = False


class FieldAnswerSubmission(BaseModel):
    fieldId: str = ""
    normalizedKey: str = ""
    value: Any = None
    profileKey: str = ""


class FieldAnswersPayload(BaseModel):
    answers: list[FieldAnswerSubmission] = Field(default_factory=list)


class UnifiedAnswerTarget(BaseModel):
    appId: str
    fieldId: str
    normalizedKey: str = ""
    label: str = ""
    companyName: str = ""


class UnifiedFieldAnswerSubmission(BaseModel):
    canonicalId: str
    value: Any = None
    profileKey: str = ""
    normalizedKey: str = ""
    targets: list[UnifiedAnswerTarget] = Field(default_factory=list)


class UnifiedFieldAnswersPayload(BaseModel):
    answers: list[UnifiedFieldAnswerSubmission] = Field(default_factory=list)


class AnswerPayload(BaseModel):
    normalizedKey: str
    questionVariants: list[str] = Field(default_factory=list)
    answerType: str = "short_text"
    value: Any = None
    sensitivityCategory: str = "none"
    verificationStatus: str = "verified"
    applicableCompanies: list[str] = Field(default_factory=list)
    applicableProviders: list[str] = Field(default_factory=list)


class SettingsPayload(BaseModel):
    enabled: bool | None = None
    tailoringMode: str | None = None
    allowInferredAnswers: bool | None = None
    llm: dict[str, Any] | None = None
    browser: dict[str, Any] | None = None
    fieldMapping: dict[str, Any] | None = None
    domainAllowlist: list[str] | None = None


class QwenChatPayload(BaseModel):
    message: str
    history: list[dict[str, str]] = Field(default_factory=list)
    context: dict[str, Any] = Field(default_factory=dict)


class QwenAgentPreparePayload(BaseModel):
    jobId: str = ""
    applicationId: str = ""


class OpenReviewPayload(BaseModel):
    force: bool = False


class ScraperImportPayload(BaseModel):
    scraperJobId: str


class GenerateAnswerPayload(BaseModel):
    question: str
    company: str = ""
    role: str = ""
    jobDescription: str = ""


# ── Settings ──────────────────────────────────────────────────────────────────

@router.get("/settings")
def get_aa_settings(db: Session = Depends(db_session)) -> dict[str, Any]:
    return {"success": True, "settings": get_settings(db)}


@router.post("/settings")
def update_aa_settings(payload: SettingsPayload, db: Session = Depends(db_session)) -> dict[str, Any]:
    patch = payload.model_dump(exclude_none=True)
    return {"success": True, "settings": save_settings(db, patch)}


@router.get("/providers")
def get_providers() -> dict[str, Any]:
    return {"success": True, "providers": list_providers()}


# ── Discovery ─────────────────────────────────────────────────────────────────

@router.post("/discovery/start")
async def start_discovery(payload: DiscoveryStartPayload, db: Session = Depends(db_session)) -> dict[str, Any]:
    valid, reason = validate_url(payload.careersUrl)
    if not valid:
        raise HTTPException(status_code=400, detail=reason)

    run = create_discovery_run(db, payload.model_dump())
    await run_in_background(run["id"], run_discovery(run["id"]))
    return {"success": True, "run": run}


@router.get("/discovery/{run_id}")
def get_discovery_status(run_id: str, db: Session = Depends(db_session)) -> dict[str, Any]:
    run = get_discovery_run(db, run_id)
    if not run:
        raise HTTPException(status_code=404, detail="Discovery run not found")
    return {"success": True, "run": run, "taskStatus": task_status(run_id)}


@router.post("/discovery/{run_id}/cancel")
def cancel_discovery_run(run_id: str) -> dict[str, Any]:
    cancelled = cancel_discovery(run_id)
    return {"success": cancelled}


@router.get("/discovery")
def list_runs(db: Session = Depends(db_session)) -> dict[str, Any]:
    return {"success": True, "runs": list_discovery_runs(db)}


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
def dashboard_stats(db: Session = Depends(db_session)) -> dict[str, Any]:
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


# ── Applications ──────────────────────────────────────────────────────────────

@router.get("/applications")
def list_applications(
    db: Session = Depends(db_session),
    status: str | None = Query(default=None),
) -> dict[str, Any]:
    from app.services.application_assistant.browser_replay import summarize_application_list_item
    from app.services.application_assistant.persistence import index_active_browser_runs
    from app.services.application_assistant.agent import _get_agent_runs, reconcile_stale_prep_state

    drafts = list_application_drafts(db, status=status, cleanup_duplicates=False)
    agent_runs = _get_agent_runs(db)
    active_browser_runs = index_active_browser_runs(db)
    enriched: list[dict[str, Any]] = []
    for draft in drafts:
        app_id = str(draft.get("id") or "")
        draft = reconcile_stale_prep_state(db, draft, active_run=active_browser_runs.get(app_id))
        job = get_discovered_job(db, draft.get("jobId", ""))
        if job:
            draft = {
                **draft,
                "jobLocation": job.get("location", ""),
                "workplaceType": job.get("workplaceType", ""),
            }
        agent_run = agent_runs.get(app_id)
        if agent_run and agent_run.get("status") == "failed":
            draft = {
                **draft,
                "lastPrepFailed": True,
                "lastPrepError": agent_run.get("error") or agent_run.get("stoppedReason") or "",
                "lastPrepAnalysis": agent_run.get("analysis") or "",
            }
        enriched.append(summarize_application_list_item(draft))
    return {"success": True, "applications": enriched}


@router.get("/applications/autofill-state")
def list_autofill_state(
    db: Session = Depends(db_session),
) -> dict[str, Any]:
    """Per-job saved Playwright autofill state (applicationId + jobId + hasSavedAutofillState)."""
    from app.services.application_assistant.browser_replay import list_autofill_states
    from app.services.application_assistant.agent import reconcile_stale_prep_state

    drafts = list_application_drafts(db)
    reconciled = [reconcile_stale_prep_state(db, d) for d in drafts]
    return {"success": True, "states": list_autofill_states(reconciled)}


@router.post("/applications")
def create_application(payload: ApplicationCreatePayload, db: Session = Depends(db_session)) -> dict[str, Any]:
    job = get_discovered_job(db, payload.jobId)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")

    match = get_job_match(db, payload.jobId)
    draft = create_application_draft(db, {
        "jobId": payload.jobId,
        "jobUrl": job.get("applicationUrl", job.get("listingUrl", "")),
        "companyName": job.get("company", ""),
        "roleTitle": job.get("title", ""),
        "provider": job.get("sourceProvider", "unknown"),
        "resumeId": payload.resumeId,
        "matchScore": match.get("overallScore", 0) if match else 0,
    })
    return {"success": True, "application": draft}


@router.post("/applications/quick-add")
def quick_add_application(payload: QuickAddApplicationPayload, db: Session = Depends(db_session)) -> dict[str, Any]:
    """Paste any job posting URL (+ optional JD text) straight into the pipeline.

    Mirrors the scraper-import path (`upsert_discovered_job` -> `create_application_draft`)
    but for a single link the crawler never found, instead of a discovery run.
    """
    from app.services.job_discover.url_import import autoextract_job_from_url

    valid, reason = validate_url(payload.url)
    if not valid:
        raise HTTPException(status_code=400, detail=reason)

    auto: dict[str, Any] | None = None
    if not payload.description:
        auto = autoextract_job_from_url(payload.url)

    title = payload.title or (auto or {}).get("title") or ""
    company = payload.company or (auto or {}).get("company") or ""
    location = payload.location or (auto or {}).get("location") or ""
    description = payload.description or (auto or {}).get("description") or ""
    if not title or not company:
        raise HTTPException(
            status_code=422,
            detail="Could not read a title/company from that link — add them manually.",
        )

    job = upsert_discovered_job(db, {
        "title": title,
        "company": company,
        "location": location,
        "description": description,
        "applicationUrl": payload.url,
        "listingUrl": payload.url,
        "sourceProvider": "manual_link",
        "active": True,
    })

    draft = create_application_draft(db, {
        "jobId": job["id"],
        "jobUrl": payload.url,
        "companyName": company,
        "roleTitle": title,
        "provider": "manual_link",
        "resumeId": payload.resumeId,
        "matchScore": 0,
    })
    return {"success": True, "job": job, "application": draft, "autoExtracted": bool(auto)}


@router.get("/applications/{app_id}")
def get_application(app_id: str, db: Session = Depends(db_session)) -> dict[str, Any]:
    from app.services.application_assistant.browser_replay import enrich_draft_replay_state, reconcile_stale_browser_run

    draft = get_application_draft(db, app_id)
    if not draft:
        raise HTTPException(status_code=404, detail="Application not found")
    draft = reconcile_stale_browser_run(db, draft)
    draft = enrich_draft_replay_state(draft)
    browser_run = get_active_browser_run_for_app(db, app_id)
    return {
        "success": True,
        "application": draft,
        "browserRun": browser_run,
        "locked": is_app_locked(app_id),
    }


@router.post("/applications/{app_id}/prepare")
async def start_preparation(app_id: str, db: Session = Depends(db_session)) -> dict[str, Any]:
    from app.services.application_assistant.agent import execute_application_prepare

    prep = await execute_application_prepare(app_id, allow_retry=True)
    if prep.get("error") == "Application not found":
        raise HTTPException(status_code=404, detail="Application not found")
    if prep.get("error") == "Application is already being prepared":
        raise HTTPException(status_code=409, detail="Application is already being prepared")
    if prep.get("error") == "Browser run already active":
        raise HTTPException(status_code=409, detail="Browser run already active")
    if prep.get("error"):
        raise HTTPException(status_code=400, detail=prep["error"])
    return prep


@router.post("/applications/{app_id}/resume")
async def resume_application(app_id: str, db: Session = Depends(db_session)) -> dict[str, Any]:
    """Resume a previously started application."""
    return await start_preparation(app_id, db)


@router.post("/applications/{app_id}/fields/{field_id}")
def edit_field(app_id: str, field_id: str, payload: FieldEditPayload, db: Session = Depends(db_session)) -> dict[str, Any]:
    draft = get_application_draft(db, app_id)
    if not draft:
        raise HTTPException(status_code=404, detail="Application not found")

    fields = draft.get("fields", [])
    updated = False
    for field in fields:
        if field.get("id") == field_id or field.get("normalizedKey") == field_id:
            field["proposedValue"] = payload.value
            if payload.approved:
                field["classification"] = "verified"
            field["updatedAt"] = __import__("app.db.store", fromlist=["now_iso"]).now_iso()
            updated = True
            break

    if not updated:
        raise HTTPException(status_code=404, detail="Field not found")

    saved = save_application_fields(db, app_id, fields)
    return {"success": True, "application": saved}


@router.post("/applications/{app_id}/approve/{field_id}")
def approve_field(app_id: str, field_id: str, db: Session = Depends(db_session)) -> dict[str, Any]:
    return edit_field(app_id, field_id, FieldEditPayload(fieldId=field_id, value=None, approved=True), db)


@router.get("/applications/{app_id}/readiness")
def get_application_readiness(app_id: str, db: Session = Depends(db_session)) -> dict[str, Any]:
    """Fast check: are all profile questions answered so the browser can open?"""
    from app.services.application_assistant.field_answers import sync_application_readiness

    draft = get_application_draft(db, app_id)
    if not draft:
        raise HTTPException(status_code=404, detail="Application not found")

    readiness = sync_application_readiness(db, app_id, persist=True)
    return {"success": True, **readiness}


@router.get("/applications/{app_id}/pending-fields")
async def get_pending_fields(
    app_id: str,
    use_ai: bool = Query(False, description="When true, run Qwen semantic matching and question enrichment"),
    db: Session = Depends(db_session),
) -> dict[str, Any]:
    """List fields that need user answers, with optional Qwen storage hints."""
    from app.db.store import get_kv
    from app.services.application_assistant.field_answers import (
        _fallback_enrich_field,
        enrich_pending_with_qwen,
        filter_wizard_pending,
        load_persisted_wizard_pending,
        persist_wizard_analysis,
        split_pending_fields,
        sync_application_readiness,
        sync_application_readiness_async,
    )

    draft = get_application_draft(db, app_id)
    if not draft:
        raise HTTPException(status_code=404, detail="Application not found")

    company = str(draft.get("companyName") or "")
    analyze_ctx = {"applicationId": app_id, "companyName": company}

    if use_ai:
        from app.services.application_assistant.field_answers import _log_analyze

        _log_analyze(
            f"Starting Qwen analysis for {company} — {draft.get('roleTitle', '')}",
            event_type="analyze_start",
            application_id=app_id,
            company_name=company,
            metadata={"missingCount": draft.get("missingCount", 0)},
        )
        try:
            readiness = await sync_application_readiness_async(db, app_id, persist=True)
            pending = readiness.get("pending") or []
            if pending:
                profile = get_kv(db, "profile") or {}
                settings = get_settings(db)
                enriched = await enrich_pending_with_qwen(
                    pending, profile, settings, analyze_context=analyze_ctx,
                )
                wizard_pending = filter_wizard_pending(enriched)
                split = split_pending_fields(wizard_pending)
            else:
                split = split_pending_fields(pending)
                wizard_pending = []
            persist_wizard_analysis(db, app_id, split, ai_analyzed=True)
            _log_analyze(
                f"Analysis complete — {len(wizard_pending)} wizard question(s) for {company}",
                event_type="analyze_complete",
                application_id=app_id,
                company_name=company,
                metadata={"questionCount": len(wizard_pending)},
            )
        except Exception as exc:
            _log_analyze(
                f"Analysis failed for {company}: {exc}",
                event_type="analyze_failed",
                application_id=app_id,
                company_name=company,
                success=False,
                error=str(exc),
            )
            raise
    else:
        cache = draft.get("wizardPendingCache")
        if draft.get("aiAnalyzed") and isinstance(cache, dict) and cache.get("pending"):
            profile_pending = filter_wizard_pending(list(cache.get("profilePending") or []))
            application_pending = filter_wizard_pending(list(cache.get("applicationPending") or []))
            wizard_pending = filter_wizard_pending(list(cache.get("pending") or []))
            if not wizard_pending:
                wizard_pending = profile_pending + application_pending
            split = {
                "pending": wizard_pending,
                "profilePending": profile_pending,
                "applicationPending": application_pending,
                "profileKeysMissing": list(cache.get("profileKeysMissing") or []),
            }
        else:
            readiness = sync_application_readiness(db, app_id, persist=True)
            cached = load_persisted_wizard_pending(db, app_id, readiness)
            if cached is not None:
                split = cached
                wizard_pending = split["pending"]
            else:
                pending = readiness.get("pending") or []
                enriched = [_fallback_enrich_field(f) for f in pending]
                wizard_pending = filter_wizard_pending(enriched)
                split = split_pending_fields(wizard_pending)
    fresh = get_application_draft(db, app_id) or draft
    return {
        "success": True,
        "pending": split["pending"],
        "profilePending": split["profilePending"],
        "applicationPending": split["applicationPending"],
        "profileKeysMissing": split["profileKeysMissing"],
        "count": len(split["pending"]),
        "readyForBrowser": len(wizard_pending) == 0,
        "aiAnalyzed": bool(fresh.get("aiAnalyzed")),
    }


@router.get("/pending-fields/aggregate")
async def get_aggregate_pending_fields(
    app_ids: str = Query("", description="Comma-separated application IDs; empty = all with pending questions"),
    use_ai: bool = Query(False, description="When true, interpret and deduplicate with Qwen"),
    db: Session = Depends(db_session),
) -> dict[str, Any]:
    """Collect pending questions across applications; AI normalization is opt-in."""
    from app.services.application_assistant.field_answers import aggregate_pending_across_apps

    ids = [part.strip() for part in app_ids.split(",") if part.strip()] or None
    result = await aggregate_pending_across_apps(db, ids, use_ai=use_ai)
    return {"success": True, **result}


@router.post("/field-answers/batch")
async def submit_unified_field_answers(
    payload: UnifiedFieldAnswersPayload,
    db: Session = Depends(db_session),
) -> dict[str, Any]:
    """Save normalized answers once and apply them to every matching application field."""
    from app.services.application_assistant.field_answers import save_unified_field_answers
    from app.services.application_assistant.agent import schedule_autonomous_prepare

    if not payload.answers:
        raise HTTPException(status_code=400, detail="No answers provided")

    batch_result = await save_unified_field_answers(
        db,
        [a.model_dump(exclude_none=True) for a in payload.answers],
    )
    db.commit()
    reprepped = list(batch_result.get("readyApplicationIds") or [])
    for app_id in reprepped:
        schedule_autonomous_prepare(app_id)

    return {
        "success": True,
        **batch_result,
        "repreppedApplicationIds": reprepped,
    }


@router.post("/applications/{app_id}/field-answers")
async def submit_field_answers(
    app_id: str,
    payload: FieldAnswersPayload,
    db: Session = Depends(db_session),
) -> dict[str, Any]:
    """Save user-provided answers to profile + answer library and update the draft."""
    from app.services.application_assistant.field_answers import save_field_answers
    from app.services.application_assistant.agent import schedule_autonomous_prepare

    if not payload.answers:
        raise HTTPException(status_code=400, detail="No answers provided")

    updated = save_field_answers(
        db,
        app_id,
        [a.model_dump(exclude_none=True) for a in payload.answers],
    )
    if not updated:
        raise HTTPException(status_code=404, detail="Application not found")

    saved_count = int(updated.get("savedCount") or 0)
    if saved_count == 0:
        raise HTTPException(
            status_code=400,
            detail="No answers were saved — field IDs may not match the application draft. Try Analyze with Qwen again.",
        )

    db.commit()

    fresh = get_application_draft(db, app_id) or updated
    ready_for_browser = bool(fresh.get("readyForBrowser"))
    pending_count = int(fresh.get("pendingFieldCount") or 0)

    reprep_started = ready_for_browser
    if ready_for_browser:
        schedule_autonomous_prepare(app_id)

    return {
        "success": True,
        "application": fresh,
        "savedCount": saved_count,
        "readyForBrowser": ready_for_browser,
        "pendingCount": pending_count,
        "aiAnalyzed": bool(fresh.get("aiAnalyzed")),
        "reprepStarted": reprep_started,
    }


@router.post("/applications/{app_id}/mark-submitted")
def mark_submitted(app_id: str, db: Session = Depends(db_session)) -> dict[str, Any]:
    """Toggle submitted status — marks submitted or restores previous status."""
    draft = get_application_draft(db, app_id)
    if not draft:
        raise HTTPException(status_code=404, detail="Application not found")
    if draft.get("status") == "submitted_manually":
        restore = draft.get("previousStatus") or "needs_review"
        updated = update_application_draft(
            db,
            app_id,
            {
                "status": restore,
                "previousStatus": None,
                "submittedAt": None,
                "submissionSource": None,
                "submissionTrigger": None,
                "submissionUrl": None,
            },
        )
        return {"success": True, "application": updated, "submitted": False}
    updated = update_application_draft(
        db,
        app_id,
        {
            "status": "submitted_manually",
            "previousStatus": draft.get("status", "needs_review"),
            "submittedAt": now_iso(),
            "submissionSource": "manual",
        },
    )
    return {"success": True, "application": updated, "submitted": True}


@router.post("/applications/{app_id}/record-submission")
def record_submission(
    app_id: str,
    db: Session = Depends(db_session),
    trigger: str = Query(default="manual"),
    url: str = Query(default=""),
) -> dict[str, Any]:
    """Record submission detected from the review browser or an external hook."""
    from app.services.application_assistant.submission_watcher import record_application_submission

    draft = get_application_draft(db, app_id)
    if not draft:
        raise HTTPException(status_code=404, detail="Application not found")
    recorded = record_application_submission(app_id, trigger, url or draft.get("jobUrl", ""))
    updated = get_application_draft(db, app_id)
    return {"success": recorded, "application": updated, "submitted": True}


@router.post("/applications/{app_id}/unmark-submitted")
def unmark_submitted(app_id: str, db: Session = Depends(db_session)) -> dict[str, Any]:
    """Explicit unmark — same as toggling off submitted_manually."""
    draft = get_application_draft(db, app_id)
    if not draft:
        raise HTTPException(status_code=404, detail="Application not found")
    if draft.get("status") != "submitted_manually":
        return {"success": True, "application": draft, "submitted": False}
    restore = draft.get("previousStatus") or "needs_review"
    updated = update_application_draft(db, app_id, {"status": restore, "previousStatus": None})
    return {"success": True, "application": updated, "submitted": False}


@router.post("/applications/{app_id}/archive")
def archive_application(app_id: str, db: Session = Depends(db_session)) -> dict[str, Any]:
    draft = get_application_draft(db, app_id)
    if not draft:
        raise HTTPException(status_code=404, detail="Application not found")
    prev = draft.get("status") if draft.get("status") != "archived" else "ready_to_prepare"
    updated = update_application_draft(db, app_id, {"status": "archived", "previousStatus": prev})
    return {"success": True, "application": updated}


@router.post("/applications/{app_id}/unarchive")
def unarchive_application(app_id: str, db: Session = Depends(db_session)) -> dict[str, Any]:
    draft = get_application_draft(db, app_id)
    if not draft:
        raise HTTPException(status_code=404, detail="Application not found")
    restore = draft.get("previousStatus") or "ready_to_prepare"
    updated = update_application_draft(db, app_id, {"status": restore, "previousStatus": None})
    return {"success": True, "application": updated}


@router.post("/applications/{app_id}/stop-browser")
async def stop_browser(app_id: str, db: Session = Depends(db_session)) -> dict[str, Any]:
    from app.services.application_assistant.browser_runner import cleanup_stale_session

    await close_session(app_id)
    await cleanup_stale_session(app_id, db)
    active_run = get_active_browser_run_for_app(db, app_id)
    if active_run:
        update_browser_run(db, active_run["id"], {"status": "stopped"})
    draft = get_application_draft(db, app_id)
    if draft and draft.get("status") == "in_progress":
        update_application_draft(db, app_id, {"status": "needs_review"})
    return {"success": True, "browserOpen": False, "status": "ready"}


@router.get("/applications/{app_id}/submission-confirmed")
def check_submission_confirmed_route(app_id: str, db: Session = Depends(db_session)) -> dict[str, Any]:
    """Real success check: has a confirmation email actually arrived for this
    application's tracking address? A submit that returns 'ok' but never gets
    a real ATS confirmation shouldn't be reported as a successful application."""
    from app.services.tracker.confirmation import check_submission_confirmed

    return check_submission_confirmed(db, app_id)


@router.get("/applications/{app_id}/review-status")
def review_session_status(app_id: str, db: Session = Depends(db_session)) -> dict[str, Any]:
    from app.services.application_assistant.agent import get_review_session_status

    status = get_review_session_status(db, app_id)
    if status.get("status") == "not_found":
        raise HTTPException(status_code=404, detail="Application not found")
    return {"success": True, **status}


@router.post("/applications/{app_id}/open-review")
async def open_application_review(
    app_id: str,
    payload: OpenReviewPayload = Body(default_factory=OpenReviewPayload),
    db: Session = Depends(db_session),
) -> dict[str, Any]:
    """Open employer application page in visible browser and fill from saved draft."""
    from app.services.application_assistant.agent import execute_application_open_review
    from app.services.application_assistant.persistence import (
        get_application_draft,
        create_application_draft,
        get_autopilot_job,
        list_autopilot_jobs,
    )
    from app.db.store import now_iso

    # Ensure draft exists; if app_id belongs to an autopilot job, auto-seed draft with saved fields & answers
    draft = get_application_draft(db, app_id)
    if not draft:
        # Check if app_id or raw ID matches an autopilot job
        target_job = get_autopilot_job(db, app_id)
        if not target_job:
            # Check by canonical job ID suffix
            for j in list_autopilot_jobs(db):
                cand_id = f"app_{str(j.get('jobId') or j.get('id') or '').replace('-', '_')}"[:120]
                if cand_id == app_id or j.get("id") == app_id or j.get("jobId") == app_id:
                    target_job = j
                    break

        if target_job:
            job_url = target_job.get("applicationUrl") or target_job.get("listingUrl") or ""
            answers = target_job.get("answers") or {}
            fields_list = []
            for k, v in answers.items():
                fields_list.append({
                    "fieldId": f"fld_{k.lower().replace(' ', '_')}",
                    "label": k,
                    "normalizedKey": k.lower().strip(),
                    "classification": "verified",
                    "proposedValue": v,
                    "userEdited": True,
                    "confidence": 1.0,
                    "requiresUserReview": False,
                })

            draft = create_application_draft(db, {
                "id": app_id,
                "jobId": target_job.get("jobId") or target_job.get("id"),
                "companyName": target_job.get("company", "Unknown company"),
                "roleTitle": target_job.get("title", "Unknown role"),
                "jobUrl": job_url,
                "status": "needs_review",
                "readyForBrowser": True,
                "pendingFieldCount": 0,
                "fields": fields_list,
                "verifiedCount": len(fields_list),
                "reviewCount": 0,
                "missingCount": 0,
                "matchScore": target_job.get("matchScore"),
                "aiAnalyzed": True,
                "updatedAt": now_iso(),
            })

    result = await execute_application_open_review(db, app_id, force_reopen=payload.force, background=True)
    if result.get("error") == "Application not found":
        raise HTTPException(status_code=404, detail="Application not found")
    if result.get("status") == "profile_incomplete":
        raise HTTPException(status_code=409, detail=result["error"])
    if result.get("error"):
        raise HTTPException(status_code=409, detail=result["error"])
    return {"success": True, **result}


@router.get("/applications/{app_id}/review")
def get_review(app_id: str, db: Session = Depends(db_session)) -> dict[str, Any]:
    draft = get_application_draft(db, app_id)
    if not draft:
        raise HTTPException(status_code=404, detail="Application not found")

    fields = draft.get("fields", [])
    grouped = {
        "verified": [f for f in fields if f.get("classification") == "verified"],
        "needsReview": [f for f in fields if f.get("classification") == "inferred"],
        "missing": [f for f in fields if f.get("classification") == "unknown"],
        "conflicting": [f for f in fields if f.get("classification") == "conflict"],
        "sensitive": [f for f in fields if f.get("sensitivityCategory", "none") != "none"],
        "manualOnly": [f for f in fields if f.get("classification") == "manual_only"],
    }

    return {
        "success": True,
        "application": draft,
        "grouped": grouped,
        "summary": {
            "verified": draft.get("verifiedCount", 0),
            "needsReview": draft.get("reviewCount", 0),
            "missing": draft.get("missingCount", 0),
            "conflicting": draft.get("conflictingCount", 0),
            "progress": draft.get("progress", 0),
        },
        "prepLog": draft.get("prepLog"),
        "skipped": draft.get("skipped", []),
        "errors": draft.get("errors", []),
        "stoppedReason": draft.get("stoppedReason", ""),
    }


# ── Answer Library ────────────────────────────────────────────────────────────

@router.get("/answers")
def list_answers(db: Session = Depends(db_session)) -> dict[str, Any]:
    return {"success": True, "answers": list_answer_library(db)}


@router.post("/answers")
def create_answer(payload: AnswerPayload, db: Session = Depends(db_session)) -> dict[str, Any]:
    answer = upsert_answer(db, payload.model_dump())
    return {"success": True, "answer": answer}


@router.delete("/answers/{answer_id}")
def remove_answer(answer_id: str, db: Session = Depends(db_session)) -> dict[str, Any]:
    deleted = delete_answer(db, answer_id)
    return {"success": deleted}


# ── LLM ───────────────────────────────────────────────────────────────────────

@router.post("/llm/test")
async def test_llm(db: Session = Depends(db_session)) -> dict[str, Any]:
    from app.services.application_assistant.qwen_activity import update_connection_status

    settings = get_settings(db)
    client = create_llm_client(settings)
    result = await client.test_connection()
    model = settings.get("llm", {}).get("model", "")
    if result.get("models") and not model:
        model = result["models"][0] if result["models"] else ""
    update_connection_status(db, connected=result.get("success", False), model=model)
    return {"success": result.get("success", False), **result}


# ── Qwen agent (metrics, logs, chat) ──────────────────────────────────────────

QWEN_SYSTEM_PROMPT = """You are Qwen, the autonomous application assistant inside CareerOS.
You run application preparation in a visible browser and log every step.
The user watches your activity log — they do not drive prep manually.
When asked what went wrong, use the prep context provided and explain clearly.
If the issue is a UI or backend bug, name the layer and suggest a specific fix.
Never claim to submit applications or bypass submission guards."""


@router.post("/qwen/agent/prepare")
async def qwen_agent_prepare(payload: QwenAgentPreparePayload, db: Session = Depends(db_session)) -> dict[str, Any]:
    from app.services.application_assistant.agent import (
        start_autonomous_prepare,
        start_autonomous_prepare_for_job,
    )

    if payload.applicationId:
        result = await start_autonomous_prepare(payload.applicationId)
    elif payload.jobId:
        result = await start_autonomous_prepare_for_job(payload.jobId)
    else:
        raise HTTPException(status_code=400, detail="Provide jobId or applicationId")

    if not result.get("success"):
        raise HTTPException(status_code=409, detail=result.get("error", "Agent prep failed"))
    return result


@router.get("/qwen/agent/prep-queue")
def qwen_agent_prep_queue() -> dict[str, Any]:
    from app.services.application_assistant.worker import prep_queue_status

    return {"success": True, **prep_queue_status()}


@router.get("/qwen/agent/status/{app_id}")
def qwen_agent_status(app_id: str, db: Session = Depends(db_session)) -> dict[str, Any]:
    from app.services.application_assistant.agent import get_agent_run

    run = get_agent_run(db, app_id)
    draft = get_application_draft(db, app_id)
    return {"success": True, "run": run, "application": draft}


@router.get("/qwen/status")
async def qwen_status(db: Session = Depends(db_session)) -> dict[str, Any]:
    from app.services.application_assistant.qwen_activity import update_connection_status

    settings = get_settings(db)
    llm = settings.get("llm", {})
    client = create_llm_client(settings)
    ping = await client.test_connection()
    model = llm.get("model") or (ping.get("models", [""])[0] if ping.get("models") else "")
    metrics = update_connection_status(db, connected=ping.get("success", False), model=model)
    return {
        "success": True,
        "connected": ping.get("success", False),
        "model": model,
        "baseUrl": llm.get("baseUrl", ""),
        "provider": llm.get("provider", "ollama"),
        "models": ping.get("models", []),
        "error": ping.get("error"),
        "metrics": metrics,
    }


@router.get("/qwen/metrics")
def qwen_metrics(db: Session = Depends(db_session)) -> dict[str, Any]:
    from app.services.application_assistant.qwen_activity import get_metrics

    settings = get_settings(db)
    return {
        "success": True,
        "metrics": get_metrics(db),
        "llm": settings.get("llm", {}),
    }


@router.get("/qwen/logs")
def qwen_logs(
    db: Session = Depends(db_session),
    limit: int = Query(default=50, ge=1, le=200),
) -> dict[str, Any]:
    from app.services.application_assistant.qwen_activity import (
        get_active_analyze_from_logs,
        get_active_prep_from_logs,
        get_logs,
    )

    return {
        "success": True,
        "logs": get_logs(db, limit=limit),
        "activePrep": get_active_prep_from_logs(db),
        "activeAnalyze": get_active_analyze_from_logs(db),
    }


@router.get("/qwen/live")
def qwen_live_status(db: Session = Depends(db_session)) -> dict[str, Any]:
    from app.services.application_assistant.qwen_activity import (
        get_active_analyze_from_logs,
        get_active_prep_from_logs,
        get_logs,
        get_metrics,
    )
    from app.services.application_assistant.agent import get_agent_run

    active_prep = get_active_prep_from_logs(db)
    active_analyze = get_active_analyze_from_logs(db)
    latest = get_logs(db, limit=20)
    agent_run = None
    if active_prep and active_prep.get("applicationId"):
        agent_run = get_agent_run(db, str(active_prep["applicationId"]))
    return {
        "success": True,
        "activePrep": active_prep,
        "activeAnalyze": active_analyze,
        "agentRun": agent_run,
        "logs": latest,
        "metrics": get_metrics(db),
    }


@router.post("/qwen/chat")
async def qwen_chat(payload: QwenChatPayload, db: Session = Depends(db_session)) -> dict[str, Any]:
    from app.services.application_assistant.qwen_activity import ActivityTimer, append_log

    settings = get_settings(db)
    client = create_llm_client(settings)
    if not client.enabled:
        raise HTTPException(status_code=503, detail="Qwen is not configured. Set llm.model in settings.")

    messages = [
        *[{"role": m["role"], "content": m["content"]} for m in payload.history if m.get("role") and m.get("content")],
        {"role": "user", "content": payload.message},
    ]

    context_note = ""
    from app.services.application_assistant.agent import build_chat_context

    context_note = build_chat_context(db, payload.context)
    if context_note:
        context_note = "\n\n" + context_note

    system = QWEN_SYSTEM_PROMPT + context_note

    with ActivityTimer() as timer:
        result = await client.chat(messages, system=system)

    append_log(
        db,
        event_type="chat",
        model=client.model,
        success=result.get("success", False),
        latency_ms=timer.elapsed_ms,
        summary=f"Chat: {payload.message[:120]}",
        error=result.get("error", ""),
        metadata={
            "usage": result.get("usage", {}),
            "responsePreview": str(result.get("data", ""))[:120],
        },
    )

    if not result.get("success"):
        raise HTTPException(status_code=502, detail=result.get("error", "Qwen request failed"))

    return {
        "success": True,
        "reply": result.get("data", ""),
        "usage": result.get("usage", {}),
        "latencyMs": timer.elapsed_ms,
        "model": client.model,
    }


# ── Diagnostics ───────────────────────────────────────────────────────────────

@router.get("/applications/{app_id}/diagnostics")
def export_diagnostics(app_id: str, db: Session = Depends(db_session)) -> dict[str, Any]:
    from app.services.application_assistant.log_redaction import redact_dict

    draft = get_application_draft(db, app_id)
    if not draft:
        raise HTTPException(status_code=404, detail="Application not found")

    browser_run = get_active_browser_run_for_app(db, app_id)
    sanitized_fields = []
    for field in draft.get("fields", []):
        sanitized_fields.append({
            "label": field.get("label"),
            "normalizedKey": field.get("normalizedKey"),
            "classification": field.get("classification"),
            "filled": field.get("filled"),
            "required": field.get("required"),
            "sensitivityCategory": field.get("sensitivityCategory"),
        })

    return {
        "success": True,
        "bundle": redact_dict({
            "applicationId": app_id,
            "company": draft.get("companyName"),
            "role": draft.get("roleTitle"),
            "provider": draft.get("provider"),
            "status": draft.get("status"),
            "progress": draft.get("progress"),
            "fields": sanitized_fields,
            "errors": draft.get("errors", []),
            "skipped": draft.get("skipped", []),
            "prepLog": draft.get("prepLog"),
            "stoppedReason": draft.get("stoppedReason", ""),
            "browserRun": {
                "id": browser_run.get("id") if browser_run else None,
                "status": browser_run.get("status") if browser_run else None,
                "tracePath": browser_run.get("tracePath") if browser_run else None,
            },
            "screenshotCount": len(draft.get("screenshots", [])),
        }),
    }


@router.post("/generate-answer")
async def generate_answer_route(
    payload: GenerateAnswerPayload,
    db: Session = Depends(db_session),
) -> dict[str, Any]:
    """Generate answer for a freeform screening/textarea question using Ollama Qwen + user profile."""
    from app.services.application_assistant.llm_answer_generator import generate_theory_answer

    profile = get_kv(db, "profile") or {}
    docs = get_kv(db, "documents") or {}
    default_resume = docs.get("defaultResume") or {}
    resume_text = default_resume.get("text") or default_resume.get("content") or profile.get("resumeText") or ""
    settings = get_settings(db)

    result = await generate_theory_answer(
        payload.question,
        company=payload.company,
        role=payload.role,
        job_description=payload.jobDescription,
        profile=profile,
        resume_text=resume_text,
        settings=settings,
    )
    if not result.get("success"):
        raise HTTPException(status_code=400, detail=result.get("error", "Answer generation failed"))
    return result


# ── Autopilot Autonomous Runner Routes ────────────────────────────────────────

@router.post("/autopilot/start")
async def start_autopilot(
    options: dict[str, Any] = Body(default_factory=dict),
    db: Session = Depends(db_session),
) -> dict[str, Any]:
    from app.services.application_assistant.autopilot_runner import AutopilotRunner
    runner = AutopilotRunner.get_instance()
    run = await runner.start(options=options)
    return {"success": True, "run": run}


@router.post("/autopilot/pause")
async def pause_autopilot(
    db: Session = Depends(db_session),
) -> dict[str, Any]:
    from app.services.application_assistant.autopilot_runner import AutopilotRunner
    runner = AutopilotRunner.get_instance()
    run = await runner.pause(db)
    return {"success": True, "run": run}


@router.post("/autopilot/stop")
async def stop_autopilot(
    db: Session = Depends(db_session),
) -> dict[str, Any]:
    from app.services.application_assistant.autopilot_runner import AutopilotRunner
    runner = AutopilotRunner.get_instance()
    run = await runner.stop(db)
    return {"success": True, "run": run}


@router.get("/llm-metrics")
def get_llm_metrics() -> dict[str, Any]:
    """Which model actually answered each LLM call since the backend last restarted,
    across every flow (form-field self-healing, code-patch self-healing, answer
    resolution, etc.) — counts are process-wide, not per-run."""
    from app.services.application_assistant.llm_client import llm_call_metrics

    return {"success": True, "metrics": llm_call_metrics.to_dict()}


@router.post("/llm-metrics/reset")
def reset_llm_metrics() -> dict[str, Any]:
    from app.services.application_assistant.llm_client import llm_call_metrics

    llm_call_metrics.reset()
    return {"success": True}


@router.get("/autopilot/status")
def get_autopilot_status(
    db: Session = Depends(db_session),
) -> dict[str, Any]:
    from app.services.application_assistant.autopilot_runner import AutopilotRunner
    runner = AutopilotRunner.get_instance()
    return runner.get_status(db)


@router.get("/autopilot/events")
async def autopilot_events_sse(
    request: Request,
) -> StreamingResponse:
    """Server-Sent Events (SSE) push stream for live dashboard logs and worker updates."""
    import asyncio
    from app.services.application_assistant.autopilot_runner import AutopilotRunner
    from app.db.store import session_scope

    runner = AutopilotRunner.get_instance()
    queue = runner.subscribe_events()

    async def event_generator():
        # Send initial status snapshot immediately on connect
        try:
            with session_scope() as db:
                initial_status = runner.get_status(db)
            yield f"event: status\ndata: {json.dumps(initial_status)}\n\n"
        except Exception:
            pass

        try:
            while True:
                if await request.is_disconnected():
                    break
                try:
                    # Wait up to 15s for push event or send keep-alive heartbeat
                    msg = await asyncio.wait_for(queue.get(), timeout=12.0)
                    evt_type = msg.get("event", "message")
                    evt_data = json.dumps(msg.get("data", {}))
                    yield f"event: {evt_type}\ndata: {evt_data}\n\n"
                except asyncio.TimeoutError:
                    # Heartbeat comment to keep SSE connection alive
                    yield ": ping\n\n"
        finally:
            runner.unsubscribe_events(queue)

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


@router.get("/autopilot/workers")
def get_autopilot_workers() -> dict[str, Any]:
    """Return live per-worker status for each concurrency slot."""
    from app.services.application_assistant.autopilot_runner import AutopilotRunner
    runner = AutopilotRunner.get_instance()
    workers = [ws.to_dict() for ws in runner.worker_states.values()]
    active_count = sum(1 for ws in runner.worker_states.values() if ws.status not in ("idle", "done"))
    return {
        "success": True,
        "workers": workers,
        "concurrency": runner.concurrency,
        "activeWorkers": active_count,
        "concurrencyMetrics": runner.metrics.to_dict(active_count, runner.concurrency),
    }


@router.post("/autopilot/self-heal")
async def trigger_self_heal() -> dict[str, Any]:
    """Manually trigger a self-healing cycle for all currently failed autopilot jobs."""
    from app.services.application_assistant.autopilot_runner import AutopilotRunner
    from app.services.application_assistant.autopilot_self_healer import run_self_healing_cycle
    from app.services.application_assistant.persistence import list_autopilot_jobs

    runner = AutopilotRunner.get_instance()
    failed_jobs: list[dict[str, Any]] = []
    with session_scope() as db:
        all_jobs = list_autopilot_jobs(db)
        failed_jobs = [j for j in all_jobs if j.get("status") in ("FAILED", "ERROR")]

    if not failed_jobs:
        return {"success": True, "message": "No failed jobs to heal", "patchesApplied": 0}

    result = await run_self_healing_cycle(
        failed_jobs=failed_jobs,
        log_event_fn=runner.log_event,
    )

    # If patches were applied, restart the autopilot to process re-queued jobs
    if result.get("patchesApplied", 0) > 0:
        run = await runner.start(options={"targetProcessCount": len(failed_jobs)})
        result["autopilotRestarted"] = True
        result["run"] = run

    return {"success": True, **result}


@router.get("/autopilot/self-healing-log")
def get_self_healing_log() -> dict[str, Any]:
    """Return the full patch history from self-healing cycles."""
    from app.services.application_assistant.autopilot_self_healer import get_self_healing_state
    state = get_self_healing_state()
    return {
        "success": True,
        **state.to_dict(),
    }


@router.get("/autopilot/jobs")
def get_autopilot_jobs_list(
    status: str | None = Query(default=None),
    db: Session = Depends(db_session),
) -> dict[str, Any]:
    from app.services.application_assistant.persistence import list_autopilot_jobs
    jobs = list_autopilot_jobs(db, status=status)
    return {"success": True, "jobs": jobs, "count": len(jobs)}


@router.delete("/autopilot/jobs/{job_id}")
def delete_autopilot_job_endpoint(
    job_id: str,
    db: Session = Depends(db_session),
) -> dict[str, Any]:
    """Delete a specific application job from processing/queue."""
    from app.services.application_assistant.persistence import delete_autopilot_job, get_autopilot_job
    existing = get_autopilot_job(db, job_id)
    if not existing:
        raise HTTPException(status_code=404, detail="Job application not found")
    delete_autopilot_job(db, job_id)
    return {"success": True, "deletedId": job_id, "message": f"Successfully removed job application '{existing.get('title')}'"}


@router.get("/autopilot/staged")
def get_staged_applications(
    db: Session = Depends(db_session),
) -> dict[str, Any]:
    from app.services.application_assistant.persistence import list_autopilot_jobs
    jobs = list_autopilot_jobs(db)
    staged = [j for j in jobs if j.get("status") in ("STAGED", "NEEDS_REVIEW")]
    return {"staged": staged, "count": len(staged)}


@router.post("/autopilot/staged/{id}/approve")
def approve_staged_answer(
    id: str,
    payload: dict[str, Any] = Body(default_factory=dict),
    db: Session = Depends(db_session),
) -> dict[str, Any]:
    from app.services.application_assistant.persistence import get_autopilot_job, save_autopilot_job, upsert_answer
    from app.db.store import new_id, now_iso

    job = get_autopilot_job(db, id)
    if not job:
        raise HTTPException(status_code=404, detail="Staged application not found")

    question = payload.get("question") or ""
    answer = payload.get("answer") or ""

    if question and answer:
        entry = {
            "id": new_id("lib_"),
            "normalizedKey": question.strip().lower(),
            "questionVariants": [question],
            "answerType": "short_text",
            "value": answer,
            "verificationStatus": "verified",
            "source": "user_approved",
            "createdAt": now_iso(),
            "updatedAt": now_iso(),
        }
        upsert_answer(db, entry)

    job["status"] = "QUEUED"
    save_autopilot_job(db, job)
    return {"success": True, "job": job}


@router.post("/autopilot/staged/{id}/skip")
def skip_staged_application(
    id: str,
    payload: dict[str, Any] = Body(default_factory=dict),
    db: Session = Depends(db_session),
) -> dict[str, Any]:
    from app.services.application_assistant.persistence import get_autopilot_job, save_autopilot_job

    job = get_autopilot_job(db, id)
    if not job:
        raise HTTPException(status_code=404, detail="Staged application not found")

    job["status"] = "SKIPPED"
    job["skipReason"] = payload.get("reason") or "Skipped by user in Review Center"
    save_autopilot_job(db, job)
    return {"success": True, "job": job}


@router.post("/autopilot/enqueue")
def enqueue_job_for_autopilot(
    payload: dict[str, Any] = Body(default_factory=dict),
    db: Session = Depends(db_session),
) -> dict[str, Any]:
    from app.services.application_assistant.persistence import save_autopilot_job, is_duplicate_application
    from app.db.store import new_id, now_iso

    company = payload.get("company") or "Unknown Company"
    title = payload.get("title") or "Unknown Role"
    app_url = payload.get("applicationUrl") or ""

    # ── Idempotent duplicate guard ──
    is_dup, existing = is_duplicate_application(db, company, title, app_url)
    if is_dup and existing:
        return {
            "success": True,
            "deduplicated": True,
            "message": f"Already exists as {existing.get('status', 'UNKNOWN')} (id={existing.get('id')})",
            "job": existing,
        }

    # ── Hard filter pre-check (US citizenship & sponsorship / SWE role / location) ──
    from app.services.application_assistant.job_filter_ranker import evaluate_hard_filters
    from app.db.store import get_kv
    profile = get_kv(db, "profile") or {}
    passed, skip_reason = evaluate_hard_filters(payload, profile, [])
    if not passed:
        return {
            "success": False,
            "filtered": True,
            "message": f"Application not enqueued: {skip_reason}",
            "reason": skip_reason,
        }

    job_item = {
        "id": new_id("apjob_"),
        "jobId": payload.get("jobId") or new_id("job_"),
        "company": company,
        "title": title,
        "applicationUrl": app_url,
        "status": "QUEUED",
        "matchScore": float(payload.get("matchScore") or 85.0),
        "discoveredAt": now_iso(),
        "queuedAt": now_iso(),
    }
    saved = save_autopilot_job(db, job_item)
    return {"success": True, "deduplicated": False, "job": saved}


@router.post("/autopilot/reset-submitted")
def reset_submitted_autopilot_jobs(
    payload: dict[str, Any] = Body(default_factory=dict),
    db: Session = Depends(db_session),
) -> dict[str, Any]:
    """Reset submitted/processed autopilot jobs back to UNAPPLIED so they can be re-applied."""
    from app.services.application_assistant.persistence import delete_autopilot_job, list_autopilot_jobs
    status_filter = payload.get("status")  # Optional: "SUBMITTED", "ALL", etc.
    all_jobs = list_autopilot_jobs(db)

    reset_count = 0
    for job in all_jobs:
        job_status = job.get("status", "")
        should_reset = False
        if not status_filter or status_filter == "ALL":
            should_reset = job_status in ("SUBMITTED", "STAGED", "FAILED", "SKIPPED", "PROCESSED", "APPLYING")
        elif status_filter == "SUBMITTED":
            should_reset = job_status == "SUBMITTED"
        elif job_status == status_filter:
            should_reset = True

        if should_reset:
            delete_autopilot_job(db, job["id"])
            reset_count += 1

    return {"success": True, "resetCount": reset_count, "message": f"Successfully reset {reset_count} job(s) to unapplied"}


def _requeue_autopilot_jobs_by_status(statuses: tuple[str, ...]) -> dict[str, Any]:
    from app.services.application_assistant.persistence import list_autopilot_jobs, save_autopilot_job
    from app.db.store import session_scope, now_iso

    reprocessed_count = 0
    with session_scope() as db:
        jobs = list_autopilot_jobs(db)
        for j in jobs:
            if j.get("status") in statuses:
                j["status"] = "QUEUED"
                j["lastError"] = None
                j["lastErrorType"] = None
                j["attemptCount"] = 0
                j["lockedBy"] = None
                j["lockedAt"] = None
                j["lockExpiresAt"] = None
                j["queuedAt"] = now_iso()
                save_autopilot_job(db, j)
                reprocessed_count += 1

    return {
        "success": True,
        "reprocessedCount": reprocessed_count,
        "message": f"Queued {reprocessed_count} application(s). Choose a batch size and press Start Run when you are ready.",
    }


@router.post("/autopilot/reprocess-failed")
async def reprocess_failed_autopilot_jobs() -> dict[str, Any]:
    """Return only FAILED/ERROR applications to the queue without starting Autopilot."""
    return _requeue_autopilot_jobs_by_status(("FAILED", "ERROR", "VALIDATION_FAILED"))


@router.post("/autopilot/reprocess-staged")
async def reprocess_staged_autopilot_jobs() -> dict[str, Any]:
    """Return only STAGED/NEEDS_REVIEW applications to the queue without starting Autopilot."""
    return _requeue_autopilot_jobs_by_status(("STAGED", "NEEDS_REVIEW"))


@router.post("/autopilot/jobs/{id}/reprocess")
async def reprocess_single_autopilot_job(id: str) -> dict[str, Any]:
    """Return one failed job to the queue without starting Autopilot."""
    from app.services.application_assistant.persistence import get_autopilot_job, save_autopilot_job
    from app.db.store import session_scope, now_iso

    job_title = ""
    with session_scope() as db:
        job = get_autopilot_job(db, id)
        if not job:
            raise HTTPException(status_code=404, detail="Job not found")

        job_title = job.get("title", "Job")
        job["status"] = "QUEUED"
        job["lastError"] = None
        job["lastErrorType"] = None
        job["attemptCount"] = 0
        job["lockedBy"] = None
        job["lockedAt"] = None
        job["lockExpiresAt"] = None
        job["queuedAt"] = now_iso()
        save_autopilot_job(db, job)

    return {
        "success": True,
        "id": id,
        "message": f"Queued '{job_title}'. Press Start Run when you are ready to process it.",
    }


@router.post("/autopilot/jobs/{id}/reset")
def reset_single_autopilot_job_endpoint(id: str) -> dict[str, Any]:
    """Reset a single autopilot job back to unapplied state by removing it from the autopilot entity list."""
    from app.services.application_assistant.persistence import get_autopilot_job, delete_autopilot_job
    from app.db.store import session_scope

    with session_scope() as db:
        job = get_autopilot_job(db, id)
        if not job:
            raise HTTPException(status_code=404, detail="Job not found in autopilot list")
        job_title = job.get("title", "Job")
        delete_autopilot_job(db, id)

    return {
        "success": True,
        "id": id,
        "message": f"Successfully reset '{job_title}' to unapplied.",
    }


# ─── TSENTA SUITE: VISUAL DIFFS, PRE-FLIGHT APPROVAL, RECEIPTS & EMAIL SYNC ───

@router.get("/jobs/{id}/tailor-diff")
async def get_job_tailor_diff(
    id: str,
    mode: str | None = None,
    db: Session = Depends(db_session),
) -> dict[str, Any]:
    """Generate or retrieve role-tailored materials with full visual diff chunks."""
    from app.services.application_assistant.persistence import get_autopilot_job, get_settings
    from app.services.application_assistant.resume_diff_service import generate_role_tailoring_diff
    from app.db.store import get_kv

    active_mode = mode or get_settings(db).get("tailoringMode", "honest")
    job = get_autopilot_job(db, id)
    if not job:
        # Fallback: check job search table or mock job item
        queue = get_kv(db, "autopilot_job_queue") or []
        for q in queue:
            if isinstance(q, dict) and q.get("id") == id:
                job = q
                break

    if not job:
        job = {"id": id, "title": "Software Engineer", "company": "Target Company"}

    profile = get_kv(db, "profile") or {}
    master_resume = get_kv(db, "resume_corpus_master") or {}

    diff_data = await generate_role_tailoring_diff(job, profile, master_resume, mode=active_mode)
    return {"success": True, "diff": diff_data}


@router.post("/jobs/{id}/preflight-approve")
async def approve_preflight_submission(
    id: str,
    payload: dict[str, Any] = Body(default_factory=dict),
    db: Session = Depends(db_session),
) -> dict[str, Any]:
    """Approve pre-flight tailored materials and enqueue job for cloud submission."""
    from app.services.application_assistant.persistence import get_autopilot_job, save_autopilot_job
    from app.services.application_assistant.autopilot_runner import AutopilotRunner
    from app.db.store import now_iso

    job = get_autopilot_job(db, id)
    if not job:
        raise HTTPException(status_code=404, detail="Application not found")

    job["status"] = "QUEUED"
    job["preflightApproved"] = True
    job["preflightApprovedAt"] = now_iso()
    if payload.get("customAnswers"):
        job["customAnswers"] = payload["customAnswers"]
    save_autopilot_job(db, job)

    runner = AutopilotRunner.get_instance()
    run = await runner.start(options={"targetProcessCount": 1})
    return {
        "success": True,
        "message": f"Pre-flight approved for {job.get('company')} — cloud submission initiated.",
        "job": job,
        "run": run,
    }


@router.get("/receipts/{id}")
def get_receipt_endpoint(id: str) -> dict[str, Any]:
    """Fetch an archived submission receipt by jobId or receiptId."""
    from app.services.application_assistant.submission_receipt_service import get_submission_receipt

    receipt = get_submission_receipt(id)
    if not receipt:
        raise HTTPException(status_code=404, detail="Submission receipt not found")
    return {"success": True, "receipt": receipt}


@router.get("/receipts")
def list_receipts_endpoint() -> dict[str, Any]:
    """List all archived submission receipts."""
    from app.services.application_assistant.submission_receipt_service import list_all_submission_receipts

    receipts = list_all_submission_receipts()
    return {"success": True, "receipts": receipts, "total": len(receipts)}


@router.post("/email-sync")
def email_sync_webhook(
    payload: dict[str, Any] = Body(...),
) -> dict[str, Any]:
    """Inbound email sync webhook to parse recruiter responses and update job status."""
    from app.services.application_assistant.inbound_email_tracker import process_inbound_email

    sender = payload.get("sender") or payload.get("from") or "recruiter@company.com"
    subject = payload.get("subject") or "Application Update"
    body = payload.get("body") or payload.get("text") or ""
    received_at = payload.get("receivedAt") or payload.get("date")

    record = process_inbound_email(sender, subject, body, received_at)
    return {"success": True, "record": record}


@router.post("/autopilot/audit-sponsorship")
def audit_sponsorship_endpoint(
    db: Session = Depends(db_session),
) -> dict[str, Any]:
    """Audit all queued and staged applications against US citizenship & sponsorship criteria."""
    from app.services.application_assistant.persistence import list_autopilot_jobs, save_autopilot_job, delete_autopilot_job
    from app.services.application_assistant.job_filter_ranker import evaluate_hard_filters
    from app.db.store import get_kv

    profile = get_kv(db, "profile") or {}
    jobs = list_autopilot_jobs(db)
    
    skipped_count = 0
    skipped_jobs: list[dict[str, Any]] = []

    for job in jobs:
        # Check jobs not yet submitted
        if job.get("status") in ("QUEUED", "STAGED", "NEEDS_REVIEW", "FAILED"):
            passed, reason = evaluate_hard_filters(job, profile, [])
            if not passed and ("citizenship" in reason.lower() or "sponsorship" in reason.lower() or "itar" in reason.lower()):
                job["status"] = "SKIPPED"
                job["skipReason"] = reason
                job["aiExplanation"] = f"Filtered: {reason}"
                save_autopilot_job(db, job)
                skipped_count += 1
                skipped_jobs.append({
                    "id": job.get("id"),
                    "company": job.get("company"),
                    "title": job.get("title"),
                    "reason": reason,
                })

    return {
        "success": True,
        "auditedTotal": len(jobs),
        "skippedCount": skipped_count,
        "skippedJobs": skipped_jobs,
        "message": f"Audited {len(jobs)} jobs. Flagged/Skipped {skipped_count} jobs requiring US Citizenship or lacking sponsorship.",
    }





