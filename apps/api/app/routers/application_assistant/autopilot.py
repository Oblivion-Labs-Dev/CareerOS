"""Application Assistant API routes — autopilot domain."""

from ._common import *  # noqa: F401,F403

router = APIRouter(prefix="/application-assistant", tags=["application-assistant"])


# ── Autopilot Autonomous Runner Routes ────────────────────────────────────────

@router.post("/autopilot/start")
async def start_autopilot(
    options: dict[str, Any] = Body(default_factory=dict),
) -> dict[str, Any]:
    # No Depends(db_session) here on purpose: a batch run can take many minutes,
    # and holding a pooled connection open for the whole request (unused — the
    # runner opens its own short-lived sessions internally) is what previously
    # exhausted the connection pool. See approve_preflight_submission for the
    # same fix applied to the single-job apply path.
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
    status: str | None = Query(default=None, description="Single status, or comma-separated list (e.g. QUEUED,NEEDS_REVIEW,STAGED)"),
    role: str | None = Query(default=None, description="Case-insensitive substring match against job title"),
    location: str | None = Query(default=None, description="Case-insensitive substring match against job location"),
    company: str | None = Query(default=None, description="Case-insensitive substring match against company name"),
    limit: int = Query(default=24, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    db: Session = Depends(db_session),
) -> dict[str, Any]:
    """List autopilot jobs, filtered and paginated server-side.

    The entity store isn't indexed for this (see list_entities in db/store.py —
    it loads every row of the type and filters in Python), so this doesn't scale
    to a huge table yet. But moving filtering here, out of the frontend, means
    the client only ever receives one page of results instead of the whole
    queue — the actual thing worth fixing today. Real scale later means giving
    autopilot jobs real indexed columns (status/company/title/location) instead
    of an opaque JSON payload blob.
    """
    from app.services.application_assistant.persistence import list_autopilot_jobs

    statuses = [s.strip() for s in status.split(",")] if status else [None]
    jobs: list[dict[str, Any]] = []
    for s in statuses:
        jobs.extend(list_autopilot_jobs(db, status=s))

    role_q = (role or "").strip().lower()
    location_q = (location or "").strip().lower()
    company_q = (company or "").strip().lower()
    if role_q:
        jobs = [j for j in jobs if role_q in str(j.get("title") or "").lower()]
    if location_q:
        jobs = [j for j in jobs if location_q in str(j.get("location") or "").lower()]
    if company_q:
        jobs = [j for j in jobs if company_q in str(j.get("company") or "").lower()]

    jobs.sort(key=lambda j: j.get("matchScore") or 0, reverse=True)

    total = len(jobs)
    page = jobs[offset:offset + limit]
    return {
        "success": True,
        "jobs": page,
        "count": len(page),
        "total": total,
        "hasMore": offset + limit < total,
    }


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


@router.post("/autopilot/jobs/{id}/classify-questions")
async def classify_pending_questions(id: str) -> dict[str, Any]:
    """On-demand model classification of a NEEDS_REVIEW/STAGED job's outstanding
    questions, for jobs that were staged before pendingQuestions existed (or whose
    original DOM field metadata wasn't captured). Re-running the whole live browser
    submission just to get cleaner question text would be wasteful — this reruns
    only the cheap classification step against whatever evidence is already on file.
    Idempotent: if the job already has pendingQuestions, they're returned as-is.

    Deliberately avoids `Depends(db_session)` — classification runs several
    45-second-class model calls, and holding a pooled connection open for that
    whole span (per request, and worse per accidental duplicate) is what exhausted
    the connection pool previously. See approve_preflight_submission for the same fix.
    """
    from app.services.application_assistant.persistence import get_autopilot_job, save_autopilot_job
    from app.services.application_assistant.error_normalizer import build_pending_questions
    from app.db.store import session_scope

    with session_scope() as db:
        job = get_autopilot_job(db, id)
        if not job:
            raise HTTPException(status_code=404, detail="Job not found")

        if job.get("pendingQuestions"):
            return {"success": True, "pendingQuestions": job["pendingQuestions"]}

        blocking_issues = (
            ((job.get("submissionEvidence") or {}).get("policyEvaluation") or {}).get("blockingIssues", [])
        )

        if not blocking_issues:
            # No structured evidence on file (job predates the policy engine) — fall back to
            # splitting the raw error text itself; the model still has enough to work with.
            raw = (job.get("lastError") or job.get("aiExplanation") or "")
            raw = raw.split(":", 1)[-1] if raw.lower().startswith("staged for human review:") else raw
            blocking_issues = [{"reason": part.strip()} for part in raw.split(";") if part.strip()]

    pending_questions = await build_pending_questions(blocking_issues)

    job["pendingQuestions"] = pending_questions
    with session_scope() as db:
        save_autopilot_job(db, job)
    return {"success": True, "pendingQuestions": pending_questions}


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
        "location": payload.get("location", ""),
        "discoveredAt": now_iso(),
        "queuedAt": now_iso(),
    }
    if payload.get("tailoringMode") in ("off", "honest", "aggressive"):
        job_item["tailoringMode"] = payload["tailoringMode"]
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


@router.post("/autopilot/reprocess-skipped")
async def reprocess_skipped_autopilot_jobs() -> dict[str, Any]:
    """Return all SKIPPED applications to the queue without starting Autopilot.

    Jobs the executor found to be genuinely expired/removed are deleted outright
    (see the `expired` branch in autopilot_runner), never marked SKIPPED, so
    everything this touches was skipped by a hard filter that may no longer
    apply (e.g. sponsorship policy or profile changes) — safe to retry.
    """
    return _requeue_autopilot_jobs_by_status(("SKIPPED",))


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


