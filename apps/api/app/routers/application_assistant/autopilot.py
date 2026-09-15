"""Application Assistant API routes — autopilot domain."""

import logging

from ._common import *  # noqa: F401,F403

logger = logging.getLogger("career_os.application_assistant.autopilot_routes")

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
    logger.info("start_autopilot called with options: %s", options)
    from app.services.application_assistant.autopilot_runner import AutopilotRunner
    runner = AutopilotRunner.get_instance()
    run = await runner.start(options=options)
    logger.info("start_autopilot finished runner.start(), returning run id: %s", (run or {}).get("id"))
    return {"success": True, "run": run}


@router.post("/autopilot/pause")
async def pause_autopilot() -> dict[str, Any]:
    from app.services.application_assistant.autopilot_runner import AutopilotRunner
    runner = AutopilotRunner.get_instance()
    run = await runner.pause()
    return {"success": True, "run": run}


@router.post("/autopilot/stop")
async def stop_autopilot() -> dict[str, Any]:
    from app.services.application_assistant.autopilot_runner import AutopilotRunner
    runner = AutopilotRunner.get_instance()
    run = await runner.stop()
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
# None = the handed-over browser window stays open until the candidate closes
# it. It used to be 600s, which closed the window mid-application on anyone who
# needed longer than ten minutes - the assisted flow exists precisely for forms
# a person has to work through by hand, so putting a stopwatch on it defeated
# the feature.
ASSISTED_HANDOFF_SECONDS: float | None = None

def _cached_autopilot_status() -> dict[str, Any]:
    """Shared by the REST poller and the SSE stream's initial snapshot, so both pay for
    at most one real `get_status()` computation per TTL window instead of each running
    their own uncached scan.

    No `Depends(db_session)`: this is one of the most frequently polled endpoints (the
    dashboard hits it every few seconds alongside /jobs and /staged), and
    Depends(db_session) holds a pooled connection for the whole request/response cycle.
    Under any slowdown elsewhere (e.g. a long-running autopilot submission contending for
    the same SQLite file), enough of these pile up concurrently to exhaust the pool — and
    once that happens even the auth middleware can't get a connection, freezing the
    entire API. A short-lived session_scope() avoids that.

    Also served from the background-refreshed read cache: the dashboard polls this every
    few seconds from several components at once, and the status is an aggregate that is
    allowed to be a beat behind. A short TTL keeps a live run's progress visibly moving
    while taking the recompute off every poll.
    """
    from app.services.application_assistant.autopilot_runner import AutopilotRunner
    from app.db.store import session_scope
    from app.services.read_cache import read_cache

    def _load() -> dict[str, Any]:
        runner = AutopilotRunner.get_instance()
        with session_scope() as db:
            return runner.get_status(db)

    return read_cache.get("autopilot_status", AUTOPILOT_STATUS_TTL_SECONDS, _load)


@router.get("/autopilot/status")
def get_autopilot_status() -> dict[str, Any]:
    return _cached_autopilot_status()


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
        # Send initial status snapshot immediately on connect.
        #
        # This used to call runner.get_status(db) directly, synchronously, right here
        # on the event loop — an uncached full scan of every aa_autopilot_job row
        # (2500+ and growing) that blocks the ENTIRE server, every other request and
        # every other SSE connection, for the full duration of that scan. The REST
        # /autopilot/status endpoint already learned this lesson (see
        # _cached_autopilot_status's docstring) and goes through the read cache + a
        # short-lived session; this path never got the same treatment. Confirmed live
        # via py-spy on 2026-09-15: the MainThread itself sat blocked here for 30+
        # seconds from a single new dashboard connection. Route through the same cache
        # (a connection made while the REST poller keeps it warm is then instant) AND
        # always hop to a worker thread regardless (so even a genuinely cold cache —
        # e.g. right after a restart, exactly what was reproduced — cannot block the
        # loop).
        try:
            initial_status = await asyncio.to_thread(_cached_autopilot_status)
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


@router.get("/autopilot/stats")
def get_autopilot_stats() -> dict[str, Any]:
    """Precomputed aggregated counts by status and company, served instantly from cache."""
    from app.services.application_assistant.persistence import (
        AUTOPILOT_STATS_CACHE_KEY,
        get_autopilot_status_company_stats,
    )
    from app.db.store import session_scope
    from app.services.read_cache import read_cache

    def _load_stats() -> dict[str, Any]:
        with session_scope() as db:
            return get_autopilot_status_company_stats(db)

    stats = read_cache.get(AUTOPILOT_STATS_CACHE_KEY, 30.0, _load_stats)
    return {"success": True, **stats}


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
    """List autopilot jobs, filtered and paginated server-side."""
    from app.services.application_assistant.persistence import (
        AUTOPILOT_JOBS_CACHE_KEY,
        AUTOPILOT_STATS_CACHE_KEY,
        get_autopilot_status_company_stats,
        list_autopilot_jobs,
    )
    from app.db.store import session_scope
    from app.services.read_cache import read_cache

    statuses = {s.strip() for s in status.split(",")} if status else None

    # Load precomputed status and company counts (very fast group-by or memory cache)
    def _load_stats() -> dict[str, Any]:
        with session_scope() as db:
            return get_autopilot_status_company_stats(db)

    stats = read_cache.get(AUTOPILOT_STATS_CACHE_KEY, 30.0, _load_stats)
    status_counts = stats.get("statusCounts", {})
    company_counts_by_status = stats.get("companyCountsByStatus", {})

    if status and status in company_counts_by_status:
        company_counts = dict(company_counts_by_status[status])
    elif status and "," in status:
        company_counts = {}
        for s in (statuses or ()):
            for c, cnt in company_counts_by_status.get(s, {}).items():
                company_counts[c] = company_counts.get(c, 0) + cnt
    elif not status or status.lower() == "all":
        company_counts = dict(company_counts_by_status.get("all", {}))
    else:
        company_counts = {}

    def _load_all_jobs() -> list[dict[str, Any]]:
        with session_scope() as db:
            return list_autopilot_jobs(db)

    all_jobs = read_cache.get(AUTOPILOT_JOBS_CACHE_KEY, AUTOPILOT_JOBS_TTL_SECONDS, _load_all_jobs)
    jobs = [job for job in all_jobs if not statuses or job.get("status") in statuses]

    if not company_counts:
        for job in jobs:
            c_name = (job.get("company") or "").strip()
            if c_name:
                company_counts[c_name] = company_counts.get(c_name, 0) + 1

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
        exact_matches = [j for j in jobs if str(j.get("company") or "").strip().lower() == company_q]
        if exact_matches:
            jobs = exact_matches
        else:
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
    if any(job.get("status") == "SUBMITTED" for job in page):
        from app.services.application_assistant.application_journey import assess_receipt
        with session_scope() as db:
            receipts = get_kv(db, "autopilot_submission_receipts") or {}
        for job in page:
            job["submissionConfirmed"] = job.get("status") == "SUBMITTED" and assess_receipt(job, receipts.get(job["id"]))["state"] == "confirmed"

    return {
        "success": True,
        "jobs": page,
        "count": len(page),
        "total": total,
        "statusCounts": status_counts,
        "companyCounts": company_counts,
        "hasMore": offset + limit < total,
    }


@router.get("/autopilot/jobs/{job_id}")
def get_autopilot_job_detail(job_id: str, db: Session = Depends(db_session)) -> dict[str, Any]:
    from app.services.application_assistant.persistence import get_autopilot_job
    job = get_autopilot_job(db, job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Application not found")
    return {"job": job}


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


def _resolve_job_fields(payload: dict[str, Any]) -> dict[str, Any]:
    """Fill in whatever the pasted link can tell us about the posting.

    A job URL already carries its own company, title and location - the ATS
    marks the page up with Schema.org JobPosting - so asking a person to retype
    them is busywork, and the values they type are the ones most likely to be
    wrong (a company named differently from the board slug breaks the duplicate
    guard). Anything the caller supplied explicitly still wins; this only fills
    the gaps, and falls back to the board slug in the URL when the fetch fails.
    """
    from app.services.job_discover.url_import import (
        autoextract_job_from_url,
        guess_company_from_url,
    )

    resolved = dict(payload)
    url = str(resolved.get("applicationUrl") or "").strip()
    if not url:
        return resolved

    # An aggregator listing is not an application form. Resolve it to the
    # employer's own board first, so what gets stored is a URL the automation
    # can actually submit rather than a page it will never get past.
    from app.services.job_discover.aggregator_resolve import (
        is_aggregator_url,
        resolve_aggregator_url,
    )

    if is_aggregator_url(url):
        found = resolve_aggregator_url(
            url,
            company_name=str(resolved.get("company") or ""),
            title=str(resolved.get("title") or ""),
        )
        if found:
            resolved["applicationUrl"] = found["applicationUrl"]
            resolved["aggregatorUrl"] = url
            resolved.setdefault("company", found.get("company") or "")
            if not str(resolved.get("title") or "").strip():
                resolved["title"] = found.get("title") or ""
            url = found["applicationUrl"]

    needs = not str(resolved.get("company") or "").strip() or not str(resolved.get("title") or "").strip()
    if not needs:
        return resolved

    extracted = None
    try:
        extracted = autoextract_job_from_url(url)
    except Exception:
        logger.debug("Could not auto-extract %s", url, exc_info=True)

    if extracted:
        for key in ("company", "title", "location"):
            if not str(resolved.get(key) or "").strip() and extracted.get(key):
                resolved[key] = extracted[key]
        if extracted.get("description") and not resolved.get("description"):
            resolved["description"] = extracted["description"]

    # Even a failed fetch leaves the board slug, which is a far better company
    # name than "Unknown Company" - it is what the dedupe key is built from.
    if not str(resolved.get("company") or "").strip():
        resolved["company"] = guess_company_from_url(url) or ""
    return resolved


@router.post("/autopilot/enqueue")
def enqueue_job_for_autopilot(
    payload: dict[str, Any] = Body(default_factory=dict),
    db: Session = Depends(db_session),
) -> dict[str, Any]:
    from app.services.application_assistant.persistence import save_autopilot_job, is_duplicate_application
    from app.db.store import new_id, now_iso

    payload = _resolve_job_fields(payload)
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
        # Where the link came from, when it was an aggregator listing that got
        # resolved to the employer's board.
        "aggregatorUrl": payload.get("aggregatorUrl"),
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


@router.post("/autopilot/enqueue-batch")
def enqueue_jobs_for_autopilot(
    payload: dict[str, Any] = Body(default_factory=dict),
    db: Session = Depends(db_session),
) -> dict[str, Any]:
    """Queue many postings from their links alone.

    People collect job links in bulk - a dozen tabs, a list from a newsletter -
    and the details are already on the far end of every one of them, so the only
    thing worth asking for is the links. Each URL is resolved to its company,
    title and location, then run through exactly the same duplicate guard and
    hard filters as a single add, and every one gets its own outcome back so a
    posting that was filtered or already queued says so rather than vanishing.
    """
    import re as _re
    from concurrent.futures import ThreadPoolExecutor

    raw = payload.get("urls")
    if isinstance(raw, str):
        raw = [raw]
    if not isinstance(raw, list):
        raise HTTPException(status_code=400, detail="Expected 'urls' to be a list of job links.")

    # Accept a pasted block: newlines, spaces, commas, or a mix of them.
    urls: list[str] = []
    seen: set[str] = set()
    for entry in raw:
        for candidate in _re.split(r"[\s,]+", str(entry or "")):
            candidate = candidate.strip()
            if not candidate:
                continue
            if not candidate.lower().startswith(("http://", "https://")):
                continue
            if candidate in seen:
                continue
            seen.add(candidate)
            urls.append(candidate)

    if not urls:
        raise HTTPException(status_code=400, detail="No usable http(s) job links were found in that input.")
    if len(urls) > 50:
        raise HTTPException(status_code=400, detail=f"{len(urls)} links is more than the 50 this accepts at once.")

    tailoring_mode = payload.get("tailoringMode")

    # Resolution is a network fetch per link, so do those together rather than
    # one after another; the database writes below stay sequential on the single
    # request session.
    def _resolve(url: str) -> dict[str, Any]:
        return _resolve_job_fields({"applicationUrl": url, "tailoringMode": tailoring_mode})

    with ThreadPoolExecutor(max_workers=min(8, len(urls))) as pool:
        resolved = list(pool.map(_resolve, urls))

    results: list[dict[str, Any]] = []
    queued = 0
    for url, item in zip(urls, resolved):
        try:
            outcome = enqueue_job_for_autopilot(payload=item, db=db)
        except HTTPException:
            raise
        except Exception as exc:
            logger.exception("Could not queue %s", url)
            results.append({"url": url, "state": "error", "message": str(exc)[:200]})
            continue

        if outcome.get("deduplicated"):
            state = "duplicate"
        elif outcome.get("filtered") or outcome.get("success") is False:
            state = "filtered"
        else:
            state = "queued"
            queued += 1
        job = outcome.get("job") or {}
        results.append({
            "url": url,
            "state": state,
            "company": job.get("company") or item.get("company") or "",
            "title": job.get("title") or item.get("title") or "",
            "message": outcome.get("message") or "",
        })

    return {
        "success": True,
        "queued": queued,
        "total": len(urls),
        "results": results,
    }


@router.post("/autopilot/resolve-aggregator-urls")
def resolve_aggregator_urls(
    payload: dict[str, Any] = Body(default_factory=dict),
    db: Session = Depends(db_session),
) -> dict[str, Any]:
    """Repoint jobs stored at an aggregator listing to the employer's own board.

    Ingestion resolves these going forward, but rows queued before that are
    stuck at a URL with no application form on it. This walks the existing rows
    and fixes the ones whose posting can be found on a public board API.

    A row whose resolved URL already belongs to another application is retired
    as a duplicate rather than left as a second copy of the same posting.
    """
    from concurrent.futures import ThreadPoolExecutor

    from app.services.application_assistant.domain import IneligibilityReason
    from app.services.application_assistant.ineligibility import apply_ineligibility
    from app.services.application_assistant.persistence import (
        list_autopilot_jobs,
        save_autopilot_job,
    )
    from app.services.job_discover.aggregator_resolve import (
        is_aggregator_url,
        resolve_aggregator_url,
    )

    statuses = payload.get("statuses") or ["QUEUED", "MANUAL_REVIEW", "FAILED", "NEEDS_REVIEW"]
    wanted = {str(s).upper() for s in statuses}

    all_jobs = list_autopilot_jobs(db)
    targets = [
        j for j in all_jobs
        if str(j.get("status") or "").upper() in wanted
        and is_aggregator_url(str(j.get("applicationUrl") or ""))
    ]
    if not targets:
        return {"success": True, "examined": 0, "resolved": 0, "duplicates": 0, "unresolved": 0,
                "message": "No jobs are stored at an aggregator listing."}

    def _lookup(job: dict[str, Any]) -> tuple[dict[str, Any], dict[str, Any] | None]:
        try:
            return job, resolve_aggregator_url(
                str(job.get("applicationUrl") or ""),
                company_name=str(job.get("company") or ""),
                title=str(job.get("title") or ""),
            )
        except Exception:
            logger.exception("Aggregator resolve failed for %s", job.get("id"))
            return job, None

    with ThreadPoolExecutor(max_workers=8) as pool:
        results = list(pool.map(_lookup, targets))

    # URLs already spoken for, so a resolved row does not become a second copy.
    def _canon(url: str) -> str:
        return str(url or "").lower().split("?")[0].rstrip("/")

    taken = {
        _canon(j.get("applicationUrl")): j
        for j in all_jobs
        if j.get("applicationUrl") and not is_aggregator_url(str(j.get("applicationUrl")))
    }

    resolved = duplicates = 0
    details: list[dict[str, Any]] = []
    for job, found in results:
        if not found:
            continue
        new_url = found["applicationUrl"]
        existing = taken.get(_canon(new_url))
        if existing and existing.get("id") != job.get("id"):
            apply_ineligibility(
                job,
                IneligibilityReason.DUPLICATE_APPLICATION,
                f"The same posting is already tracked as {existing.get('status')} "
                f"({existing.get('id')}) once its aggregator link was resolved.",
            )
            save_autopilot_job(db, job)
            duplicates += 1
            details.append({"id": job["id"], "company": job.get("company"), "state": "duplicate"})
            continue

        job["aggregatorUrl"] = job.get("applicationUrl")
        job["applicationUrl"] = new_url
        if found.get("title"):
            job["title"] = found["title"]
        # The row was parked for a reason that no longer applies: it is now a
        # normal posting on a board the automation can drive.
        if str(job.get("status") or "").upper() != "QUEUED":
            job["status"] = "QUEUED"
            job["queuedAt"] = now_iso()
            job["attemptCount"] = 0
        job["hasPersistentBlock"] = False
        job["lastError"] = None
        job["lastErrorType"] = None
        job.pop("ineligibilityReason", None)
        job.pop("ineligibilityDetail", None)
        save_autopilot_job(db, job)
        taken[_canon(new_url)] = job
        resolved += 1
        details.append({"id": job["id"], "company": job.get("company"),
                        "state": "resolved", "url": new_url})

    unresolved = len(targets) - resolved - duplicates
    return {
        "success": True,
        "examined": len(targets),
        "resolved": resolved,
        "duplicates": duplicates,
        "unresolved": unresolved,
        "details": details[:60],
        "message": (
            f"Resolved {resolved} of {len(targets)} aggregator listings to the employer's board"
            + (f", retired {duplicates} as duplicates" if duplicates else "")
            + f". {unresolved} could not be found on a public board."
        ),
    }


@router.post("/autopilot/dedupe-applications")
def dedupe_applications(
    payload: dict[str, Any] = Body(default_factory=dict),
    db: Session = Depends(db_session),
) -> dict[str, Any]:
    """Collapse rows that are the same posting under the same URL.

    ``close_duplicate_applications`` already retires siblings the moment one
    record is submitted, but a posting that was re-discovered many times and
    never submitted keeps every copy. One Roblox posting had 34 rows, all
    carrying the same jobId, which made the Manual Review list read as 32
    different jobs when it held one.

    The survivor is the most advanced record - a submitted one always wins, then
    the one that got furthest - and ties break to the oldest so the original
    discovery is kept. Everything else is retired as a duplicate, which is a
    terminal bucket, so the lists the user works through stop repeating.
    """
    from app.services.application_assistant.domain import IneligibilityReason
    from app.services.application_assistant.ineligibility import apply_ineligibility
    from app.services.application_assistant.persistence import (
        canonical_application_url,
        list_autopilot_jobs,
        save_autopilot_job,
    )

    dry_run = bool(payload.get("dryRun"))

    # Most-finished first: the record that got furthest is the one worth keeping.
    RANK = {
        "SUBMITTED": 0, "APPLYING": 1, "NEEDS_REVIEW": 2, "STAGED": 2,
        "MANUAL_REVIEW": 3, "FAILED": 4, "QUEUED": 5, "SKIPPED": 6, "INELIGIBLE": 7,
    }

    groups: dict[str, list[dict[str, Any]]] = {}
    for job in list_autopilot_jobs(db):
        key = canonical_application_url(job.get("applicationUrl") or "")
        if not key:
            continue
        groups.setdefault(key, []).append(job)

    retired = 0
    collapsed = 0
    examples: list[dict[str, Any]] = []
    for key, rows in groups.items():
        # Already-retired duplicates are not worth reconsidering.
        live = [r for r in rows if r.get("ineligibilityReason") != "DUPLICATE_APPLICATION"]
        if len(live) < 2:
            continue
        live.sort(key=lambda r: (RANK.get(str(r.get("status") or "").upper(), 9),
                                 str(r.get("discoveredAt") or "")))
        keeper, extras = live[0], live[1:]
        collapsed += 1
        if len(examples) < 12:
            examples.append({
                "url": key[:110],
                "company": keeper.get("company"),
                "title": str(keeper.get("title") or "")[:60],
                "kept": keeper.get("status"),
                "retiring": len(extras),
            })
        if dry_run:
            retired += len(extras)
            continue
        for extra in extras:
            apply_ineligibility(
                extra,
                IneligibilityReason.DUPLICATE_APPLICATION,
                f"The same posting is tracked as {keeper.get('status')} ({keeper.get('id')}).",
            )
            save_autopilot_job(db, extra)
            retired += 1

    return {
        "success": True,
        "dryRun": dry_run,
        "duplicateGroups": collapsed,
        "retired": retired,
        "examples": examples,
        "message": (
            f"{'Would retire' if dry_run else 'Retired'} {retired} duplicate row(s) across "
            f"{collapsed} posting(s)."
            if collapsed else "No duplicate applications found."
        ),
    }


# Buckets the user may sweep back into the queue, and what each one actually
# covers. "review" and "failed" may be swept wholesale, with or without a
# company filter, as before.
#
# "manual", "skipped" and "ineligible" were originally excluded entirely: a
# wholesale sweep of any of them would refill the queue with jobs the user
# already worked through and dismissed for reasons an automated retry cannot
# resolve - a dead posting, a CAPTCHA, a hard ineligibility. They stay excluded
# from a *wholesale* sweep, but a company-scoped requeue is a different,
# deliberate action ("I just fixed the thing that misclassified every Roblox
# posting - send Roblox's specifically back"), so those three are requeuable
# only when the caller also names a `company` - enforced below, not by leaving
# them out of this map.
REQUEUABLE_BUCKETS: dict[str, tuple[str, ...]] = {
    "review": ("NEEDS_REVIEW", "STAGED"),
    "failed": ("FAILED",),
    "manual": ("MANUAL_REVIEW",),
    "skipped": ("SKIPPED",),
    "ineligible": ("INELIGIBLE",),
}

# Buckets whose wholesale (no company filter) sweep stays blocked - see comment above.
COMPANY_ONLY_BUCKETS = frozenset({"manual", "skipped", "ineligible"})


@router.post("/autopilot/requeue-bucket")
def requeue_bucket(
    payload: dict[str, Any] = Body(default_factory=dict),
    db: Session = Depends(db_session),
) -> dict[str, Any]:
    """Send applications in one bucket back to the queue.

    Used after a fix lands: the whole Review or Failed list (or, for Manual/
    Skipped/Ineligible, just one company's slice of it) is worth another
    attempt, and relabelling them one at a time through the side panel is not
    practical once there are dozens.

    This is destructive in one specific way the caller must warn about: the
    reason each job was parked - the question that needed answering, the error
    that broke the attempt - is cleared so the runner will pick it up again, and
    that record is not recoverable.
    """
    from app.services.application_assistant.persistence import (
        list_autopilot_jobs,
        save_autopilot_job,
    )

    bucket = str(payload.get("bucket") or "").strip().lower()
    if bucket not in REQUEUABLE_BUCKETS:
        raise HTTPException(
            status_code=400,
            detail=f"Unsupported bucket '{bucket}'. Allowed: {', '.join(REQUEUABLE_BUCKETS)}",
        )

    company = str(payload.get("company") or "").strip()
    if bucket in COMPANY_ONLY_BUCKETS and not company:
        raise HTTPException(
            status_code=400,
            detail=f"Requeuing the '{bucket}' bucket requires a company filter - "
            "filter to one company first.",
        )

    wanted = set(REQUEUABLE_BUCKETS[bucket])
    company_lower = company.lower()
    moved = 0
    for job in list_autopilot_jobs(db):
        if str(job.get("status") or "").upper() not in wanted:
            continue
        if company and str(job.get("company") or "").strip().lower() != company_lower:
            continue
        job["previousStatus"] = job.get("status")
        job["status"] = "QUEUED"
        job["queuedAt"] = now_iso()
        job["updatedAt"] = now_iso()
        job["stateSetBy"] = "user"
        job["attemptCount"] = 0
        # Everything that would keep the runner away from it has to go, or the
        # job sits in the queue and is skipped on every pass.
        job["hasPersistentBlock"] = False
        job["lastError"] = None
        job["lastErrorType"] = None
        job["skipReason"] = None
        job["submittedAt"] = None
        job["submissionSource"] = None
        job.pop("ineligibilityReason", None)
        job.pop("ineligibilityDetail", None)
        save_autopilot_job(db, job)
        moved += 1

    scope = f" from {company}" if company else ""
    return {
        "success": True,
        "bucket": bucket,
        "company": company or None,
        "moved": moved,
        "message": (
            f"Moved {moved} application{'' if moved == 1 else 's'}{scope} back to the queue."
            if moved else f"Nothing in that bucket{scope} to requeue."
        ),
    }


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


# Assisted hand-offs in flight, keyed by job id, so a second click does not open
# a second window onto the same posting.
_ASSISTED_RUNS: dict[str, asyncio.Task] = {}


async def _run_assisted_fill(job_id: str, job: dict[str, Any], profile: dict[str, Any],
                             answer_lib: list[dict[str, Any]], timeout_sec: float) -> None:
    """Fill the form, then sit with the open window until the candidate is done.

    Runs detached from the HTTP request on purpose. While this was awaited by the
    endpoint, the window's lifetime was capped by whichever timeout fired first -
    the browser's fetch abort, the Next proxy's 300s header timeout, or the
    server's own deadline - and the window was torn down mid-application. Nothing
    about how long a person needs to finish a form belongs to an HTTP request.
    """
    from app.db.store import now_iso, session_scope
    from app.services.application_assistant.persistence import get_autopilot_job, save_autopilot_job
    from app.services.application_assistant.playwright_autopilot_executor import (
        execute_live_playwright_submission,
    )

    def _record_submitted(evidence: dict[str, Any]) -> None:
        """Mark the job submitted. Called the instant a confirmation is seen."""
        with session_scope() as db:
            current = get_autopilot_job(db, job_id) or job
            if current.get("status") == "SUBMITTED":
                return
            current["previousStatus"] = current.get("status")
            current["status"] = "SUBMITTED"
            current["submittedAt"] = now_iso()
            current["submissionSource"] = "manual-assisted"
            current["hasPersistentBlock"] = False
            current["lastError"] = None
            current["answers"] = {
                **(current.get("answers") or {}),
                **(evidence.get("fieldsFilled") or {}),
            }
            current["submissionEvidence"] = {
                **(current.get("submissionEvidence") or {}),
                "confirmationText": "Confirmed on screen during assisted hand-off",
                "confirmationUrl": evidence.get("confirmationUrl") or "",
            }
            save_autopilot_job(db, current)
        logger.info("Assisted submission recorded immediately for %s", job_id)

    async def _on_confirmed(evidence: dict[str, Any]) -> None:
        # The hand-off loop runs on the browser thread's event loop, so the DB
        # write goes to a worker thread rather than blocking it.
        await asyncio.to_thread(_record_submitted, evidence)

    try:
        result = await execute_live_playwright_submission(
            job_item=job,
            profile=profile,
            answer_lib=answer_lib,
            # Always visible: the whole point is that a person finishes it.
            headless=False,
            timeout_sec=timeout_sec,
            fill_only=True,
            hand_off_seconds=ASSISTED_HANDOFF_SECONDS,
            # Persist the submission when it happens, not when the window
            # finally closes - the user expects the app to reflect what they
            # just did while they are still looking at it.
            on_confirmed=_on_confirmed,
        )
        filled = result.get("fieldsFilled") or {}
        if result.get("submitted"):
            with session_scope() as db:
                current = get_autopilot_job(db, job_id) or job
                current["previousStatus"] = current.get("status")
                current["status"] = "SUBMITTED"
                current["submittedAt"] = now_iso()
                current["submissionSource"] = "manual-assisted"
                current["hasPersistentBlock"] = False
                current["answers"] = {**(current.get("answers") or {}), **filled}
                current["submissionEvidence"] = result.get("evidence") or {}
                save_autopilot_job(db, current)
            logger.info("Assisted hand-off for %s ended in a submission", job_id)
        else:
            with session_scope() as db:
                current = get_autopilot_job(db, job_id)
                if current and filled:
                    current["answers"] = {**(current.get("answers") or {}), **filled}
                    save_autopilot_job(db, current)
            logger.info("Assisted hand-off window for %s closed without a submission", job_id)
    except Exception:
        logger.exception("Assisted fill failed for %s", job_id)
    finally:
        _ASSISTED_RUNS.pop(job_id, None)


@router.post("/autopilot/jobs/{id}/assisted-fill")
async def assisted_fill(id: str) -> dict[str, Any]:
    """Autofill this application in a visible browser and hand it to the user.

    For postings automation can reach but must not finish - a CAPTCHA guards the
    board, or a question only the candidate can answer. Everything the profile
    can answer gets typed in, then the window is left open so the person does
    only the part that actually needs them, instead of re-typing the whole form.

    Returns as soon as the hand-off starts. The window then stays open until the
    candidate closes it, with no time limit; if they submit, the job marks itself
    submitted on its own.
    """
    from app.db.store import get_kv, session_scope
    from app.services.application_assistant.persistence import (
        get_autopilot_job,
        get_settings,
        list_answer_library,
    )

    existing = _ASSISTED_RUNS.get(id)
    if existing and not existing.done():
        return {
            "success": True,
            "assisted": True,
            "submitted": False,
            "alreadyOpen": True,
            "message": "That application is already open in a browser window - finish it there.",
        }

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
    timeout_sec = float(browser_settings.get("timeout") or 60000) / 1000.0

    _ASSISTED_RUNS[id] = asyncio.create_task(
        _run_assisted_fill(id, job, profile, answer_lib, timeout_sec)
    )

    return {
        "success": True,
        "assisted": True,
        "submitted": False,
        "message": (
            f"Opening {job.get('company') or 'the application'} in a browser window and filling "
            "what we can. Take as long as you need - the window stays open until you close it, "
            "and it marks itself submitted if you submit."
        ),
    }


# What the user is allowed to set a job to from the side panel, and what each
# choice means on the job record. Only buckets a person can legitimately
# determine by opening the posting themselves are offered - nothing here lets
# them relabel a job the automation is still working.
USER_SETTABLE_STATES: dict[str, dict[str, Any]] = {
    "SUBMITTED": {"label": "Submitted - I applied myself"},
    # Putting a job back in the queue is the natural move once the reason it
    # was parked turns out to be wrong - a board reported as bot-protected that
    # actually loads fine, or a posting parked before a fix landed. Without
    # this the only way back was to re-add the URL by hand, which created a
    # duplicate rather than reviving the row.
    "QUEUED": {"label": "Queue it again - Autopilot should retry this"},
    "MANUAL_REVIEW": {"label": "Manual review - I need to finish this by hand"},
    "NEEDS_REVIEW": {"label": "Needs review - a question still needs answering"},
    "FAILED": {"label": "Failed - the attempt broke"},
    "INELIGIBLE": {
        "label": "Expired or broken link - nothing to apply to",
        "ineligibilityReason": "POSTING_EXPIRED",
    },
    "SKIPPED": {"label": "Skipped - not worth applying to"},
}

# The buckets whose jobs the user may relabel. A queued or in-flight job belongs
# to the automation; a submitted one is already recorded.
USER_RELABELLABLE_FROM = ("NEEDS_REVIEW", "STAGED", "FAILED", "MANUAL_REVIEW")


@router.get("/autopilot/job-states")
def list_user_settable_job_states() -> dict[str, Any]:
    """States the side panel may offer, and which buckets may be relabelled."""
    return {
        "success": True,
        "states": [
            {"value": value, "label": meta["label"]}
            for value, meta in USER_SETTABLE_STATES.items()
        ],
        "settableFrom": list(USER_RELABELLABLE_FROM),
    }


@router.post("/autopilot/jobs/{id}/set-state")
def set_autopilot_job_state(
    id: str,
    payload: dict[str, Any] = Body(default_factory=dict),
) -> dict[str, Any]:
    """Let the user record what actually happened with an application.

    Working these lists by hand turns up outcomes a submit-only button could not
    express - most often a posting that has expired or whose link is broken. The
    user is the one looking at the posting, so they are the authority on which
    bucket it belongs in.

    Restricted to jobs already in a bucket the user owns; a QUEUED job the
    automation still intends to try is not theirs to relabel.
    """
    from app.db.store import now_iso, session_scope
    from app.services.application_assistant.persistence import get_autopilot_job, save_autopilot_job

    requested = str(payload.get("status") or "").strip().upper()
    if requested not in USER_SETTABLE_STATES:
        raise HTTPException(
            status_code=400,
            detail=f"Unsupported state '{requested}'. Allowed: {', '.join(USER_SETTABLE_STATES)}",
        )

    with session_scope() as db:
        job = get_autopilot_job(db, id)
        if not job:
            raise HTTPException(status_code=404, detail="Application not found")

        current = job.get("status")
        if current not in USER_RELABELLABLE_FROM and current != requested:
            raise HTTPException(
                status_code=409,
                detail=(
                    f"A job in {current} cannot be relabelled here - only "
                    f"{', '.join(USER_RELABELLABLE_FROM)} jobs can."
                ),
            )

        meta = USER_SETTABLE_STATES[requested]
        job["previousStatus"] = current
        job["status"] = requested
        job["updatedAt"] = now_iso()
        job["stateSetBy"] = "user"

        if requested == "SUBMITTED":
            job["submittedAt"] = job.get("submittedAt") or now_iso()
            job["submissionSource"] = job.get("submissionSource") or "manual"
            job["hasPersistentBlock"] = False
            job["lastError"] = None
        elif requested == "QUEUED":
            # Everything that kept the runner away from this job has to go, or
            # it sits in the queue and is skipped every pass: the persistent
            # block flag, the ineligibility verdict, and the stale error that
            # would otherwise still describe it on the card.
            job["hasPersistentBlock"] = False
            job["lastError"] = None
            job["lastErrorType"] = None
            job["skipReason"] = None
            job["submittedAt"] = None
            job["submissionSource"] = None
            job["queuedAt"] = now_iso()
            job["attemptCount"] = 0
        else:
            # Leaving SUBMITTED means it was not actually sent.
            job["submittedAt"] = None
            job["submissionSource"] = None

        reason = meta.get("ineligibilityReason")
        if reason:
            job["ineligibilityReason"] = reason
            job["ineligibilityDetail"] = str(
                payload.get("note") or "Marked by you: posting expired or the link is broken"
            )
        elif requested != "INELIGIBLE":
            job.pop("ineligibilityReason", None)
            job.pop("ineligibilityDetail", None)

        note = str(payload.get("note") or "").strip()
        if note and requested != "INELIGIBLE":
            job["lastError"] = note

        saved = save_autopilot_job(db, job)
        return {"success": True, "job": saved}


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


