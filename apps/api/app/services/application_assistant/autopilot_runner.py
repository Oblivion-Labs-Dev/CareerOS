"""Fault-Tolerant Autopilot Application Runner Daemon for CareerOS.

Supports N concurrent browser workers with per-worker status tracking,
concurrency metrics, and a batch-end self-healing cycle powered by Qwen.
"""

from __future__ import annotations

import asyncio
import re
import threading
import logging
import os
import time
import traceback
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from sqlalchemy.orm import Session

from app.db.store import new_id, now_iso, session_scope
from app.services.application_assistant.adapters import resolve_adapter
from app.services.application_assistant.domain import (
    ApplicationErrorType,
    AutopilotJobStatus,
    AutopilotRunStatus,
    CheckpointStep,
    IneligibilityReason,
)
from app.services.application_assistant.job_filter_ranker import filter_and_rank_jobs
from app.services.application_assistant.persistence import (
    claim_job_lock,
    get_active_autopilot_run,
    get_autopilot_job,
    get_autopilot_run,
    get_settings,
    list_autopilot_jobs,
    list_discovered_jobs,
    release_job_lock,
    save_autopilot_job,
    save_autopilot_run,
)
from app.services.application_assistant.structured_answer_engine import resolve_application_question


logger = logging.getLogger("career_os.autopilot_runner")

MAX_JOB_ATTEMPTS = 3
# An application is submitted once its resume's match score reaches this
# bar. All queued jobs have already passed strict role, seniority, and location filters.
MIN_MATCH_SCORE_TO_SUBMIT = float(os.environ.get("AUTOPILOT_MIN_MATCH_SCORE", "80.0"))
# How many times a resume may be re-tailored for one posting before giving up.
# Each attempt is a full local-model rewrite plus a scoring pass (~30-60s on
# this hardware), so this trades wall-clock against the chance of clearing the
# bar. Three is enough for the pattern that actually works: one honest pass, one
# targeted at the reported gaps, one with the framing escalated.
MAX_TAILORING_ATTEMPTS = int(os.environ.get("AUTOPILOT_MAX_TAILORING_ATTEMPTS", "3"))
# The fewest rewritten bullets that still counts as a tailored resume.
#
# A high score alone is not sufficient grounds to submit. Match scoring reads
# the whole candidate context - profile, accomplishments, resume - so a posting
# can score well while the document itself came out byte-identical to the
# original, which is what happened when every batch was discarded by the
# alignment guard: the run reported a passing score and attached an untailored
# resume. Requiring that the rewrite actually changed something makes "the score
# is fine" and "the resume is fine" two separate conditions, both of which must
# hold before anything is sent to an employer.
MIN_TAILORED_BULLETS = int(os.environ.get("AUTOPILOT_MIN_TAILORED_BULLETS", "3"))
TAILORING_ESCALATION_ORDER = ["off", "honest", "aggressive"]

# Score bands that decide how hard to tailor. Set by the operator: a posting
# already at or above the submit bar needs no rewriting, one within striking
# distance gets honest re-emphasis, and one well below gets the strongest
# framing the underlying facts support.
TAILORING_HONEST_FLOOR = float(os.environ.get("AUTOPILOT_TAILORING_HONEST_FLOOR", "60.0"))


def _tailoring_mode_for_score(score: float, configured_mode: str) -> str:
    """Pick a tailoring mode from the pre-tailoring match score.

    Bands:
        >= MIN_MATCH_SCORE_TO_SUBMIT : "off"        - already clears the bar
        >= TAILORING_HONEST_FLOOR    : "honest"     - near miss, re-emphasise
        below that                   : "aggressive" - distant, push the framing

    An operator who has explicitly turned tailoring off keeps it off: the bands
    decide how much to tailor, not whether the feature is enabled at all.
    """
    if configured_mode == "off":
        return "off"
    if score >= MIN_MATCH_SCORE_TO_SUBMIT:
        return "off"
    if score >= TAILORING_HONEST_FLOOR:
        return "honest"
    return "aggressive"
# Launches are staggered just enough to avoid a burst of browser startups.  The
# former three-second default left most worker slots idle at the start of every
# batch without improving form reliability.
DEFAULT_STAGGER_DELAY = 0.5
# The persistent queue has no artificial size limit. Background preparation
# (`queue_preprocessor`) keeps pulling every eligible posting it can score into
# QUEUED for as long as Autopilot is running; this constant only decides how
# eagerly the batch loop performs its own inline top-up when the preprocessor
# has not caught up yet. Applications themselves still run strictly one at a
# time — see APPLY_CONCURRENCY.
QUEUE_REFILL_THRESHOLD = 50
# How many applications may be in an employer form at once.
#
# Sequential (1) is the safe default and stays the default. Each submission does
# launch its own Chromium with a fresh, non-persistent context, and job claiming
# is a per-row lease (see ``claim_job_lock``), so parallel workers do not share a
# browser profile and cannot both claim the same posting — the original "shared
# browser profile" concern no longer applies. What parallelism does cost is
# memory: roughly 300-500MB per concurrent Chromium. Raise this only when that
# headroom genuinely exists (for example with the local LLM switched off), via
# AUTOPILOT_APPLY_CONCURRENCY, and expect SQLite write contention to grow with
# it. Capped at 5 so a stray value cannot spawn an unbounded number of browsers.
APPLY_CONCURRENCY = max(1, min(5, int(os.environ.get("AUTOPILOT_APPLY_CONCURRENCY", "1"))))

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
        # Background queue-refill task (see _refill_queue) — tracked so a
        # top-up already in flight isn't launched a second time by the next
        # loop iteration before it finishes.
        self._refill_task: asyncio.Task | None = None
        self.activity_log: list[dict[str, Any]] = []
        self._subscribers: set[asyncio.Queue[dict[str, Any]]] = set()
        # Serializes read-modify-write updates to the shared run record so
        # concurrent workers don't lose each other's counter increments.
        # A plain threading.Lock (not asyncio.Lock) so it works from both the
        # async worker paths and the sync exception-boundary handler.
        self._run_update_lock = threading.Lock()

        # Job ids that a user explicitly clicked "Apply" on. The batch loop's
        # queue selection otherwise claims whichever QUEUED job comes first in
        # list_autopilot_jobs's order — unrelated to what the user clicked —
        # so a single-job Apply click could silently process a different job
        # entirely while the one the user asked for sits untouched. Checked
        # (and popped) in _process_batch_loop's claim step, front of the list first.
        self.priority_job_ids: list[str] = []

        # ── Concurrency state ──
        self.concurrency: int = APPLY_CONCURRENCY
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

        # Applications run one at a time regardless of what the caller asked
        # for; see APPLY_CONCURRENCY.
        self.concurrency = APPLY_CONCURRENCY
        requested_concurrency = int(opts.get("concurrency") or 0)
        if requested_concurrency > APPLY_CONCURRENCY:
            self.log_event(
                f"Ignoring requested concurrency {requested_concurrency}: applications run sequentially.",
                level="info",
            )
        self.stagger_delay = float(opts.get("staggerDelay") or DEFAULT_STAGGER_DELAY)
        self.self_healing_enabled = bool(opts.get("selfHealing", True))

        priority_job_id = opts.get("priorityJobId")
        if priority_job_id:
            if priority_job_id in self.priority_job_ids:
                self.priority_job_ids.remove(priority_job_id)
            self.priority_job_ids.insert(0, priority_job_id)

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
                    self._ensure_queue_preprocessor()
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
            f"Autopilot run started (Target batch: {target_count} jobs, applications run sequentially)",
            level="info",
            metadata={"runId": self.active_run_id, "concurrency": self.concurrency},
        )

        self._ensure_queue_preprocessor()

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
        # Queue preparation stops with the run: it exists to have the next job
        # ready for *this* runner, and leaving it scoring in the background
        # would keep the local model busy after the user asked Autopilot to
        # stop. The queue rows it already built persist either way.
        try:
            from app.services.application_assistant.queue_preprocessor import get_preprocessor

            await get_preprocessor().stop()
        except Exception as exc:
            logger.warning("Could not stop queue preprocessor: %s", exc)
        # Wait for the loop task to actually exit before returning. Without
        # this, the task can still be mid-flight (it only checks
        # _stop_requested at its own checkpoints) when this call returns —
        # if start() is then called again quickly, `self._loop_task.done()`
        # is still False, so start() skips spawning a new worker loop
        # entirely: the new run's DB record says RUNNING but nothing is
        # actually processing it. Bounded wait rather than indefinite, since
        # a genuinely wedged task shouldn't hang the stop() caller forever;
        # on timeout we log and proceed rather than cancel, since cancelling
        # mid-submission could skip the executor's own interrupted-submit
        # cleanup (staging as SUBMISSION_UNCERTAIN instead of leaving it
        # silently stuck).
        if self._loop_task and not self._loop_task.done():
            try:
                await asyncio.wait_for(asyncio.shield(self._loop_task), timeout=30)
            except asyncio.TimeoutError:
                logger.warning("Autopilot loop task still running 30s after stop() request; proceeding anyway.")
            except Exception:
                pass
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

    def _ensure_queue_preprocessor(self) -> None:
        """Keep the background queue pipeline alive alongside the run.

        Scraping, deduping, eligibility filtering and Mistral match scoring all
        continue while an application is mid-flight, so the next job is already
        prepared and ranked by the time the current one finishes.

        Deliberately fire-and-forget rather than awaited. Callers include
        ``start()``, which runs inside an open SQLite write transaction — and
        the preprocessor's own startup writes its stats row. Awaiting it there
        made the second write wait on the first connection's lock, which is what
        stalled the "Apply" endpoint for ~45s and tripped the web client's
        request abort, showing the user a timeout error for an application that
        had actually started.
        """
        try:
            from app.services.application_assistant.queue_preprocessor import get_preprocessor

            preprocessor = get_preprocessor()
            if preprocessor.is_running():
                return
            asyncio.create_task(preprocessor.start())
            self.log_event(
                "Background queue preparation started (scrape → dedupe → filters → Mistral match → queue)",
                level="info",
            )
        except Exception as exc:
            logger.warning("Could not start queue preprocessor: %s", exc)
            self.log_event(f"Queue preparation unavailable: {exc}", level="warning")

    async def _refill_queue(self, deficit: int, run_settings: dict[str, Any]) -> None:
        """Pull up to `deficit` more eligible postings from the discovered-jobs
        backlog into the QUEUED state, reusing the same hard-filter/match-score
        ranking and duplicate protection as the original queue-population path.
        Safe to run concurrently with in-progress job processing — it only
        ever adds new QUEUED rows, never touches a job that's already claimed.
        """
        from app.db.store import get_kv
        from app.services.application_assistant.persistence import is_duplicate_application

        with session_scope() as db:
            existing_autopilot_jobs = list_autopilot_jobs(db)
            profile = get_kv(db, "profile") or {}
            raw_jobs = list_discovered_jobs(db, active_only=True, exclude_demo=True)

        if not raw_jobs:
            return

        self.log_event(f"Queue refill: scanning discovered postings for {deficit} more eligible matches...", level="info")
        refill_settings = {**run_settings, "maxApplicationsPerRun": deficit}
        # Reuse whatever the background preprocessor has already scored with
        # Mistral so this catch-up path never re-ranks the same posting with the
        # weaker keyword heuristic.
        precomputed = {
            str(j.get("id")): j["mistralMatch"]
            for j in raw_jobs
            if isinstance(j.get("mistralMatch"), dict)
        }
        ranked = filter_and_rank_jobs(
            existing_autopilot_jobs, raw_jobs, profile, refill_settings,
            precomputed_matches=precomputed,
        )
        if not ranked:
            self.log_event("Queue refill: no new unapplied job postings found in database.", level="info")
            return

        self.log_event(f"Queue refill: selected {len(ranked)} eligible job postings matching target criteria", level="info")
        enqueued_count = 0
        with session_scope() as db:
            for r in ranked:
                r_company = r.get("company") or ""
                r_title = r.get("title") or ""
                r_url = r.get("applicationUrl") or r.get("listingUrl") or ""
                is_dup, _ = is_duplicate_application(db, r_company, r_title, r_url)
                if is_dup:
                    continue
                save_autopilot_job(db, {
                    "id": new_id("apjob_"),
                    "jobId": r.get("id") or new_id("job_"),
                    "company": r_company,
                    "title": r_title,
                    "applicationUrl": r_url,
                    "status": AutopilotJobStatus.QUEUED.value,
                    "matchScore": r.get("matchScore", 0.0),
                    "matchReason": r.get("matchReason", ""),
                    "keyMatchingSkills": r.get("keyMatchingSkills", []),
                    "missingSkills": r.get("missingSkills", []),
                    "matchMethod": r.get("matchMethod", ""),
                    "matchModel": r.get("matchModel", ""),
                    "matchReasons": r.get("matchReasons", []),
                    "queuePriority": r.get("queuePriority", 0.0),
                    "location": r.get("location", ""),
                    "discoveredAt": now_iso(),
                    "queuedAt": now_iso(),
                })
                enqueued_count += 1
        if enqueued_count < len(ranked):
            self.log_event(f"Queue refill: deduplicated {len(ranked) - enqueued_count} already-applied jobs", level="info")
        self.log_event(f"Queue refill: enqueued {enqueued_count} new job(s)", level="info")

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
                # The run this loop was tracking finished (e.g. self-healing just
                # wrapped up). Before exiting, check for a *different* run that was
                # started while we were busy — otherwise a Start Run click that lands
                # in this exact window leaves the new run stuck at RUNNING with no
                # worker actually processing it until the next manual start/reload.
                with session_scope() as db:
                    fresh_active = get_active_autopilot_run(db)
                if fresh_active and fresh_active.get("status") in (AutopilotRunStatus.RUNNING.value, AutopilotRunStatus.RECOVERING.value):
                    self.active_run_id = fresh_active["id"]
                    continue
                self.log_event(f"Batch worker idle — active run status is '{run.get('status') if run else 'NONE'}'", level="info")
                break

            target_count = run.get("targetProcessCount", 25)
            processed_count = run.get("processedCount", 0)
            submitted_count = run.get("submittedCount", 0)

            if processed_count >= target_count:
                with session_scope() as db:
                    r = get_autopilot_run(db, run["id"])
                    if r:
                        r["status"] = AutopilotRunStatus.COMPLETED.value
                        r["completedAt"] = now_iso()
                        r["currentJobId"] = None
                        save_autopilot_run(db, r)
                self.log_event(f"Batch completed: {submitted_count} applications submitted ({processed_count} processed)!", level="info")
                await self._trigger_post_batch_self_healing(run["id"])
                continue

            # Heartbeat update
            with session_scope() as db:
                r = get_autopilot_run(db, run["id"])
                if r:
                    r["lastHeartbeatAt"] = now_iso()
                    r["logs"] = self.activity_log[-100:]
                    save_autopilot_run(db, r)

            # 2. Fetch queued jobs. The background preprocessor is the primary
            # source of new QUEUED rows and runs continuously with no size cap;
            # the inline refill below is only a catch-up for the case where the
            # queue is shallow and the preprocessor has not reached those
            # postings yet. When there's still work to process this iteration,
            # the refill runs as a background task instead of blocking that
            # work on an LLM match-scoring pass over the discovered backlog.
            self._ensure_queue_preprocessor()
            with session_scope() as db:
                existing_autopilot_jobs = list_autopilot_jobs(db)
            queued = [j for j in existing_autopilot_jobs if j.get("status") == AutopilotJobStatus.QUEUED.value]
            deficit = QUEUE_REFILL_THRESHOLD - len(queued)

            if deficit > 0 and (self._refill_task is None or self._refill_task.done()):
                run_settings = run.get("settings") or {}
                if queued:
                    self._refill_task = asyncio.create_task(self._refill_queue(deficit, run_settings))
                else:
                    await self._refill_queue(deficit, run_settings)
                    with session_scope() as db:
                        existing_autopilot_jobs = list_autopilot_jobs(db)
                    queued = [j for j in existing_autopilot_jobs if j.get("status") == AutopilotJobStatus.QUEUED.value]

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
                continue

            # 3. Claim the next job, never more than the batch still needs.
            # Claim order is exactly the queue's own ordering key — the
            # location/level tier bonus plus the Mistral resume-match score
            # (see job_filter_ranker.queue_priority_score) — so a posting the
            # preprocessor scored higher five minutes ago genuinely overtakes
            # what was already waiting. list_autopilot_jobs returns rows in
            # storage order, so without this the runner would apply to whichever
            # job happens to sit at the front of the table.
            from app.services.application_assistant.job_filter_ranker import queue_priority_score
            queued.sort(
                key=lambda j: (queue_priority_score(j), j.get("queuedAt") or ""),
                reverse=True,
            )

            # Jobs the user explicitly clicked "Apply" on jump the queue first —
            # see priority_job_ids above.
            if self.priority_job_ids:
                by_id = {j["id"]: j for j in queued}
                prioritized = [by_id.pop(pid) for pid in list(self.priority_job_ids) if pid in by_id]
                queued = prioritized + list(by_id.values())

            remaining_budget = max(0, target_count - processed_count)
            claim_limit = min(self.concurrency, remaining_budget)
            claimed_jobs: list[dict[str, Any]] = []
            with session_scope() as db:
                for cand in queued:
                    if len(claimed_jobs) >= claim_limit:
                        break
                    if claim_job_lock(db, cand["id"], self.worker_id):
                        claimed_jobs.append(cand)
                    else:
                        self.metrics.lock_contention_count += 1

            if not claimed_jobs:
                self.log_event("Could not claim any jobs — all locked or queue empty.", level="info")
                await asyncio.sleep(2)
                continue

            for claimed in claimed_jobs:
                if claimed["id"] in self.priority_job_ids:
                    self.priority_job_ids.remove(claimed["id"])

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
                with self._run_update_lock:
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
            failed_jobs = [j for j in all_jobs if j.get("status") in (AutopilotJobStatus.FAILED.value, "ERROR") and j.get("lastAttemptRunId") == run_id]

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
        # SAFETY GUARD: Never retry a job with persistent blocking contradictions.
        # These can only be resolved through explicit human review (custom answers).
        if job_item.get("hasPersistentBlock") or job_item.get("blockingContradictions"):
            company = job_item.get("company", "Unknown")
            title = job_item.get("title", "Unknown")
            job_item["status"] = AutopilotJobStatus.NEEDS_REVIEW.value
            job_item["lastError"] = "Persistent contradiction block — requires human review"
            job_item["aiExplanation"] = (
                "This application has irreconcilable contradictions detected on a prior attempt. "
                "Automated retries cannot clear this block. Please review and provide custom answers."
            )
            self._record_checkpoint(job_item, CheckpointStep.STAGED, "Persistent block prevents retry")
            with session_scope() as db:
                save_autopilot_job(db, job_item)
            self.log_event(
                f"Skipping retry for {company} — {title}: persistent contradiction block active",
                level="warning",
            )
            return

        # An ATS will not accept a second application to the same posting — it
        # just leaves the form on screen, which surfaces as an opaque "submit
        # button is still active" failure after a full browser run. Check before
        # opening a browser at all, and record it as the dead end it is.
        from app.services.application_assistant.ineligibility import (
            IneligibilityReason,
            apply_ineligibility,
            find_duplicate_submission,
        )

        with session_scope() as db:
            already_submitted = list_autopilot_jobs(db, AutopilotJobStatus.SUBMITTED.value)
        duplicate = find_duplicate_submission(job_item, already_submitted)
        if duplicate is not None:
            when = str(duplicate.get("submittedAt") or "")[:10] or "earlier"
            detail = f"Already applied to this posting on {when}"
            apply_ineligibility(job_item, IneligibilityReason.DUPLICATE_APPLICATION, detail)
            job_item["lastError"] = detail
            self._record_checkpoint(job_item, CheckpointStep.SKIPPED, detail)
            with session_scope() as db:
                save_autopilot_job(db, job_item)
            self.log_event(
                f"Duplicate: {job_item.get('company')} — {job_item.get('title')} ({detail})",
                level="warning",
            )
            return

        attempt = (job_item.get("attemptCount") or 0) + 1
        job_item["attemptCount"] = attempt
        job_item["lastAttemptRunId"] = run_id
        self._record_checkpoint(job_item, CheckpointStep.JOB_CLAIMED, f"Attempt {attempt}/{MAX_JOB_ATTEMPTS}")
        with session_scope() as db:
            save_autopilot_job(db, job_item)

        try:
            await self._execute_application_pipeline(run_id, job_item, worker_state)
        except Exception as exc:
            exc_detail = str(exc).strip() or exc.__class__.__name__
            err_type = self._classify_error(Exception(exc_detail))

            # An ineligible posting is not a failure to retry: no number of
            # attempts makes a citizenship-restricted, non-sponsoring, non-US or
            # dead posting applyable. Classify before the retry branch so those
            # never burn three attempts and never land in the review queue.
            from app.services.application_assistant.ineligibility import (
                apply_ineligibility,
                classify_ineligibility,
            )

            job_item["lastError"] = exc_detail
            job_item["lastErrorType"] = err_type
            classified = classify_ineligibility(job_item)
            if classified:
                reason, detail = classified
                apply_ineligibility(job_item, reason, detail)
                self._record_checkpoint(job_item, CheckpointStep.SKIPPED, f"{reason.value}: {detail}")
                with self._run_update_lock:
                    with session_scope() as db:
                        save_autopilot_job(db, job_item)
                        r = get_autopilot_run(db, run_id)
                        if r:
                            r["ineligibleCount"] = (r.get("ineligibleCount") or 0) + 1
                            save_autopilot_run(db, r)
                self.log_event(
                    f"Ineligible ({reason.value}): {job_item.get('company')} — {job_item.get('title')}",
                    level="warning",
                )
                return

            if err_type in TRANSIENT_ERRORS and attempt < MAX_JOB_ATTEMPTS:
                delay = 2 if attempt == 1 else 5
                self.log_event(f"Transient error ({err_type}). Retrying attempt {attempt + 1} after {delay}s...", level="warning")
                await asyncio.sleep(delay)
                return await self._process_single_job_with_retries(run_id, job_item, worker_state)

            job_item["status"] = AutopilotJobStatus.FAILED.value
            job_item["aiExplanation"] = f"Failed due to error: {err_type} ({exc_detail})"
            self._record_checkpoint(job_item, CheckpointStep.FAILED, f"Failed on error: {err_type}")
            with self._run_update_lock:
                with session_scope() as db:
                    save_autopilot_job(db, job_item)
                    r = get_autopilot_run(db, run_id)
                    if r:
                        r["failedCount"] = (r.get("failedCount") or 0) + 1
                        save_autopilot_run(db, r)

            # This is best-effort bookkeeping only. Never allow creating a
            # preparation draft to mask the original browser failure or crash
            # every worker in the batch.
            try:
                # Keep failed Autopilot work in the same preparation queue used
                # by All Applications. This preserves answers and evidence so a
                # user can resume a prepared application instead of starting
                # from a blank form after a safe submission block.
                from app.services.application_assistant.persistence import create_application_draft

                captured_answers = job_item.get("answers") or {}
                prepared_fields = [
                    {
                        "label": str(label),
                        "value": value,
                        "classification": "verified",
                        "source": "autopilot",
                    }
                    for label, value in captured_answers.items()
                    if value not in (None, "")
                ]
                with session_scope() as draft_db:
                    create_application_draft(draft_db, {
                        "jobId": job_item.get("jobId") or job_item.get("id"),
                        "jobUrl": job_item.get("applicationUrl") or job_item.get("listingUrl") or "",
                        "companyName": job_item.get("company") or "",
                        "roleTitle": job_item.get("title") or "",
                        "provider": job_item.get("provider") or job_item.get("sourceProvider") or "unknown",
                        "matchScore": job_item.get("matchScore") or 0,
                        "status": "ready_to_prepare",
                        "fields": prepared_fields,
                        "autopilotFailure": {
                            "jobId": job_item.get("id"),
                            "error": exc_detail,
                            "errorType": job_item.get("lastErrorType"),
                            "evidence": job_item.get("submissionEvidence") or {},
                            "capturedAnswers": captured_answers,
                        },
                    })
            except Exception:
                logger.exception("Could not preserve failed job %s as a preparation draft", job_item.get("id"))

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

        # Pre-check US citizenship & visa sponsorship / ITAR restrictions before opening browser
        from app.services.application_assistant.job_filter_ranker import evaluate_hard_filters
        from app.db.store import get_kv
        with session_scope() as filter_db:
            prof = get_kv(filter_db, "profile") or {}
        passed, skip_reason = evaluate_hard_filters(job_item, prof, [])
        classified_block = None
        if not passed:
            # Ask the classifier about *every* hard-filter rejection, not just the
            # citizenship/sponsorship wording. A posting behind a CAPTCHA, outside
            # the US, already gone, or demanding a fact the profile does not hold
            # is just as permanently closed — parking those in SKIPPED is what
            # made the skipped list impossible to work through. Anything the
            # classifier does not recognise stays a soft SKIP so it can be
            # revisited if the rule that rejected it changes.
            from app.services.application_assistant.ineligibility import (
                apply_ineligibility,
                classify_ineligibility,
            )

            job_item["skipReason"] = skip_reason
            job_item["aiExplanation"] = skip_reason
            classified_block = classify_ineligibility(job_item)

        if classified_block is not None:
            reason, detail = classified_block
            apply_ineligibility(job_item, reason, detail)
            self.log_event(
                f"{w_prefix}Ineligible {company} — {title} [{reason.value}]: {skip_reason}",
                level="warning",
                metadata={
                    "slot": slot_idx, "company": company, "title": title,
                    "reason": skip_reason, "ineligibilityReason": reason.value,
                },
            )
            self._record_checkpoint(job_item, CheckpointStep.SKIPPED, f"{reason.value}: {skip_reason}")
            with self._run_update_lock:
                with session_scope() as db:
                    save_autopilot_job(db, job_item)
                    r = get_autopilot_run(db, run_id)
                    if r:
                        r["ineligibleCount"] = (r.get("ineligibleCount") or 0) + 1
                        save_autopilot_run(db, r)
            return

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
        from app.db.store import get_kv, list_entities
        from app.services.application_assistant.persistence import list_answer_library
        profile: dict[str, Any] = {}
        answer_lib: list[dict[str, Any]] = []
        master_resume: dict[str, Any] = {}
        documents: dict[str, Any] = {}
        accomplishments: list[dict[str, Any]] = []
        with session_scope() as db:
            profile = get_kv(db, "profile") or {}
            answer_lib = list_answer_library(db)
            master_resume = get_kv(db, "resume_corpus_master") or {}
            # Re-scoring the tailored resume needs the same evidence base the
            # queue scorer used, or a tailored resume would be judged against a
            # narrower set of facts than the original was and score lower for
            # no reason.
            documents = get_kv(db, "documents") or {}
            try:
                accomplishments = list_entities(db, "accomplishment")
            except Exception:  # noqa: BLE001
                # Optional enrichment for scoring only. Losing it costs some
                # match accuracy; letting it raise would abort a submission that
                # is otherwise ready, which is far worse.
                logger.debug("Could not load accomplishments for match scoring", exc_info=True)
                accomplishments = []
            tailoring_mode = job_item.get("tailoringMode") or get_settings(db).get("tailoringMode", "honest")

        self.log_event(
            f"{w_prefix}Launching Playwright live Chromium session for {company}...",
            level="info",
            metadata={"slot": slot_idx, "company": company},
        )
        self._record_checkpoint(job_item, CheckpointStep.FORM_DISCOVERED, "Navigating via Chromium")
        with session_scope() as db:
            save_autopilot_job(db, job_item)

        from app.services.application_assistant.playwright_autopilot_executor import (
            execute_live_playwright_submission,
            get_active_resume_path,
        )

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

        # Preserve the operator's selected mode, even for low-scoring matches.
        submission_profile = dict(profile)
        try:
            base_match_score = float(job_item.get("matchScore") or 0.0)
        except (TypeError, ValueError):
            base_match_score = 0.0
        from app.services.application_assistant.resume_diff_service import (
            generate_role_tailoring_diff,
            render_tailored_resume_pdf,
        )

        # Tailoring effort is chosen by how far the posting starts from the bar.
        # A near-miss needs its real experience surfaced in the posting's own
        # vocabulary; a distant one needs the framing pushed as far as the facts
        # allow. Both modes are bound by the same absolute rule in the tailoring
        # prompt - employer, product, domain and every number stay exactly as
        # written - and by _reject_fabrication afterwards, so "aggressive"
        # amplifies framing, never invents experience.
        # Tailor, score the document that would actually be submitted, and try
        # again when it falls short. Each retry is told which requirements the
        # scorer said were still unevidenced, so attempt two is a targeted
        # second pass rather than a re-roll of attempt one. The mode escalates
        # once on the final attempt because a near-miss that honest rewriting
        # could not close is exactly the case aggressive framing exists for.
        start_mode = _tailoring_mode_for_score(base_match_score, tailoring_mode)
        _granular_log(
            f"Queue match {base_match_score:.0f}% -> tailoring mode '{start_mode}', "
            f"up to {MAX_TAILORING_ATTEMPTS} attempt(s) against a "
            f"{MIN_MATCH_SCORE_TO_SUBMIT:.0f}% bar"
        )

        diff_data: dict[str, Any] | None = None
        winning_mode: str | None = None
        best_score = 0.0
        best_diff: dict[str, Any] | None = None
        best_mode: str | None = None
        gaps: list[str] = []
        best_changed = 0
        override = job_item.get("manualMatchOverride") is True
        attempts_log: list[dict[str, Any]] = []

        try:
            from app.services.application_assistant.tailored_match import describe_gaps

            for attempt in range(1, MAX_TAILORING_ATTEMPTS + 1):
                # Escalate only on the last attempt, and only upward: an
                # operator who explicitly chose "off" is not overridden here.
                candidate_mode = start_mode
                if (
                    attempt == MAX_TAILORING_ATTEMPTS
                    and start_mode == "honest"
                    and MAX_TAILORING_ATTEMPTS > 1
                ):
                    candidate_mode = "aggressive"

                candidate_diff = await generate_role_tailoring_diff(
                    job_item,
                    profile,
                    master_resume,
                    mode=candidate_mode,
                    feedback_gaps=gaps or None,
                    documents=documents,
                    accomplishments=accomplishments,
                )
                score = float(candidate_diff.get("matchScore") or 0)
                rescored = bool(candidate_diff.get("matchRescored"))
                attempts_log.append(
                    {
                        "attempt": attempt,
                        "mode": candidate_mode,
                        "score": score,
                        "rescored": rescored,
                        "gapsTargeted": list(gaps),
                        "changedBullets": candidate_diff.get("totalChanges"),
                    }
                )
                _granular_log(
                    f"Attempt {attempt}/{MAX_TAILORING_ATTEMPTS} (mode={candidate_mode}): "
                    f"tailored resume scores {score:.0f}%"
                    + ("" if rescored else " [NOT re-scored - local model unavailable]")
                    + (f", changed {candidate_diff.get('totalChanges')} bullets"
                       if candidate_diff.get("totalChanges") is not None else "")
                )

                # Two independent conditions, both required: the document has
                # to score well enough AND actually be a tailored document.
                quality = candidate_diff.get("quality") or {}
                changed = int(quality.get("changed") or candidate_diff.get("totalChanges") or 0)

                if score > best_score or best_diff is None:
                    best_score, best_diff, best_mode = score, candidate_diff, candidate_mode
                    best_changed = changed
                resume_is_good = candidate_mode == "off" or (
                    not candidate_diff.get("tailoringFailed") and bool(quality.get("ok"))
                )
                if not resume_is_good:
                    problems = "; ".join(str(p) for p in (quality.get("problems") or []))
                    _granular_log(
                        f"Score {score:.0f}% clears the bar but the resume does not: "
                        + (problems or "tailoring fell back to the static template")
                        + ". Not submitting this."
                    )

                if (score >= MIN_MATCH_SCORE_TO_SUBMIT or override) and resume_is_good:
                    if score < MIN_MATCH_SCORE_TO_SUBMIT:
                        _granular_log(
                            f"Explicit Apply overrides the match cutoff ({score:.0f}%); "
                            f"keeping {candidate_mode} tailoring and all eligibility checks"
                        )
                    diff_data = candidate_diff
                    winning_mode = candidate_mode
                    break

                # A rewrite that could not be scored must not drive a retry:
                # the score did not fall short, it never existed, and re-running
                # would just burn a second model call on the same blind guess.
                if not rescored:
                    _granular_log(
                        "Tailored resume could not be re-scored, so there is nothing to "
                        "improve against; stopping after this attempt."
                    )
                    break

                gaps = describe_gaps(
                    {"missingSkills": candidate_diff.get("missingSkills") or []}
                )
                if attempt < MAX_TAILORING_ATTEMPTS:
                    _granular_log(
                        f"{score:.0f}% is below the {MIN_MATCH_SCORE_TO_SUBMIT:.0f}% bar; "
                        "retrying against the gaps the scorer found: "
                        + (", ".join(gaps[:6]) if gaps else "none reported")
                    )

            job_item["tailoringAttempts"] = attempts_log
        except Exception as e:
            logger.warning(
                "Resume tailoring/match-scoring failed for %s (mode=%s): %s",
                company, tailoring_mode, e,
            )

        if self._stop_requested:
            job_item["status"] = AutopilotJobStatus.QUEUED.value
            with session_scope() as db:
                save_autopilot_job(db, job_item)
            _granular_log("Stopped before opening the employer application form")
            return

        if winning_mode is None or diff_data is None:
            attempted = len(job_item.get("tailoringAttempts") or []) or 1
            skip_reason = (
                f"Match score stayed below {MIN_MATCH_SCORE_TO_SUBMIT:.0f}% after "
                f"{attempted} tailoring attempt(s) (best {best_score:.0f}%, "
                f"queue score {base_match_score:.0f}%)"
            )
            if best_changed < MIN_TAILORED_BULLETS:
                skip_reason = (
                    f"Resume was not usefully tailored after "
                    f"{len(job_item.get('tailoringAttempts') or []) or 1} attempt(s): only "
                    f"{best_changed} bullet(s) changed (need {MIN_TAILORED_BULLETS}); "
                    f"best score {best_score:.0f}%"
                )
            if best_diff and best_diff.get("missingSkills"):
                skip_reason += "; still unevidenced: " + ", ".join(
                    str(m) for m in best_diff["missingSkills"][:6]
                )
            self.log_event(
                f"{w_prefix}Skipped {company} — {title}: {skip_reason}",
                level="warning",
                metadata={"slot": slot_idx, "company": company, "title": title, "reason": skip_reason},
            )
            # NEEDS_REVIEW rather than SKIPPED: a below-cutoff match is a
            # judgement the user may disagree with, and they work through these
            # by opening the posting and applying by hand. A terminal SKIPPED
            # bucket hides the job from that workflow.
            job_item["status"] = AutopilotJobStatus.NEEDS_REVIEW.value
            job_item["skipReason"] = skip_reason
            job_item["lastError"] = skip_reason
            job_item["aiExplanation"] = skip_reason
            job_item["tailoringMode"] = tailoring_mode
            self._record_checkpoint(job_item, CheckpointStep.SKIPPED, skip_reason)
            with self._run_update_lock:
                with session_scope() as db:
                    save_autopilot_job(db, job_item)
                    r = get_autopilot_run(db, run_id)
                    if r:
                        r["skippedCount"] = (r.get("skippedCount") or 0) + 1
                        save_autopilot_run(db, r)
            return

        tailoring_mode = winning_mode
        job_item["tailoringMode"] = tailoring_mode
        job_item["matchScoreAtSubmission"] = diff_data.get("matchScore")
        if tailoring_mode == "off":
            # Tailoring off means the rendered PDF would be a byte-for-byte copy
            # of the candidate's original resume (see render_tailored_resume_pdf),
            # so writing one per job just fills data/tailored_resumes with
            # duplicates. Leave submission_profile["resumePath"] unset and let
            # get_active_resume_path fall through to the original resume.
            original_resume = get_active_resume_path(submission_profile)
            job_item["resumeFileUsed"] = Path(original_resume).name if original_resume else None
            job_item["resumeTailoringFailed"] = False
            job_item["resumeTailoringModel"] = ""
            job_item["resumeTailoringError"] = ""
            _granular_log("Tailoring off — submitting the original resume unmodified (no per-job PDF saved)")
        else:
            try:
                pdf_bytes = render_tailored_resume_pdf(diff_data, profile)
                tailored_dir = Path(__file__).resolve().parents[3] / "data" / "application_assistant" / "tailored_resumes"
                tailored_dir.mkdir(parents=True, exist_ok=True)
                # Human-readable and deterministic (company + title), not the
                # opaque job id — this is only our own internal storage name for
                # browsing/linking to a specific submission's resume; the file
                # actually uploaded to the ATS is always staged under the
                # candidate's normal resume filename regardless (see
                # get_resume_upload_payload in playwright_autopilot_executor.py),
                # so a distinctive name here never leaks to the employer. A short
                # id suffix keeps two postings with the same company+title from
                # overwriting each other's file.
                name_slug = re.sub(r"[^a-zA-Z0-9]+", "_", f"{company}_{title}").strip("_")[:80]
                id_suffix = str(job_item.get("id") or "job")[-8:]
                resume_path = tailored_dir / f"{name_slug}_{id_suffix}_{tailoring_mode}.pdf"
                resume_path.write_bytes(pdf_bytes)
                submission_profile["resumePath"] = str(resume_path)
                job_item["resumeFileUsed"] = resume_path.name
                job_item["resumeTailoringFailed"] = bool(diff_data.get("tailoringFailed"))
                job_item["resumeTailoringModel"] = diff_data.get("tailoringModel") or ""
                job_item["resumeTailoringError"] = diff_data.get("tailoringError") or ""
                if job_item["resumeTailoringFailed"]:
                    _granular_log("Resume tailoring unavailable; using the saved template wording", "warning")
                else:
                    _granular_log(
                        f"Tailored resume generated (mode={tailoring_mode}, "
                        f"model={job_item['resumeTailoringModel']}, match={diff_data.get('matchScore')}%)"
                    )
            except Exception as e:
                logger.warning(
                    "Resume PDF render failed for %s (mode=%s): %s — falling back to default resume",
                    company, tailoring_mode, e,
                )
                job_item["resumeFileUsed"] = None
                job_item["resumeTailoringFailed"] = True
                job_item["resumeTailoringError"] = str(e)[:300]

        # An untailored resume must never reach an employer silently. When
        # tailoring falls back to the generic static template the application is
        # held for review instead of submitted: the whole point of this pipeline
        # is that the employer receives a resume written against *their* posting,
        # and a template submission both wastes the application and misreports
        # what CareerOS did. This tightens the submission gate; it never loosens
        # one, and the deterministic pre-submit validation is untouched.
        if job_item.get("resumeTailoringFailed") and tailoring_mode != "off":
            reason = (
                "Resume tailoring fell back to the static template "
                f"({job_item.get('resumeTailoringError') or 'no tailored bullets produced'}); "
                "held for review rather than submitting an untailored resume."
            )
            job_item["status"] = AutopilotJobStatus.NEEDS_REVIEW.value
            job_item["lastError"] = reason
            job_item["aiExplanation"] = reason
            self._record_checkpoint(job_item, CheckpointStep.STAGED, reason)
            self.log_event(
                f"{w_prefix}Held {company} — {title}: {reason}",
                level="warning",
                metadata={"slot": slot_idx, "company": company, "title": title},
            )
            with session_scope() as db:
                save_autopilot_job(db, job_item)
            return

        with session_scope() as db:
            save_autopilot_job(db, job_item)

        try:
            result = await asyncio.wait_for(
                execute_live_playwright_submission(
                    job_item=job_item,
                    profile=submission_profile,
                    answer_lib=answer_lib,
                    headless=headless_mode,
                    timeout_sec=420.0,
                    log_callback=_granular_log,
                ),
                timeout=480.0,
            )
        except asyncio.TimeoutError:
            logger.error("Playwright execution hard watchdog timed out for job %s", job_item.get("id"))
            result = {
                "submitted": False,
                "error": "Navigation or submission watchdog timeout (480s limit exceeded)",
                "evidence": {},
            }

        if result.get("submitted"):
            if worker_state:
                worker_state.status = "submitting"
                worker_state.current_step = "SUBMITTED"
            job_item["status"] = AutopilotJobStatus.SUBMITTED.value
            job_item["submittedAt"] = now_iso()
            evidence = dict(result.get("evidence", {}) or {})
            evidence["tailoringMode"] = job_item.get("tailoringMode")
            evidence["resumeFileUsed"] = job_item.get("resumeFileUsed")
            evidence["matchScoreAtSubmission"] = job_item.get("matchScoreAtSubmission")
            job_item["submissionEvidence"] = evidence
            job_item["answers"] = result.get("fieldsFilled", {})
            self._record_checkpoint(job_item, CheckpointStep.SUBMITTED, "Real browser submission confirmed")
            with self._run_update_lock:
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
        elif result.get("expired") or result.get("noApplicationForm"):
            # Job is unlisted / removed by employer: Drop from list and exclude permanently from future queue.
            # `noApplicationForm` lands here too: the executor sets it when the posting URL
            # resolved to a page with no form at all (observed live: otter.ai/careers, a
            # Coinbase posting 302ing to its careers index). That is a pulled posting, not a
            # selector bug — treating it as FAILED burned three retries per job and left the
            # dead posting eligible for the next batch.
            self.log_event(
                f"{w_prefix}Job unlisted / expired by employer ({company} — {title}). Dropping from candidate list.",
                level="info",
                metadata={"slot": slot_idx, "company": company, "title": title},
            )
            with session_scope() as db:
                from app.services.application_assistant.persistence import ENTITY_DISCOVERED_JOB
                from app.services.application_assistant.ineligibility import apply_ineligibility

                # Retained as an INELIGIBLE row rather than deleted: the user asked to
                # be able to see *why* a posting produced no application, and a silently
                # deleted job is indistinguishable from one that was never queued.
                apply_ineligibility(
                    job_item,
                    IneligibilityReason.POSTING_EXPIRED,
                    result.get("error") or "Posting was unlisted or removed by the employer.",
                )
                save_autopilot_job(db, job_item)
                r = get_autopilot_run(db, run_id)
                if r:
                    r["ineligibleCount"] = (r.get("ineligibleCount") or 0) + 1
                    save_autopilot_run(db, r)
                # Also archive or mark inactive in discovered jobs so it is never picked up again.
                # This must use ENTITY_DISCOVERED_JOB ("aa_discovered_job") — the entity type
                # every other reader/writer of these rows uses. It previously passed a bare
                # "discovered_job", so get_entity always returned None, the archive silently
                # never happened, and _refill_queue re-queued the very posting that had just
                # been dropped — expired postings cycled through the batch forever, each pass
                # consuming a processedCount slot without producing an application.
                from app.db.store import get_entity, upsert_entity
                job_id = job_item.get("jobId")
                if job_id:
                    dj = get_entity(db, ENTITY_DISCOVERED_JOB, job_id)
                    if dj:
                        dj["active"] = False
                        dj["expired"] = True
                        dj["unlistedAt"] = now_iso()
                        upsert_entity(db, ENTITY_DISCOVERED_JOB, dj)
                    else:
                        logger.warning(
                            "Expired job %s (%s — %s) had no discovered_job row to archive; "
                            "it may be re-discovered on the next crawl.",
                            job_id, company, title,
                        )
        elif result.get("stagedForReview") or result.get("status") == "NEEDS_REVIEW":
            # ─── VERIFIED AUTONOMY: STAGE TO NEEDS_REVIEW (NOT FAILED) ───
            review_reason = result.get("error") or "Requires human review before submission"
            job_item["status"] = AutopilotJobStatus.NEEDS_REVIEW.value
            job_item["lastError"] = f"Staged for human review: {review_reason}"
            job_item["lastErrorType"] = ApplicationErrorType.VALIDATION_ERROR.value
            job_item["submissionEvidence"] = result.get("evidence", {}) or {}
            job_item["answers"] = result.get("fieldsFilled", {})
            job_item["aiExplanation"] = job_item["lastError"]

            # ── Persist blocking contradictions from executor onto the job ──
            # The executor may have recorded new high-risk contradictions on
            # job_item["blockingContradictions"] during its run. These MUST be
            # persisted so that any subsequent retry or self-healing cycle
            # cannot bypass them — SubmissionPolicy will permanently block.
            blocking_issues = ((result.get("evidence") or {}).get("policyEvaluation") or {}).get("blockingIssues", [])
            has_persistent_blocks = any(bi.get("persistent") or bi.get("gate") == "PERSISTENT_CONTRADICTION_BLOCK" for bi in blocking_issues)
            if has_persistent_blocks:
                job_item["hasPersistentBlock"] = True
                self.log_event(
                    f"{w_prefix}PERSISTENT BLOCK: {company} — {title} has irreconcilable contradictions. "
                    f"Only human resolution (custom answers) can clear this.",
                    level="error",
                    metadata={"slot": slot_idx, "company": company, "title": title, "persistent": True},
                )

            # Structured, answerable questions for the Apply-board popup. Browser-automation
            # errors are inherently non-deterministic (wording varies per ATS, per field type,
            # per employer) — rather than hand-coding an ever-growing set of string patterns,
            # each blocking reason is classified by a local model into a fixed enum, which
            # decides both whether it's something a candidate can answer at all and, if so,
            # phrases it as one clean question. See error_normalizer.build_pending_questions —
            # shared with the on-demand re-classification endpoint for pre-existing jobs.
            from app.services.application_assistant.error_normalizer import build_pending_questions

            job_item["pendingQuestions"] = await build_pending_questions(blocking_issues)
            self._record_checkpoint(job_item, CheckpointStep.STAGED, f"Staged for Review: {review_reason}")
            
            if worker_state:
                worker_state.status = "done"
                worker_state.current_step = "NEEDS_REVIEW"
                
            with session_scope() as db:
                save_autopilot_job(db, job_item)
                
            self.log_event(
                f"{w_prefix}Application safely staged for human review: {company} — {title} (Ambiguity or safety rule triggered)",
                level="warning",
                metadata={"slot": slot_idx, "company": company, "title": title, "status": "NEEDS_REVIEW"},
            )
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
            # A board that refuses automation outright is not a technical
            # failure to retry — it is a posting the user can still submit by
            # hand. Without this the classifier was never consulted here, so a
            # CAPTCHA, DataDome or "flagged as possible spam" rejection sat in
            # FAILED forever and the real opportunity was buried.
            from app.services.application_assistant.ineligibility import (
                apply_ineligibility,
                classify_ineligibility,
            )

            classified_failure = classify_ineligibility(job_item)
            if classified_failure is not None:
                reason, detail = classified_failure
                apply_ineligibility(job_item, reason, detail)
                self.log_event(
                    f"{w_prefix}{company} — {title} cannot be automated [{reason.value}]: {err_msg}",
                    level="warning",
                    metadata={
                        "slot": slot_idx, "company": company, "title": title,
                        "ineligibilityReason": reason.value,
                        "status": job_item.get("status"),
                    },
                )
            self._record_checkpoint(job_item, CheckpointStep.FAILED, f"Failed: {err_msg}")
            if worker_state:
                worker_state.status = "error"
                worker_state.error = err_msg
            with self._run_update_lock:
                with session_scope() as db:
                    save_autopilot_job(db, job_item)
                    r = get_autopilot_run(db, run_id)
                    if r:
                        # A board that blocks automation is not a broken run, so
                        # it must not drag down the success rate the same way a
                        # genuine breakage does.
                        if classified_failure is not None:
                            r["ineligibleCount"] = (r.get("ineligibleCount") or 0) + 1
                        else:
                            r["failedCount"] = (r.get("failedCount") or 0) + 1
                        save_autopilot_run(db, r)
            if classified_failure is None:
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
        with self._run_update_lock, session_scope() as db:
            save_autopilot_job(db, job_item)
            r = get_autopilot_run(db, run_id)
            if r:
                r["failedCount"] = (r.get("failedCount") or 0) + 1
                save_autopilot_run(db, r)
