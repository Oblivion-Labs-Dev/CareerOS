"""Application Assistant API routes."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Body, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.db.store import get_kv, session_scope, now_iso
from app.services.application_assistant.browser_runner import close_session
from app.services.application_assistant.job_discovery import (
    cancel_discovery,
    filter_jobs,
    run_discovery,
)
from app.services.application_assistant.job_matching import match_job
from app.services.application_assistant.llm_client import create_llm_client
from app.services.application_assistant.persistence import (
    create_application_draft,
    create_discovery_run,
    delete_answer,
    get_active_browser_run_for_app,
    get_answer,
    get_application_draft,
    get_discovery_run,
    get_discovered_job,
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
    from app.services.application_assistant.qwen_agent import start_autonomous_prepare
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
    from app.services.application_assistant.qwen_agent import get_agent_run
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
    from app.services.application_assistant.qwen_agent import _get_agent_runs, reconcile_stale_prep_state
    from app.services.application_assistant.browser_replay import summarize_application_list_item
    from app.services.application_assistant.persistence import index_active_browser_runs

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
    from app.services.application_assistant.qwen_agent import reconcile_stale_prep_state

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
    from app.services.application_assistant.qwen_agent import execute_application_prepare

    prep = await execute_application_prepare(app_id)
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
    from app.services.application_assistant.qwen_agent import schedule_autonomous_prepare

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
    from app.services.application_assistant.qwen_agent import schedule_autonomous_prepare

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
    draft = update_application_draft(db, app_id, {"status": "archived"})
    if not draft:
        raise HTTPException(status_code=404, detail="Application not found")
    return {"success": True, "application": draft}


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


@router.get("/applications/{app_id}/review-status")
def review_session_status(app_id: str, db: Session = Depends(db_session)) -> dict[str, Any]:
    from app.services.application_assistant.qwen_agent import get_review_session_status

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
    from app.services.application_assistant.qwen_agent import execute_application_open_review

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
    from app.services.application_assistant.qwen_agent import (
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
    from app.services.application_assistant.qwen_agent import get_agent_run

    run = get_agent_run(db, app_id)
    draft = get_application_draft(db, app_id)
    return {"success": True, "run": run, "application": draft}


@router.get("/qwen/status")
async def qwen_status(db: Session = Depends(db_session)) -> dict[str, Any]:
    from app.services.application_assistant.qwen_activity import get_metrics, update_connection_status

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
    from app.services.application_assistant.qwen_agent import get_agent_run

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
    from app.services.application_assistant.qwen_agent import build_chat_context

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
