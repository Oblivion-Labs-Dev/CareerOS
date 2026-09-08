"""Application Assistant API routes — tailoring & receipts domain."""

from ._common import *  # noqa: F401,F403

router = APIRouter(prefix="/application-assistant", tags=["application-assistant"])


# ─── TSENTA SUITE: VISUAL DIFFS, PRE-FLIGHT APPROVAL, RECEIPTS & EMAIL SYNC ───

@router.get("/jobs/{id}/tailor-diff")
async def get_job_tailor_diff(id: str, mode: str | None = None) -> dict[str, Any]:
    """Generate or retrieve role-tailored materials with full visual diff chunks.

    No Depends(db_session): generate_role_tailoring_diff is an LLM call that can take
    tens of seconds, and holding a pooled connection for that span is unnecessary
    (see approve_preflight_submission for the pool-exhaustion this pattern caused).
    """
    from app.services.application_assistant.persistence import get_autopilot_job, get_settings
    from app.services.application_assistant.resume_diff_service import generate_role_tailoring_diff
    from app.db.store import get_kv, session_scope

    with session_scope() as db:
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


@router.get("/jobs/{id}/tailor-resume-pdf")
async def get_job_tailor_resume_pdf(id: str, mode: str | None = None) -> Response:
    """Export the tailored resume for a job as a formatted 1-page PDF document.

    No Depends(db_session) — see get_job_tailor_diff just above.
    """
    from app.services.application_assistant.persistence import get_autopilot_job, get_settings
    from app.services.application_assistant.resume_diff_service import (
        generate_role_tailoring_diff,
        render_tailored_resume_pdf,
    )
    from app.db.store import get_kv, session_scope

    with session_scope() as db:
        active_mode = mode or get_settings(db).get("tailoringMode", "honest")
        job = get_autopilot_job(db, id)
        if not job:
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
    pdf_bytes = render_tailored_resume_pdf(diff_data, profile)

    company_slug = "".join(c for c in job.get("company", "Role") if c.isalnum() or c in ("-", "_"))
    filename = f"Resume_{company_slug}_{active_mode.upper()}.pdf"

    return Response(
        content=pdf_bytes,
        media_type="application/pdf",
        headers={"Content-Disposition": f'inline; filename="{filename}"'},
    )


@router.post("/jobs/{id}/preflight-approve")
async def approve_preflight_submission(
    id: str,
    payload: dict[str, Any] = Body(default_factory=dict),
) -> dict[str, Any]:
    """Approve pre-flight tailored materials and enqueue job for cloud submission.

    Deliberately does NOT depend on the shared per-request DB session: the actual
    submission (runner.start, below) is a 45-150+ second live-browser-plus-model
    operation, and FastAPI holds a `Depends(db_session)` connection checked out of
    the pool for a request's entire lifetime. Doing that here — worse, once per
    duplicate/racing click — is what previously exhausted the SQLAlchemy connection
    pool and took the whole API down. The DB is only touched for the two quick
    reads/writes below, each in its own short-lived session.
    """
    from app.services.application_assistant.persistence import (
        claim_job_lock,
        get_autopilot_job,
        save_autopilot_job,
    )
    from app.services.application_assistant.autopilot_runner import AutopilotRunner
    from app.db.store import now_iso, session_scope

    with session_scope() as db:
        job = get_autopilot_job(db, id)
        if not job:
            raise HTTPException(status_code=404, detail="Application not found")

        if job.get("status") == "APPLYING" or not claim_job_lock(db, id, worker_id="preflight-approve"):
            return {
                "success": True,
                "message": f"{job.get('company')} is already being applied to — sit tight.",
                "job": job,
                "run": None,
            }

        job["status"] = "QUEUED"
        job["preflightApproved"] = True
        job["preflightApprovedAt"] = now_iso()
        job["lockedBy"] = None
        job["lockedAt"] = None
        job["lockExpiresAt"] = None
        if payload.get("customAnswers"):
            job["customAnswers"] = payload["customAnswers"]
        if payload.get("tailoringMode") in ("off", "honest", "aggressive"):
            job["tailoringMode"] = payload["tailoringMode"]
        save_autopilot_job(db, job)

    # start() below *resumes* an already-active run rather than guaranteeing this
    # job starts now — it only pushes the id onto priority_job_ids for whenever
    # the batch loop next claims work. Capture whether a run was already active so
    # the response can say which of those two things actually happened; reporting
    # "submission initiated" unconditionally previously made a job that never left
    # QUEUED look like it had been submitted.
    from app.services.application_assistant.persistence import get_active_autopilot_run

    with session_scope() as db:
        active_run = get_active_autopilot_run(db)
    queued_behind_active_run = bool(
        active_run and active_run.get("status") in ("RUNNING", "PAUSED", "RECOVERING")
    )

    runner = AutopilotRunner.get_instance()
    # concurrency=1 is deliberate: this is the single-job "Apply" click path, not
    # the bulk /autopilot/start runner. Without it, start() falls back to
    # DEFAULT_CONCURRENCY (5) and the batch loop picks up every other job already
    # sitting at QUEUED status too, silently turning one Apply click into a
    # 5-way-parallel headed-browser run — the exact concurrency blowup the memory-
    # constrained autopilot workflow must avoid.
    #
    # priorityJobId matters just as much: without it, the batch loop's queue
    # selection claims whichever QUEUED job happens to come first in
    # list_autopilot_jobs's order — not necessarily (or even usually) this one.
    # A user clicking "Apply" on job A would silently have job B processed
    # instead while A sits untouched, with no indication anything went wrong.
    run = await runner.start(options={"targetProcessCount": 1, "concurrency": 1, "priorityJobId": id})

    if queued_behind_active_run:
        message = (
            f"{job.get('company')} is queued next — Autopilot is already running, "
            "so it starts when the current job finishes."
        )
    else:
        message = f"Pre-flight approved for {job.get('company')} — cloud submission initiated."

    return {
        "success": True,
        "queuedBehindActiveRun": queued_behind_active_run,
        "message": message,
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





