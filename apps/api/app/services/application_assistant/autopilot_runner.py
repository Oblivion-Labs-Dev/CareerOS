"""Fault-Tolerant Autopilot Application Runner Daemon for CareerOS.

Supports N concurrent browser workers with per-worker status tracking,
concurrency metrics, and a batch-end self-healing cycle powered by Qwen.
"""

from __future__ import annotations

import asyncio
import logging
import os
import time
import traceback
import uuid
from dataclasses import dataclass, field
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
DEFAULT_CONCURRENCY = 5
# Launches are staggered just enough to avoid a burst of browser startups.  The
# former three-second default left most worker slots idle at the start of every
# batch without improving form reliability.
DEFAULT_STAGGER_DELAY = 0.5

TRANSIENT_ERRORS = {
    ApplicationErrorType.NAVIGATION_TIMEOUT.value,
    ApplicationErrorType.NETWORK_ERROR.value,
    ApplicationErrorType.AI_TIMEOUT.value,
    ApplicationErrorType.BROWSER_CRASH.value,
    ApplicationErrorType.ELEMENT_NOT_FOUND.value,
    ApplicationErrorType.UPLOAD_ERROR.value,
}


@dataclass
class WorkerState:
    """Per-worker status for frontend display."""
    worker_id: str
    slot: int
    status: str = "idle"  # idle | claiming | applying | filling | submitting | done | error
    current_job: dict[str, Any] | None = None
    current_step: str = ""
    started_at: str = ""
    error: str = ""
    jobs_completed: int = 0
    jobs_failed: int = 0

    def to_dict(self) -> dict[str, Any]:
        job_info = None
        if self.current_job:
            job_info = {
                "id": self.current_job.get("id"),
                "company": self.current_job.get("company"),
                "title": self.current_job.get("title"),
            }
        return {
            "workerId": self.worker_id,
            "slot": self.slot,
            "status": self.status,
            "currentJob": job_info,
            "currentStep": self.current_step,
            "startedAt": self.started_at,
            "error": self.error,
            "jobsCompleted": self.jobs_completed,
            "jobsFailed": self.jobs_failed,
        }


@dataclass
class ConcurrencyMetrics:
    """Concurrency performance metrics."""
    total_jobs_started: int = 0
    total_jobs_finished: int = 0
    total_job_time_sec: float = 0.0
    lock_contention_count: int = 0
    self_healing_rounds_completed: int = 0
    batch_start_time: float = 0.0

    @property
    def avg_job_time_sec(self) -> float:
        return self.total_job_time_sec / max(1, self.total_jobs_finished)

    @property
    def throughput_per_min(self) -> float:
        elapsed = time.time() - self.batch_start_time if self.batch_start_time else 1
        return (self.total_jobs_finished / max(1, elapsed)) * 60

    def to_dict(self, active_count: int, total_slots: int) -> dict[str, Any]:
        return {
            "activeWorkers": active_count,
            "totalWorkers": total_slots,
            "avgJobTimeSec": round(self.avg_job_time_sec, 1),
            "throughputPerMin": round(self.throughput_per_min, 2),
            "lockContentionCount": self.lock_contention_count,
            "selfHealingRoundsCompleted": self.self_healing_rounds_completed,
            "totalJobsStarted": self.total_jobs_started,
            "totalJobsFinished": self.total_jobs_finished,
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
        self._subscribers: set[asyncio.Queue[dict[str, Any]]] = set()

        # ── Concurrency state ──
        self.concurrency: int = DEFAULT_CONCURRENCY
        self.stagger_delay: float = DEFAULT_STAGGER_DELAY
        self.self_healing_enabled: bool = True
        self.worker_states: dict[int, WorkerState] = {}
        self.metrics = ConcurrencyMetrics()

    @classmethod
    def get_instance(cls) -> AutopilotRunner:
        if cls._instance is None:
            cls._instance = AutopilotRunner()
        return cls._instance

    def subscribe_events(self) -> asyncio.Queue[dict[str, Any]]:
        """Subscribe to real-time push events via Server-Sent Events (SSE)."""
        queue: asyncio.Queue[dict[str, Any]] = asyncio.Queue(maxsize=100)
        self._subscribers.add(queue)
        return queue

    def unsubscribe_events(self, queue: asyncio.Queue[dict[str, Any]]) -> None:
        """Unsubscribe an SSE client queue."""
        self._subscribers.discard(queue)

    def _broadcast(self, event_type: str, data: Any) -> None:
        """Push real-time SSE payload to all connected frontend listeners."""
        payload = {"event": event_type, "data": data, "timestamp": now_iso()}
        dead_queues = []
        for q in list(self._subscribers):
            try:
                if q.full():
                    try:
                        q.get_nowait()
                    except Exception:
                        pass
                q.put_nowait(payload)
            except Exception:
                dead_queues.append(q)
        for dq in dead_queues:
            self._subscribers.discard(dq)

    def log_event(self, message: str, level: str = "info", metadata: dict[str, Any] | None = None) -> None:
        entry = {
            "id": new_id("evt_"),
            "timestamp": now_iso(),
            "level": level,
            "message": message,
            "metadata": metadata or {},
        }
        self.activity_log.append(entry)
        if len(self.activity_log) > 500:
            self.activity_log.pop(0)

        # Real-time SSE push
        self._broadcast("log", entry)

    async def start(self, options: dict[str, Any] | None = None, db: Session | None = None, **kwargs: Any) -> dict[str, Any]:
        """Start or resume a fault-tolerant Autopilot run."""
        # Normalize positional / keyword options
        if isinstance(options, Session):
            local_session = options
            opts = kwargs.get("options") or db or {}
        else:
            opts = options or kwargs.get("options") or {}
        target_count = int(opts.get("targetProcessCount") or opts.get("batchSize") or 25)

        # Configure concurrency from options
        self.concurrency = max(1, min(10, int(opts.get("concurrency") or DEFAULT_CONCURRENCY)))
        self.stagger_delay = float(opts.get("staggerDelay") or DEFAULT_STAGGER_DELAY)
        self.self_healing_enabled = bool(opts.get("selfHealing", True))

        # Initialize worker states
        self.worker_states = {
            slot: WorkerState(
                worker_id=f"{self.worker_id}_slot{slot}",
                slot=slot,
            )
            for slot in range(self.concurrency)
        }
        self.metrics = ConcurrencyMetrics()

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
                    existing["concurrency"] = self.concurrency
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
                        logger.info("Resuming _run_batch_worker for existing run %s (concurrency=%d)...", existing.get("id"), self.concurrency)
                        self._loop_task = asyncio.create_task(self._run_batch_worker())
                        def _log_task_done_existing(t: asyncio.Task) -> None:
                            if not t.cancelled() and t.exception():
                                logger.error("Autopilot batch worker crashed on resume with: %s", t.exception(), exc_info=t.exception())
                        self._loop_task.add_done_callback(_log_task_done_existing)
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
                "concurrency": self.concurrency,
            }
            saved_run = save_autopilot_run(local_db, run_payload)
            self.active_run_id = run_id

        self.log_event(
            f"Autopilot run started (Target batch: {target_count} jobs, Concurrency: {self.concurrency} workers)",
            level="info",
            metadata={"runId": self.active_run_id, "concurrency": self.concurrency},
        )

        if self._loop_task is None or self._loop_task.done():
            logger.info("Spawning new _run_batch_worker asyncio task for run %s (concurrency=%d)...", self.active_run_id, self.concurrency)
            self._loop_task = asyncio.create_task(self._run_batch_worker())
            def _log_task_done(t: asyncio.Task) -> None:
                if not t.cancelled() and t.exception():
                    logger.error("Autopilot batch worker crashed with: %s", t.exception(), exc_info=t.exception())
            self._loop_task.add_done_callback(_log_task_done)

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

        # Build per-worker state for frontend
        workers_list = [ws.to_dict() for ws in self.worker_states.values()]
        active_worker_count = sum(1 for ws in self.worker_states.values() if ws.status not in ("idle", "done"))

        # Self-healing state
        from app.services.application_assistant.autopilot_self_healer import get_self_healing_state
        heal_state = get_self_healing_state().to_dict()

        if not active_run:
            return {
                "running": False,
                "status": AutopilotRunStatus.STOPPED.value,
                "run": None,
                "cumulative": cumulative,
                "activeJob": None,
                "queueSize": len(queued_jobs),
                "recentLogs": combined_logs[-25:],
                "workers": workers_list,
                "concurrency": self.concurrency,
                "concurrencyMetrics": self.metrics.to_dict(active_worker_count, self.concurrency),
                "selfHealing": heal_state,
            }

        current_job = None
        if active_run.get("currentJobId"):
            current_job = get_autopilot_job(db, active_run["currentJobId"])
        if not current_job:
            for ws in self.worker_states.values():
                if ws.current_job:
                    current_job = ws.current_job
                    break

        return {
            "running": active_run.get("status") in (AutopilotRunStatus.RUNNING.value, AutopilotRunStatus.RECOVERING.value),
            "status": active_run.get("status"),
            "run": active_run,
            "cumulative": cumulative,
            "activeJob": current_job,
            "queueSize": len(queued_jobs),
            "recentLogs": combined_logs[-25:],
            "workers": workers_list,
            "concurrency": self.concurrency,
            "concurrencyMetrics": self.metrics.to_dict(active_worker_count, self.concurrency),
            "selfHealing": heal_state,
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
            logger.info("Batch worker loop starting (concurrency=%d)...", self.concurrency)
            await self._process_batch_loop()
            logger.info("Batch worker loop exited normally.")
        except Exception as fatal_error:
            tb = traceback.format_exc()
            logger.error("Fatal worker infrastructure error:\n%s", tb)
            self.log_event(f"Fatal worker infrastructure error: {fatal_error}", level="error", metadata={"traceback": tb})
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
        """Main Batch Loop with N concurrent workers using asyncio.Semaphore."""
        self.metrics.batch_start_time = time.time()
        semaphore = asyncio.Semaphore(self.concurrency)

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
                await self._trigger_post_batch_self_healing(run["id"])
                break

            # Heartbeat update
            with session_scope() as db:
                r = get_autopilot_run(db, run["id"])
                if r:
                    r["lastHeartbeatAt"] = now_iso()
                    r["logs"] = self.activity_log[-100:]
                    save_autopilot_run(db, r)

            # 2. Fetch and auto-enqueue queued jobs
            queued: list[dict[str, Any]] = []
            with session_scope() as db:
                from app.db.store import get_kv
                existing_autopilot_jobs = list_autopilot_jobs(db)
                queued = [j for j in existing_autopilot_jobs if j.get("status") in (AutopilotJobStatus.QUEUED.value, AutopilotJobStatus.APPLYING.value)]
                if not queued:
                    profile = get_kv(db, "profile") or {}
                    raw_jobs = list_discovered_jobs(db, active_only=True, exclude_demo=True)

            if not queued:
                self.log_event("Scanning discovered job postings for eligible matches...", level="info")
                with session_scope() as db:
                    from app.db.store import get_kv
                    existing_autopilot_jobs = list_autopilot_jobs(db)
                    profile = get_kv(db, "profile") or {}
                    raw_jobs = list_discovered_jobs(db, active_only=True, exclude_demo=True)
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

            if not queued:
                self.log_event("No more eligible jobs in queue — batch run completed.", level="info")
                with session_scope() as db:
                    r = get_autopilot_run(db, run["id"])
                    if r:
                        r["status"] = AutopilotRunStatus.COMPLETED.value
                        r["completedAt"] = now_iso()
                        r["currentJobId"] = None
                        save_autopilot_run(db, r)
                await self._trigger_post_batch_self_healing(run["id"])
                break

            # 3. Claim up to N jobs concurrently
            claimed_jobs: list[dict[str, Any]] = []
            with session_scope() as db:
                for cand in queued:
                    if len(claimed_jobs) >= self.concurrency:
                        break
                    if claim_job_lock(db, cand["id"], self.worker_id):
                        claimed_jobs.append(cand)
                    else:
                        self.metrics.lock_contention_count += 1

            if not claimed_jobs:
                self.log_event("Could not claim any jobs — all locked or queue empty.", level="info")
                await asyncio.sleep(2)
                continue

            self.log_event(
                f"Claimed {len(claimed_jobs)} job(s) for parallel processing (concurrency={self.concurrency})",
                level="info",
                metadata={"jobIds": [j.get("id") for j in claimed_jobs]},
            )

            # 4. Process claimed jobs in parallel using semaphore
            tasks: list[asyncio.Task] = []
            for slot_idx, job_item in enumerate(claimed_jobs):
                # Assign worker state
                if slot_idx in self.worker_states:
                    ws = self.worker_states[slot_idx]
                else:
                    ws = WorkerState(worker_id=f"{self.worker_id}_slot{slot_idx}", slot=slot_idx)
                    self.worker_states[slot_idx] = ws

                ws.status = "claiming"
                ws.current_job = job_item
                ws.started_at = now_iso()
                ws.error = ""

                task = asyncio.create_task(
                    self._run_worker_slot(semaphore, run["id"], job_item, ws, slot_idx)
                )
                tasks.append(task)

                # Stagger delay between worker launches to avoid thundering herd
                if slot_idx < len(claimed_jobs) - 1:
                    await asyncio.sleep(self.stagger_delay)

            # Wait for all parallel workers to complete
            results = await asyncio.gather(*tasks, return_exceptions=True)

            # Log any exceptions from workers
            for i, result in enumerate(results):
                if isinstance(result, Exception):
                    logger.error("Worker slot %d raised exception: %s", i, result)
                    self.log_event(f"Worker slot {i} exception: {result}", level="error")

            # Reset worker states to idle
            for ws in self.worker_states.values():
                if ws.status not in ("error",):
                    ws.status = "idle"
                    ws.current_job = None

                # Yield briefly before claiming the next wave. The browser work
                # itself is the rate limiter; a longer fixed idle wastes slots.
                await asyncio.sleep(0.35)

    async def _run_worker_slot(
        self,
        semaphore: asyncio.Semaphore,
        run_id: str,
        job_item: dict[str, Any],
        worker_state: WorkerState,
        slot_idx: int,
    ) -> None:
        """Process a single job within a concurrency-limited worker slot."""
        async with semaphore:
            job_id = job_item["id"]
            job_start = time.time()
            self.metrics.total_jobs_started += 1
            worker_state.status = "applying"

            self.log_event(
                f"[Worker {slot_idx}] Processing: {job_item.get('company')} — {job_item.get('title')}",
                level="info",
                metadata={"workerId": worker_state.worker_id, "slot": slot_idx, "jobId": job_id},
            )

            try:
                await self._process_single_job_with_retries(run_id, job_item, worker_state)
                worker_state.jobs_completed += 1
            except Exception as unhandled_job_error:
                self._handle_unhandled_job_exception_sync(run_id, job_item, unhandled_job_error)
                worker_state.status = "error"
                worker_state.error = str(unhandled_job_error)
                worker_state.jobs_failed += 1
            finally:
                with session_scope() as db:
                    release_job_lock(db, job_id, self.worker_id)
                    r = get_autopilot_run(db, run_id)
                    if r:
                        r["processedCount"] = (r.get("processedCount") or 0) + 1
                        r["currentJobId"] = None
                        save_autopilot_run(db, r)

                job_elapsed = time.time() - job_start
                self.metrics.total_jobs_finished += 1
                self.metrics.total_job_time_sec += job_elapsed
                worker_state.status = "done"

                self.log_event(
                    f"[Worker {slot_idx}] Finished: {job_item.get('company')} ({job_elapsed:.1f}s)",
                    level="info",
                    metadata={"slot": slot_idx, "elapsedSec": round(job_elapsed, 1)},
                )

    async def _trigger_post_batch_self_healing(self, run_id: str) -> None:
        """After a batch completes, check for failures and trigger self-healing if enabled."""
        if not self.self_healing_enabled:
            return

        failed_jobs: list[dict[str, Any]] = []
        with session_scope() as db:
            all_jobs = list_autopilot_jobs(db)
            failed_jobs = [j for j in all_jobs if j.get("status") in (AutopilotJobStatus.FAILED.value, "ERROR")]

        if not failed_jobs:
            self.log_event("Post-batch check: No failures detected — self-healing not needed.", level="info")
            return

        self.log_event(
            f"Post-batch check: {len(failed_jobs)} failed job(s) detected — triggering self-healing cycle...",
            level="warning",
            metadata={"failedCount": len(failed_jobs)},
        )

        from app.services.application_assistant.autopilot_self_healer import run_self_healing_cycle

        try:
            result = await run_self_healing_cycle(
                failed_jobs=failed_jobs,
                log_event_fn=self.log_event,
                max_rounds=MAX_JOB_ATTEMPTS,
            )
            self.metrics.self_healing_rounds_completed += result.get("totalRounds", 0)

            # If patches were applied and jobs were re-queued, restart the batch loop
            if result.get("patchesApplied", 0) > 0:
                self.log_event(
                    f"Self-healing applied {result['patchesApplied']} patch(es) — re-entering batch loop to retry failed jobs",
                    level="info",
                )
                # Update the run status back to RUNNING so the loop continues
                with session_scope() as db:
                    r = get_autopilot_run(db, run_id)
                    if r:
                        r["status"] = AutopilotRunStatus.RUNNING.value
                        r["completedAt"] = None
                        # Increase target count to cover the re-queued jobs
                        requeued_count = sum(1 for j in failed_jobs)
                        r["targetProcessCount"] = (r.get("processedCount") or 0) + requeued_count
                        save_autopilot_run(db, r)
                # Re-enter the batch loop — spawn a new loop task
                if self._loop_task is None or self._loop_task.done():
                    self._loop_task = asyncio.create_task(self._run_batch_worker())
            else:
                self.log_event("Self-healing completed but no patches were applied.", level="info")
        except Exception as e:
            self.log_event(f"Self-healing cycle failed: {e}", level="error")
            logger.error("Self-healing cycle error: %s", traceback.format_exc())

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
        self, run_id: str, job_item: dict[str, Any], worker_state: WorkerState | None = None
    ) -> None:
        attempt = (job_item.get("attemptCount") or 0) + 1
        job_item["attemptCount"] = attempt
        self._record_checkpoint(job_item, CheckpointStep.JOB_CLAIMED, f"Attempt {attempt}/{MAX_JOB_ATTEMPTS}")
        with session_scope() as db:
            save_autopilot_job(db, job_item)

        try:
            await self._execute_application_pipeline(run_id, job_item, worker_state)
        except Exception as exc:
            err_type = self._classify_error(exc)

            if err_type in TRANSIENT_ERRORS and attempt < MAX_JOB_ATTEMPTS:
                delay = 2 if attempt == 1 else 5
                self.log_event(f"Transient error ({err_type}). Retrying attempt {attempt + 1} after {delay}s...", level="warning")
                await asyncio.sleep(delay)
                return await self._process_single_job_with_retries(run_id, job_item, worker_state)

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
        self, run_id: str, job_item: dict[str, Any], worker_state: WorkerState | None = None
    ) -> None:
        company = job_item.get("company") or "Unknown"
        title = job_item.get("title") or "Unknown"
        app_url = job_item.get("applicationUrl") or ""
        slot_idx = worker_state.slot if worker_state is not None else None
        w_prefix = f"[Worker {slot_idx}] " if slot_idx is not None else ""

        self.log_event(
            f"{w_prefix}Processing: {company} — {title} (Match Score: {job_item.get('matchScore', 85)}%)",
            level="info",
            metadata={"slot": slot_idx, "company": company, "title": title},
        )
        if worker_state:
            worker_state.current_step = "PAGE_OPENED"
        await asyncio.sleep(0.2)

        # Step: PAGE_OPENED
        job_item["status"] = AutopilotJobStatus.APPLYING.value
        job_item["applicationStartedAt"] = now_iso()
        self._record_checkpoint(job_item, CheckpointStep.PAGE_OPENED, f"Opened {app_url}")
        with session_scope() as db:
            save_autopilot_job(db, job_item)

        self.log_event(
            f"{w_prefix}Opened application page for {company}...",
            level="info",
            metadata={"slot": slot_idx, "company": company},
        )
        if worker_state:
            worker_state.current_step = "FORM_DISCOVERED"
        await asyncio.sleep(0.2)

        # Step: FORM_DISCOVERED & LIVE PLAYWRIGHT SUBMISSION
        from app.db.store import get_kv
        from app.services.application_assistant.persistence import list_answer_library
        profile: dict[str, Any] = {}
        answer_lib: list[dict[str, Any]] = []
        with session_scope() as db:
            profile = get_kv(db, "profile") or {}
            answer_lib = list_answer_library(db)

        self.log_event(
            f"{w_prefix}Launching Playwright live Chromium session for {company}...",
            level="info",
            metadata={"slot": slot_idx, "company": company},
        )
        self._record_checkpoint(job_item, CheckpointStep.FORM_DISCOVERED, "Navigating via Chromium")
        with session_scope() as db:
            save_autopilot_job(db, job_item)

        from app.services.application_assistant.playwright_autopilot_executor import execute_live_playwright_submission

        headless_mode = os.environ.get("AA_HEADLESS", "true").lower() in ("true", "1")

        self.log_event(
            f"{w_prefix}Inspecting form DOM, attaching resume & filling fields for {company}...",
            level="info",
            metadata={"slot": slot_idx, "company": company},
        )
        if worker_state:
            worker_state.status = "filling"
            worker_state.current_step = "QUESTIONS_COMPLETED"
        self._record_checkpoint(job_item, CheckpointStep.QUESTIONS_COMPLETED, "Resolving form fields")

        def _granular_log(msg: str, lvl: str = "info") -> None:
            if worker_state and msg:
                worker_state.current_step = msg[:40]
            self.log_event(
                f"{w_prefix}{msg}",
                level=lvl,
                metadata={"slot": slot_idx, "company": company},
            )

        result = await execute_live_playwright_submission(
            job_item=job_item,
            profile=profile,
            answer_lib=answer_lib,
            headless=headless_mode,
            timeout_sec=60.0,
            log_callback=_granular_log,
        )

        if result.get("submitted"):
            if worker_state:
                worker_state.status = "submitting"
                worker_state.current_step = "SUBMITTED"
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
            self.log_event(
                f"{w_prefix}Successfully submitted real application for {company} — {title} 🎉 (Proof captured)",
                level="info",
                metadata={"slot": slot_idx, "company": company, "title": title},
            )
        elif result.get("expired"):
            # Job is unlisted / removed by employer: Drop from list and exclude permanently from future queue
            self.log_event(
                f"{w_prefix}Job unlisted / expired by employer ({company} — {title}). Dropping from candidate list.",
                level="info",
                metadata={"slot": slot_idx, "company": company, "title": title},
            )
            with session_scope() as db:
                from app.services.application_assistant.persistence import delete_autopilot_job
                delete_autopilot_job(db, job_item["id"])
                # Also archive or mark inactive in discovered jobs so it is never picked up again
                from app.db.store import get_entity, upsert_entity
                job_id = job_item.get("jobId")
                if job_id:
                    dj = get_entity(db, "discovered_job", job_id)
                    if dj:
                        dj["active"] = False
                        dj["expired"] = True
                        dj["unlistedAt"] = now_iso()
                        upsert_entity(db, "discovered_job", dj)
        else:
            err_msg = result.get("error") or "Submission unconfirmed"
            job_item["status"] = AutopilotJobStatus.FAILED.value
            job_item["lastError"] = err_msg
            evidence = result.get("evidence", {}) or {}
            if evidence.get("unresolvedRequiredFields") or evidence.get("preSubmitValidationErrors"):
                job_item["lastErrorType"] = ApplicationErrorType.VALIDATION_ERROR.value
            elif "submit button not found" in err_msg.lower():
                job_item["lastErrorType"] = ApplicationErrorType.ELEMENT_NOT_FOUND.value
            else:
                job_item["lastErrorType"] = ApplicationErrorType.SUBMISSION_UNCERTAIN.value
            job_item["submissionEvidence"] = evidence
            job_item["aiExplanation"] = err_msg
            self._record_checkpoint(job_item, CheckpointStep.FAILED, f"Failed: {err_msg}")
            if worker_state:
                worker_state.status = "error"
                worker_state.error = err_msg
            with session_scope() as db:
                save_autopilot_job(db, job_item)
                r = get_autopilot_run(db, run_id)
                if r:
                    r["failedCount"] = (r.get("failedCount") or 0) + 1
                    save_autopilot_run(db, r)
            self.log_event(
                f"{w_prefix}Application failed ({company}): {err_msg}",
                level="error",
                metadata={"slot": slot_idx, "company": company, "error": err_msg},
            )


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
