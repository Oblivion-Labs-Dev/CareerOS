"""Fault-Tolerant Autopilot Application Runner Daemon for CareerOS."""

from __future__ import annotations

import asyncio
import logging
import os
import traceback
import uuid
from datetime import datetime, timezone
from typing import Any

from sqlalchemy.orm import Session

from app.db.store import new_id, now_iso, session_scope
from app.services.application_assistant.adapters import resolve_adapter
from app.services.application_assistant.domain import (
    ApplicationErrorType,
    AutopilotJobStatus,
    AutopilotRunStatus,
    CheckpointStep,
)
from app.services.application_assistant.job_filter_ranker import filter_and_rank_jobs
from app.services.application_assistant.persistence import (
    claim_job_lock,
    get_active_autopilot_run,
    get_autopilot_job,
    get_autopilot_run,
    list_autopilot_jobs,
    list_discovered_jobs,
    release_job_lock,
    save_autopilot_job,
    save_autopilot_run,
)
from app.services.application_assistant.structured_answer_engine import resolve_application_question


logger = logging.getLogger("career_os.autopilot_runner")

MAX_JOB_ATTEMPTS = 3
TRANSIENT_ERRORS = {
    ApplicationErrorType.NAVIGATION_TIMEOUT.value,
    ApplicationErrorType.NETWORK_ERROR.value,
    ApplicationErrorType.AI_TIMEOUT.value,
    ApplicationErrorType.BROWSER_CRASH.value,
    ApplicationErrorType.ELEMENT_NOT_FOUND.value,
    ApplicationErrorType.UPLOAD_ERROR.value,
}

class AutopilotRunner:
    _instance: AutopilotRunner | None = None

    def __init__(self) -> None:
        self.worker_id = f"worker_{uuid.uuid4().hex[:8]}"
        self.active_run_id: str | None = None
        self._stop_requested = False
        self._pause_requested = False
        self._loop_task: asyncio.Task | None = None
        self.activity_log: list[dict[str, Any]] = []

    @classmethod
    def get_instance(cls) -> AutopilotRunner:
        if cls._instance is None:
            cls._instance = AutopilotRunner()
        return cls._instance

    def log_event(self, message: str, level: str = "info", metadata: dict[str, Any] | None = None) -> None:
        entry = {
            "id": new_id("evt_"),
            "timestamp": now_iso(),
            "level": level,
            "message": message,
            "metadata": metadata or {},
        }
        self.activity_log.append(entry)
        if len(self.activity_log) > 300:
            self.activity_log.pop(0)

    async def start(self, db: Session | None = None, options: dict[str, Any] | None = None) -> dict[str, Any]:
        """Start or resume a fault-tolerant Autopilot run."""
        opts = options or {}
        target_count = int(opts.get("targetProcessCount") or opts.get("batchSize") or 25)

        saved_run: dict[str, Any] | None = None
        with session_scope() as local_db:
            existing = get_active_autopilot_run(local_db)
            if existing:
                status = existing.get("status")
                hb_str = existing.get("lastHeartbeatAt")
                if status in (AutopilotRunStatus.RUNNING.value, AutopilotRunStatus.PAUSED.value, AutopilotRunStatus.RECOVERING.value):
                    current_proc = existing.get("processedCount", 0)
                    existing["targetProcessCount"] = max(existing.get("targetProcessCount", 25), current_proc + target_count)
                    existing["status"] = AutopilotRunStatus.RUNNING.value
                    self.active_run_id = existing["id"]
                    if hb_str:
                        try:
                            hb_dt = datetime.fromisoformat(hb_str.replace("Z", "+00:00"))
                            now_dt = datetime.now(timezone.utc)
                            if (now_dt - hb_dt).total_seconds() > 60:
                                self.log_event("Stale heartbeat detected — entering RECOVERING mode", level="warning")
                                existing["status"] = AutopilotRunStatus.RECOVERING.value
                                save_autopilot_run(local_db, existing)
                                self._recover_stale_run_sync(existing)
                        except Exception:
                            pass
                    saved_run = save_autopilot_run(local_db, existing)
                    self._stop_requested = False
                    self._pause_requested = False
                    if self._loop_task is None or self._loop_task.done():
                        self._loop_task = asyncio.create_task(self._run_batch_worker())
                    return saved_run

            self._stop_requested = False
            self._pause_requested = False

            run_id = new_id("aprun_")
            run_payload = {
                "id": run_id,
                "targetProcessCount": target_count,
                "processedCount": 0,
                "submittedCount": 0,
                "stagedCount": 0,
                "skippedCount": 0,
                "failedCount": 0,
                "status": AutopilotRunStatus.RUNNING.value,
                "startedAt": now_iso(),
                "completedAt": None,
                "stoppedAt": None,
                "lastHeartbeatAt": now_iso(),
                "settings": opts,
            }
            saved_run = save_autopilot_run(local_db, run_payload)
            self.active_run_id = run_id

        self.log_event(f"Autopilot run started (Target batch: {target_count} jobs)", level="info", metadata={"runId": self.active_run_id})

        if self._loop_task is None or self._loop_task.done():
            self._loop_task = asyncio.create_task(self._run_batch_worker())

        return saved_run or {}

    async def pause(self, db: Session | None = None) -> dict[str, Any] | None:
        self._pause_requested = True
        if self.active_run_id:
            with session_scope() as local_db:
                run = get_autopilot_run(local_db, self.active_run_id)
                if run:
                    run["status"] = AutopilotRunStatus.PAUSED.value
                    run["lastHeartbeatAt"] = now_iso()
                    saved = save_autopilot_run(local_db, run)
                    self.log_event("Autopilot run paused", level="info")
                    return saved
        return None

    async def stop(self, db: Session | None = None) -> dict[str, Any] | None:
        self._stop_requested = True
        if self.active_run_id:
            with session_scope() as local_db:
                run = get_autopilot_run(local_db, self.active_run_id)
                if run:
                    run["status"] = AutopilotRunStatus.STOPPED.value
                    run["stoppedAt"] = now_iso()
                    run["lastHeartbeatAt"] = now_iso()
                    saved = save_autopilot_run(local_db, run)
                    self.log_event("Autopilot run stopped gracefully", level="info")
                    return saved
        return None

    def get_status(self, db: Session) -> dict[str, Any]:
        active_run = (get_autopilot_run(db, self.active_run_id) if self.active_run_id else None) or get_active_autopilot_run(db)
        if active_run and not self.active_run_id:
            self.active_run_id = active_run["id"]
        jobs = list_autopilot_jobs(db)
        submitted_jobs = [j for j in jobs if j.get("status") == AutopilotJobStatus.SUBMITTED.value]
        staged_jobs = [j for j in jobs if j.get("status") in (AutopilotJobStatus.STAGED.value, "NEEDS_REVIEW")]
        skipped_jobs = [j for j in jobs if j.get("status") == AutopilotJobStatus.SKIPPED.value]
        failed_jobs = [j for j in jobs if j.get("status") in (AutopilotJobStatus.FAILED.value, "ERROR")]
        queued_jobs = [j for j in jobs if j.get("status") in (AutopilotJobStatus.QUEUED.value, AutopilotJobStatus.APPLYING.value)]
        processed_total = len(submitted_jobs) + len(staged_jobs) + len(skipped_jobs) + len(failed_jobs)

        cumulative = {
            "submitted": len(submitted_jobs),
            "staged": len(staged_jobs),
            "skipped": len(skipped_jobs),
            "failed": len(failed_jobs),
            "processed": processed_total,
            "queueRemaining": len(queued_jobs),
        }

        persisted_logs = active_run.get("logs") if active_run else []
        log_dict = {l.get("id"): l for l in (persisted_logs or []) + self.activity_log if isinstance(l, dict) and l.get("id")}
        combined_logs = sorted(list(log_dict.values()), key=lambda l: l.get("timestamp", ""))

        if not active_run:
            return {
                "running": False,
                "status": AutopilotRunStatus.STOPPED.value,
                "run": None,
                "cumulative": cumulative,
                "activeJob": None,
                "queueSize": len(queued_jobs),
                "recentLogs": combined_logs[-25:],
            }

        current_job = None
        if active_run.get("currentJobId"):
            current_job = get_autopilot_job(db, active_run["currentJobId"])

        return {
            "running": active_run.get("status") in (AutopilotRunStatus.RUNNING.value, AutopilotRunStatus.RECOVERING.value),
            "status": active_run.get("status"),
            "run": active_run,
            "cumulative": cumulative,
            "activeJob": current_job,
            "queueSize": len(queued_jobs),
            "recentLogs": combined_logs[-25:],
        }

    def _recover_stale_run_sync(self, run: dict[str, Any]) -> None:
        """Inspect previous active job, release stale locks, and recover batch run."""
        with session_scope() as db:
            current_job_id = run.get("currentJobId")
            if current_job_id:
                job = get_autopilot_job(db, current_job_id)
                if job and job.get("status") == AutopilotJobStatus.APPLYING.value:
                    history = job.get("checkpointHistory") or []
                    last_step = history[-1].get("step") if history else ""
                    if last_step in (CheckpointStep.SUBMITTING.value, CheckpointStep.VERIFYING_SUBMISSION.value):
                        job["status"] = AutopilotJobStatus.STAGED.value
                        job["lastErrorType"] = ApplicationErrorType.SUBMISSION_UNCERTAIN.value
                        job["aiExplanation"] = "Interrupted during submit — staged as SUBMISSION_UNCERTAIN to prevent duplicates"
                        save_autopilot_job(db, job)
                        run["stagedCount"] = (run.get("stagedCount") or 0) + 1
                    else:
                        job["status"] = AutopilotJobStatus.QUEUED.value
                        save_autopilot_job(db, job)
                    release_job_lock(db, current_job_id, self.worker_id)

            run["status"] = AutopilotRunStatus.RUNNING.value
            run["currentJobId"] = None
            save_autopilot_run(db, run)
            self.log_event("Batch run recovered successfully", level="info")

    async def _run_batch_worker(self) -> None:
        """Worker-Level Error Boundary protecting overall batch worker execution."""
        try:
            await self._process_batch_loop()
        except Exception as fatal_error:
            self.log_event(f"Fatal worker infrastructure error: {fatal_error}", level="error")
            try:
                with session_scope() as db:
                    if self.active_run_id:
                        run = get_autopilot_run(db, self.active_run_id)
                        if run:
                            run["status"] = AutopilotRunStatus.PAUSED.value
                            save_autopilot_run(db, run)
            except Exception:
                pass

    async def _process_batch_loop(self) -> None:
        """Main Batch Loop with non-blocking, isolated database transactions."""
        while not self._stop_requested:
            if self._pause_requested:
                await asyncio.sleep(2)
                continue

            # 1. Fetch active run in short transaction scope
            run: dict[str, Any] | None = None
            with session_scope() as db:
                run = (get_autopilot_run(db, self.active_run_id) if self.active_run_id else None) or get_active_autopilot_run(db)

            if not run or run.get("status") not in (AutopilotRunStatus.RUNNING.value, AutopilotRunStatus.RECOVERING.value):
                self.log_event(f"Batch worker idle — active run status is '{run.get('status') if run else 'NONE'}'", level="info")
                break

            target_count = run.get("targetProcessCount", 25)
            processed_count = run.get("processedCount", 0)

            if processed_count >= target_count:
                with session_scope() as db:
                    r = get_autopilot_run(db, run["id"])
                    if r:
                        r["status"] = AutopilotRunStatus.COMPLETED.value
                        r["completedAt"] = now_iso()
                        r["currentJobId"] = None
                        save_autopilot_run(db, r)
                self.log_event(f"Batch completed: {processed_count} of {target_count} jobs processed!", level="info")
                break

            # Heartbeat update
            with session_scope() as db:
                r = get_autopilot_run(db, run["id"])
                if r:
                    r["lastHeartbeatAt"] = now_iso()
                    r["logs"] = self.activity_log[-100:]
                    save_autopilot_run(db, r)

            # 2. Fetch and auto-enqueue queued jobs
            target_job: dict[str, Any] | None = None
            queued: list[dict[str, Any]] = []
            existing_autopilot_jobs: list[dict[str, Any]] = []
            profile: dict[str, Any] = {}
            raw_jobs: list[dict[str, Any]] = []
            with session_scope() as db:
                from app.db.store import get_kv
                existing_autopilot_jobs = list_autopilot_jobs(db)
                queued = [j for j in existing_autopilot_jobs if j.get("status") in (AutopilotJobStatus.QUEUED.value, AutopilotJobStatus.APPLYING.value)]
                if not queued:
                    profile = get_kv(db, "profile") or {}
                    raw_jobs = list_discovered_jobs(db, active_only=True, exclude_demo=True)

            if not queued:
                self.log_event("Scanning discovered job postings for eligible matches...", level="info")
                ranked = filter_and_rank_jobs(existing_autopilot_jobs, raw_jobs, profile, run.get("settings")) if raw_jobs else []

                if ranked:
                    self.log_event(f"Selected {len(ranked)} eligible job postings matching target criteria", level="info")
                    with session_scope() as db:
                        for r in ranked:
                            save_autopilot_job(db, {
                                "id": new_id("apjob_"),
                                "jobId": r.get("id") or new_id("job_"),
                                "company": r.get("company"),
                                "title": r.get("title"),
                                "applicationUrl": r.get("applicationUrl") or r.get("listingUrl") or "",
                                "status": AutopilotJobStatus.QUEUED.value,
                                "matchScore": r.get("matchScore", 85.0),
                                "matchReasons": r.get("matchReasons", []),
                                "discoveredAt": now_iso(),
                                "queuedAt": now_iso(),
                            })
                        jobs = list_autopilot_jobs(db)
                        queued = [j for j in jobs if j.get("status") in (AutopilotJobStatus.QUEUED.value, AutopilotJobStatus.APPLYING.value)]
                else:
                    self.log_event("No new unapplied job postings found in database.", level="info")

            if queued:
                cand = queued[0]
                with session_scope() as db:
                    if claim_job_lock(db, cand["id"], self.worker_id):
                        target_job = cand
                        r = get_autopilot_run(db, run["id"])
                        if r:
                            r["currentJobId"] = cand["id"]
                            r["currentCompany"] = cand.get("company")
                            r["currentJobTitle"] = cand.get("title")
                            r["lastAction"] = f"Processing {cand.get('company')} — {cand.get('title')}"
                            save_autopilot_run(db, r)

            if not target_job:
                self.log_event("No more eligible jobs in queue — batch run completed.", level="info")
                with session_scope() as db:
                    r = get_autopilot_run(db, run["id"])
                    if r:
                        r["status"] = AutopilotRunStatus.COMPLETED.value
                        r["completedAt"] = now_iso()
                        r["currentJobId"] = None
                        save_autopilot_run(db, r)
                break

            job_id = target_job["id"]

            # 3. Process Job Execution Boundary
            try:
                await self._process_single_job_with_retries(run["id"], target_job)
            except Exception as unhandled_job_error:
                self._handle_unhandled_job_exception_sync(run["id"], target_job, unhandled_job_error)
            finally:
                with session_scope() as db:
                    release_job_lock(db, job_id, self.worker_id)
                    r = get_autopilot_run(db, run["id"])
                    if r:
                        r["processedCount"] = (r.get("processedCount") or 0) + 1
                        r["currentJobId"] = None
                        save_autopilot_run(db, r)

            await asyncio.sleep(1.5)

    def _record_checkpoint(self, job_item: dict[str, Any], step: CheckpointStep, details: str = "") -> None:
        if "checkpointHistory" not in job_item or job_item["checkpointHistory"] is None:
            job_item["checkpointHistory"] = []
        job_item["checkpointHistory"].append({
            "step": step.value,
            "timestamp": now_iso(),
            "details": details,
        })
        job_item["currentStep"] = step.value

    async def _process_single_job_with_retries(
        self, run_id: str, job_item: dict[str, Any]
    ) -> None:
        attempt = (job_item.get("attemptCount") or 0) + 1
        job_item["attemptCount"] = attempt
        self._record_checkpoint(job_item, CheckpointStep.JOB_CLAIMED, f"Attempt {attempt}/{MAX_JOB_ATTEMPTS}")
        with session_scope() as db:
            save_autopilot_job(db, job_item)

        try:
            await self._execute_application_pipeline(run_id, job_item)
        except Exception as exc:
            err_type = self._classify_error(exc)

            if err_type in TRANSIENT_ERRORS and attempt < MAX_JOB_ATTEMPTS:
                delay = 2 if attempt == 1 else 5
                self.log_event(f"Transient error ({err_type}). Retrying attempt {attempt + 1} after {delay}s...", level="warning")
                await asyncio.sleep(delay)
                return await self._process_single_job_with_retries(run_id, job_item)

            job_item["status"] = AutopilotJobStatus.FAILED.value
            job_item["lastError"] = str(exc)
            job_item["lastErrorType"] = err_type
            job_item["aiExplanation"] = f"Failed due to error: {err_type} ({exc})"
            self._record_checkpoint(job_item, CheckpointStep.FAILED, f"Failed on error: {err_type}")
            with session_scope() as db:
                save_autopilot_job(db, job_item)
                r = get_autopilot_run(db, run_id)
                if r:
                    r["failedCount"] = (r.get("failedCount") or 0) + 1
                    save_autopilot_run(db, r)

            self.log_event(f"Application failed ({err_type}): {job_item.get('company')} — {job_item.get('title')}", level="error")

    def _classify_error(self, exc: Exception) -> str:
        msg = str(exc).lower()
        if "timeout" in msg:
            return ApplicationErrorType.NAVIGATION_TIMEOUT.value
        if "network" in msg or "connection" in msg:
            return ApplicationErrorType.NETWORK_ERROR.value
        if "captcha" in msg:
            return ApplicationErrorType.CAPTCHA.value
        if "auth" in msg or "login" in msg:
            return ApplicationErrorType.AUTH_REQUIRED.value
        if "element" in msg or "not found" in msg:
            return ApplicationErrorType.ELEMENT_NOT_FOUND.value
        if "browser" in msg or "crash" in msg:
            return ApplicationErrorType.BROWSER_CRASH.value
        if "ai" in msg or "ollama" in msg or "llm" in msg:
            return ApplicationErrorType.AI_TIMEOUT.value
        return ApplicationErrorType.UNKNOWN_ERROR.value

    async def _execute_application_pipeline(
        self, run_id: str, job_item: dict[str, Any]
    ) -> None:
        company = job_item.get("company") or "Unknown"
        title = job_item.get("title") or "Unknown"
        app_url = job_item.get("applicationUrl") or ""

        self.log_event(f"Processing job: {company} — {title} (Match Score: {job_item.get('matchScore', 85)}%)", level="info")
        await asyncio.sleep(0.8)

        # Step: PAGE_OPENED
        job_item["status"] = AutopilotJobStatus.APPLYING.value
        job_item["applicationStartedAt"] = now_iso()
        self._record_checkpoint(job_item, CheckpointStep.PAGE_OPENED, f"Opened {app_url}")
        with session_scope() as db:
            save_autopilot_job(db, job_item)

        self.log_event(f"Opened application page for {company}...", level="info")
        await asyncio.sleep(0.8)

        # Step: FORM_DISCOVERED & LIVE PLAYWRIGHT SUBMISSION
        from app.db.store import get_kv
        from app.services.application_assistant.persistence import list_answer_library
        profile: dict[str, Any] = {}
        answer_lib: list[dict[str, Any]] = []
        with session_scope() as db:
            profile = get_kv(db, "profile") or {}
            answer_lib = list_answer_library(db)

        self.log_event(f"Launching Playwright live Chromium session for {company}...", level="info")
        self._record_checkpoint(job_item, CheckpointStep.FORM_DISCOVERED, "Navigating via Chromium")
        with session_scope() as db:
            save_autopilot_job(db, job_item)

        from app.services.application_assistant.playwright_autopilot_executor import execute_live_playwright_submission

        headless_mode = os.environ.get("AA_HEADLESS", "true").lower() in ("true", "1")

        self.log_event(f"Inspecting form DOM, attaching resume & filling fields for {company}...", level="info")
        self._record_checkpoint(job_item, CheckpointStep.QUESTIONS_COMPLETED, "Resolving form fields")

        result = await execute_live_playwright_submission(
            job_item=job_item,
            profile=profile,
            answer_lib=answer_lib,
            headless=headless_mode,
            timeout_sec=60.0,
        )

        if result.get("submitted"):
            job_item["status"] = AutopilotJobStatus.SUBMITTED.value
            job_item["submittedAt"] = now_iso()
            job_item["submissionEvidence"] = result.get("evidence", {})
            job_item["answers"] = result.get("fieldsFilled", {})
            self._record_checkpoint(job_item, CheckpointStep.SUBMITTED, "Real browser submission confirmed")
            with session_scope() as db:
                save_autopilot_job(db, job_item)
                r = get_autopilot_run(db, run_id)
                if r:
                    r["submittedCount"] = (r.get("submittedCount") or 0) + 1
                    save_autopilot_run(db, r)
            self.log_event(f"Successfully submitted real application for {company} — {title} 🎉 (Proof captured)", level="info")
        else:
            err_msg = result.get("error") or "Submission unconfirmed"
            job_item["status"] = AutopilotJobStatus.FAILED.value
            job_item["lastError"] = err_msg
            job_item["submissionEvidence"] = result.get("evidence", {})
            job_item["aiExplanation"] = err_msg
            self._record_checkpoint(job_item, CheckpointStep.FAILED, f"Failed: {err_msg}")
            with session_scope() as db:
                save_autopilot_job(db, job_item)
                r = get_autopilot_run(db, run_id)
                if r:
                    r["failedCount"] = (r.get("failedCount") or 0) + 1
                    save_autopilot_run(db, r)
            self.log_event(f"Application failed ({company}): {err_msg}", level="error")


    def _handle_unhandled_job_exception_sync(
        self, run_id: str, job_item: dict[str, Any], exc: Exception
    ) -> None:
        """Top-Level Exception Boundary ensuring no unhandled exception can crash the batch worker."""
        self.log_event(f"Unhandled automation error on {job_item.get('company')}: {exc}", level="error")

        job_item["status"] = AutopilotJobStatus.FAILED.value
        job_item["lastError"] = str(exc)
        job_item["lastErrorType"] = ApplicationErrorType.UNKNOWN_ERROR.value
        job_item["aiExplanation"] = f"Automation error: {exc}"
        self._record_checkpoint(job_item, CheckpointStep.FAILED, f"Unhandled exception: {exc}")
        with session_scope() as db:
            save_autopilot_job(db, job_item)
            r = get_autopilot_run(db, run_id)
            if r:
                r["failedCount"] = (r.get("failedCount") or 0) + 1
                save_autopilot_run(db, r)
