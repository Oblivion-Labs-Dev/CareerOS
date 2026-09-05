"""Application Assistant API routes — applications domain."""

from ._common import *  # noqa: F401,F403

router = APIRouter(prefix="/application-assistant", tags=["application-assistant"])


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


