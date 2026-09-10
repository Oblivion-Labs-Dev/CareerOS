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


@router.get("/autopilot/queue-preparation")
def get_queue_preparation_status() -> dict[str, Any]:
    """Live state of the background queue pipeline.

    Reports what the continuous scrape -> dedupe -> eligibility -> Mistral match
    -> queue preparation has actually done, so the operational view never has to
    infer progress from the size of the queue alone.
    """
    from app.services.application_assistant.queue_preprocessor import get_preprocessor, get_stats

    preprocessor = get_preprocessor()
    stats = get_stats()
    stats["running"] = preprocessor.is_running()
    return {"success": True, "preparation": stats}


@router.post("/autopilot/queue-preparation/start")
async def start_queue_preparation() -> dict[str, Any]:
    from app.services.application_assistant.queue_preprocessor import get_preprocessor

    return await get_preprocessor().start()


@router.post("/autopilot/queue-preparation/stop")
async def stop_queue_preparation() -> dict[str, Any]:
    from app.services.application_assistant.queue_preprocessor import get_preprocessor

    return await get_preprocessor().stop()


# A live run's counters should still look like they are moving, so this is
# deliberately shorter than the dashboard aggregate TTL.
AUTOPILOT_STATUS_TTL_SECONDS = 3.0

# The job list is invalidated on every write, so this TTL only governs how
# quickly a change made by the background runner (not by the user) appears.
AUTOPILOT_JOBS_TTL_SECONDS = 5.0

# How long an assisted fill leaves the browser open for the candidate. It ends
# as soon as they close the window, so this is only the ceiling.
ASSISTED_HANDOFF_SECONDS = 600.0

@router.get("/autopilot/status")
def get_autopilot_status() -> dict[str, Any]:
    # No Depends(db_session): this is one of the most frequently polled endpoints
    # (the dashboard hits it every few seconds alongside /jobs and /staged), and
    # Depends(db_session) holds a pooled connection for the whole request/response
    # cycle. Under any slowdown elsewhere (e.g. a long-running autopilot submission
    # contending for the same SQLite file), enough of these pile up concurrently to
    # exhaust the pool — and once that happens even the auth middleware can't get a
    # connection, freezing the entire API. A short-lived session_scope() avoids that.
    from app.services.application_assistant.autopilot_runner import AutopilotRunner
    from app.db.store import session_scope

    # Also served from the background-refreshed read cache: the dashboard polls
    # this every few seconds from several components at once, and the status is
    # an aggregate that is allowed to be a beat behind. A short TTL keeps a live
    # run's progress visibly moving while taking the recompute off every poll.
    from app.services.read_cache import read_cache

    def _load() -> dict[str, Any]:
        runner = AutopilotRunner.get_instance()
        with session_scope() as db:
            return runner.get_status(db)

    return read_cache.get("autopilot_status", AUTOPILOT_STATUS_TTL_SECONDS, _load)


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


# Per-job fields no card or side panel reads, and which dominate the response:
# across a sample of rows, checkpointHistory and submissionEvidence alone were
# about seven eighths of the bytes. A page of 20 jobs was 185KB, which is what
# made the All tab feel slow — the backend was already answering in ~20ms. The
# journey view fetches checkpoints on its own when a job is opened.
_LIST_OMITTED_FIELDS = (
    "checkpointHistory",
    "submissionEvidence",
    "fieldsFilled",
    "confirmationScreenshot",
    "presubmitScreenshot",
    "matchReasons",
    "aiExplanation",
)


def _lean_job(job: dict[str, Any]) -> dict[str, Any]:
    """A job row trimmed to what the applications list actually renders."""
    return {k: v for k, v in job.items() if k not in _LIST_OMITTED_FIELDS}


@router.get("/autopilot/jobs")
def get_autopilot_jobs_list(
    status: str | None = Query(default=None, description="Single status, or comma-separated list (e.g. QUEUED,NEEDS_REVIEW,STAGED)"),
    search: str | None = Query(default=None),
    role: str | None = Query(default=None, description="Case-insensitive substring match against job title"),
    location: str | None = Query(default=None, description="Case-insensitive substring match against job location"),
    company: str | None = Query(default=None, description="Case-insensitive substring match against company name"),
    sortBy: str = Query(default="matchScore", description="Field to sort by: matchScore, submittedAt, or updatedAt"),
    sortDir: str = Query(default="desc", description="asc or desc"),
    limit: int = Query(default=24, ge=1, le=1000),
    offset: int = Query(default=0, ge=0),
) -> dict[str, Any]:
    """List autopilot jobs, filtered and paginated server-side.

    The entity store isn't indexed for this (see list_entities in db/store.py —
    it loads every row of the type and filters in Python), so this doesn't scale
    to a huge table yet. But moving filtering here, out of the frontend, means
    the client only ever receives one page of results instead of the whole
    queue — the actual thing worth fixing today. Real scale later means giving
    autopilot jobs real indexed columns (status/company/title/location) instead
    of an opaque JSON payload blob.

    No Depends(db_session): this is polled every few seconds by the dashboard
    (five times over, once per status filter) — holding a pooled connection for
    each request's full lifetime is how the pool gets exhausted under load. See
    get_autopilot_status above.
    """
    from app.services.application_assistant.persistence import (
        AUTOPILOT_JOBS_CACHE_KEY,
        list_autopilot_jobs,
    )
    from app.db.store import session_scope
    from app.services.read_cache import read_cache

    statuses = {s.strip() for s in status.split(",")} if status else None

    # The whole job list is cached, rather than one cache entry per query-string
    # combination: the filters below are cheap once the rows are in memory, and
    # a shared list means a search box that fires on every keystroke does not
    # each time re-parse every row of the table. Writes invalidate it, so the
    # user's own Apply / Mark submitted still shows up immediately.
    def _load_all_jobs() -> list[dict[str, Any]]:
        with session_scope() as db:
            return list_autopilot_jobs(db)

    all_jobs = read_cache.get(AUTOPILOT_JOBS_CACHE_KEY, AUTOPILOT_JOBS_TTL_SECONDS, _load_all_jobs)
    jobs = [job for job in all_jobs if not statuses or job.get("status") in statuses]
    status_counts: dict[str, int] = {}
    for job in all_jobs:
        key = str(job.get("status") or "QUEUED")
        status_counts[key] = status_counts.get(key, 0) + 1
    if search and search.strip():
        needle = search.strip().lower()
        jobs = [j for j in jobs if any(needle in str(j.get(k) or "").lower()
                for k in ("company", "title", "location", "status", "lastErrorType"))]
    role_q = (role or "").strip().lower()
    location_q = (location or "").strip().lower()
    company_q = (company or "").strip().lower()
    if role_q:
        jobs = [j for j in jobs if role_q in str(j.get("title") or "").lower()]
    if location_q:
        jobs = [j for j in jobs if location_q in str(j.get("location") or "").lower()]
    if company_q:
        jobs = [j for j in jobs if company_q in str(j.get("company") or "").lower()]

    reverse = sortDir.lower() != "asc"
    jobs.sort(key=lambda j: str(j.get("id") or ""))
    if sortBy == "company":
        jobs.sort(key=lambda j: str(j.get("company") or "").lower(), reverse=reverse)
    elif sortBy == "priority":
        from app.services.application_assistant.application_list_priority import application_list_priority
        jobs.sort(key=application_list_priority, reverse=reverse)
    elif sortBy in ("submittedAt", "updatedAt"):
        jobs.sort(key=lambda j: str(j.get(sortBy) or j.get("updatedAt") or ""), reverse=reverse)
    else:
        jobs.sort(key=lambda j: j.get("matchScore") or 0, reverse=reverse)

    total = len(jobs)
    page = [_lean_job(job) for job in jobs[offset:offset + limit]]
    return {
        "success": True,
        "jobs": page,
        "count": len(page),
        "total": total,
        "statusCounts": status_counts,
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


@router.get("/autopilot/jobs/{job_id}/resume")
def get_autopilot_job_resume(
    job_id: str,
    db: Session = Depends(db_session),
):
    """Serve the exact tailored resume PDF that was attached for this job's
    submission, so the Submitted panel can link straight to it instead of
    only showing the filename as inert text."""
    from pathlib import Path
    from fastapi.responses import FileResponse
    from app.services.application_assistant.persistence import get_autopilot_job

    job = get_autopilot_job(db, job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")

    evidence = job.get("submissionEvidence") or {}
    filename = job.get("resumeFileUsed") or evidence.get("resumeFileUsed")
    if not filename:
        raise HTTPException(status_code=404, detail="No tailored resume was recorded for this submission")

    tailored_dir = Path(__file__).resolve().parents[3] / "data" / "application_assistant" / "tailored_resumes"
    resume_path = (tailored_dir / filename).resolve()
    if tailored_dir.resolve() not in resume_path.parents or not resume_path.is_file():
        raise HTTPException(status_code=404, detail="Resume file no longer exists on disk")

    # FileResponse defaults to Content-Disposition: attachment, which forces
    # a download regardless of how the link is opened. "inline" lets Chrome
    # render it in its built-in PDF viewer in the new tab instead — the user
    # can still save it from there if they want a copy.
    return FileResponse(resume_path, media_type="application/pdf", filename=filename, content_disposition_type="inline")


@router.get("/autopilot/staged")
def get_staged_applications() -> dict[str, Any]:
    # No Depends(db_session) — see get_autopilot_status above.
    # Shares the cached job list with /autopilot/jobs rather than re-reading the
    # table: the dashboard polls both together, so this was parsing every row a
    # second time for a filter it can do in memory.
    from app.services.application_assistant.persistence import (
        AUTOPILOT_JOBS_CACHE_KEY,
        list_autopilot_jobs,
    )
    from app.db.store import session_scope
    from app.services.read_cache import read_cache

    def _load_all_jobs() -> list[dict[str, Any]]:
        with session_scope() as db:
            return list_autopilot_jobs(db)

    jobs = read_cache.get(AUTOPILOT_JOBS_CACHE_KEY, AUTOPILOT_JOBS_TTL_SECONDS, _load_all_jobs)
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

    # When user approves in Review Center, clear any persistent contradiction blocks
    # so the job can be safely retried with the verified answer.
    custom_answers = payload.get("customAnswers") or {}
    if question and answer:
        custom_answers[question] = answer
    if custom_answers:
        job.setdefault("customAnswers", {}).update(custom_answers)

    job.pop("hasPersistentBlock", None)
    job.pop("blockingContradictions", None)
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

    # Statuses this bulk action must never touch. It deletes the autopilot row
    # so the posting can be applied to again, which is destructive for all
    # three: a submitted application already reached a real employer, and
    # skipped/ineligible jobs are the list the user works through by hand.
    # Excluded whether the caller asks for "ALL" or names the status directly.
    BULK_RESET_EXCLUDED = ("SUBMITTED", "SKIPPED", "INELIGIBLE")

    reset_count = 0
    for job in all_jobs:
        job_status = job.get("status", "")
        should_reset = False
        if not status_filter or status_filter == "ALL":
            should_reset = job_status in ("STAGED", "FAILED", "PROCESSED", "APPLYING")
        elif status_filter in BULK_RESET_EXCLUDED:
            should_reset = False
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
            # Never requeue a permanently ineligible posting — it would just fail
            # the same hard filter again and re-pollute the queue.
            if j.get("status") == "INELIGIBLE" or j.get("ineligibilityReason"):
                continue
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


@router.post("/autopilot/reclassify-ineligible")
def reclassify_ineligible_jobs(dry_run: bool = Query(default=False)) -> dict[str, Any]:
    """Re-triage existing NEEDS_REVIEW / FAILED / SKIPPED jobs into INELIGIBLE.

    The review queue is only useful if everything in it is something the user can
    actually act on. Jobs blocked on citizenship, visa sponsorship, a non-US
    location, or a dead posting can never be resolved by review or by a retry, so
    they are moved to INELIGIBLE with the exact reason recorded. Everything else
    is left exactly where it is.
    """
    from app.services.application_assistant.ineligibility import (
        apply_ineligibility,
        classify_ineligibility,
    )
    from app.services.application_assistant.persistence import (
        list_autopilot_jobs,
        save_autopilot_job,
    )
    from app.db.store import session_scope

    TRIAGE_STATUSES = ("NEEDS_REVIEW", "FAILED", "SKIPPED", "ERROR", "VALIDATION_FAILED")
    moved: list[dict[str, Any]] = []
    with session_scope() as db:
        for job in list_autopilot_jobs(db):
            if job.get("status") not in TRIAGE_STATUSES:
                continue
            classified = classify_ineligibility(job)
            if not classified:
                continue
            reason, detail = classified
            moved.append({
                "id": job.get("id"),
                "company": job.get("company"),
                "title": job.get("title"),
                "fromStatus": job.get("status"),
                "reason": reason.value,
                "detail": detail[:300],
            })
            if not dry_run:
                apply_ineligibility(job, reason, detail)
                save_autopilot_job(db, job)

    return {
        "success": True,
        "dryRun": dry_run,
        "reclassifiedCount": len(moved),
        "jobs": moved,
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


@router.post("/autopilot/reconcile-manual-submissions")
def reconcile_manual_submissions_route() -> dict[str, Any]:
    """Mark manually-completed applications submitted from their confirmation email.

    Employers do not send webhooks, but they all email the candidate, and
    CareerOS already reads that inbox — so the confirmation is the signal that a
    manually-finished application actually went out.
    """
    from app.services.application_assistant.manual_submission_reconciler import (
        reconcile_manual_submissions,
    )

    return reconcile_manual_submissions()


@router.post("/autopilot/jobs/{id}/assisted-fill")
async def assisted_fill(id: str) -> dict[str, Any]:
    """Autofill this application in a visible browser and hand it to the user.

    For postings automation can reach but must not finish — a CAPTCHA guards the
    board, or a question only the candidate can answer. Everything the profile
    can answer gets typed in, then the window is left open so the person does
    only the part that actually needs them, instead of re-typing the whole form.
    """
    from app.db.store import session_scope
    from app.services.application_assistant.persistence import (
        get_autopilot_job,
        get_settings,
        list_answer_library,
    )
    from app.services.application_assistant.playwright_autopilot_executor import (
        execute_live_playwright_submission,
    )
    from app.db.store import get_kv

    with session_scope() as db:
        job = get_autopilot_job(db, id)
        if not job:
            raise HTTPException(status_code=404, detail="Application not found")
        profile = get_kv(db, "profile") or {}
        try:
            answer_lib = list_answer_library(db)
        except Exception:
            answer_lib = []
        settings_row = get_settings(db) or {}

    browser_settings = settings_row.get("browser") or {}
    result = await execute_live_playwright_submission(
        job_item=job,
        profile=profile,
        answer_lib=answer_lib,
        # Always visible: the whole point is that a person finishes it.
        headless=False,
        timeout_sec=float(browser_settings.get("timeout") or 60000) / 1000.0,
        fill_only=True,
        hand_off_seconds=ASSISTED_HANDOFF_SECONDS,
    )

    filled = result.get("fieldsFilled") or {}

    # If they submitted it in the window we opened, record that here — the whole
    # point is that they should not have to come back and press "Mark submitted"
    # for something they just did.
    if result.get("submitted"):
        from app.db.store import now_iso
        from app.services.application_assistant.persistence import save_autopilot_job

        with session_scope() as db:
            job = get_autopilot_job(db, id) or job
            job["previousStatus"] = job.get("status")
            job["status"] = "SUBMITTED"
            job["submittedAt"] = now_iso()
            job["submissionSource"] = "manual-assisted"
            job["hasPersistentBlock"] = False
            job["answers"] = {**(job.get("answers") or {}), **filled}
            job["submissionEvidence"] = result.get("evidence") or {}
            save_autopilot_job(db, job)
        return {
            "success": True,
            "assisted": True,
            "submitted": True,
            "filledCount": len(filled),
            "message": f"You submitted the {job.get('company')} application — marked as submitted.",
        }

    return {
        "success": True,
        "assisted": True,
        "submitted": False,
        "filledCount": len(filled),
        "fieldsFilled": filled,
        "message": (
            f"Filled {len(filled)} field(s). Finish the challenge and press Submit "
            "in the browser window that opened."
        ),
    }


@router.post("/autopilot/jobs/{id}/mark-submitted")
def mark_autopilot_job_submitted(
    id: str,
    payload: dict[str, Any] = Body(default_factory=dict),
) -> dict[str, Any]:
    """Record that the user submitted this application by hand.

    Attempts Autopilot could not complete stay in NEEDS_REVIEW/FAILED so the
    user can open the posting and apply themselves; this is how they then take
    the job off that list. Marking is reversible — the prior status is kept so
    the card can be restored if it was pressed by mistake.
    """
    from app.services.application_assistant.persistence import get_autopilot_job, save_autopilot_job
    from app.db.store import session_scope, now_iso

    with session_scope() as db:
        job = get_autopilot_job(db, id)
        if not job:
            raise HTTPException(status_code=404, detail="Application not found")

        if job.get("status") == "SUBMITTED" and job.get("submissionSource") == "manual":
            restored = job.get("previousStatus") or "NEEDS_REVIEW"
            job["status"] = restored
            job["previousStatus"] = None
            job["submittedAt"] = None
            job["submissionSource"] = None
            saved = save_autopilot_job(db, job)
            return {"success": True, "job": saved, "submitted": False}

        job["previousStatus"] = job.get("status")
        job["status"] = "SUBMITTED"
        job["submittedAt"] = now_iso()
        job["submissionSource"] = "manual"
        job["hasPersistentBlock"] = False
        job["lastError"] = None
        saved = save_autopilot_job(db, job)
        return {"success": True, "job": saved, "submitted": True}


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


