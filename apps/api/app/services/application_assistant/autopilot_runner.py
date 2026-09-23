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
from app.services.intelligence.night_shift_config import is_tier_1
from app.services.application_assistant.persistence import (
    application_identity,
    claim_application_identity,
    claim_job_lock,
    get_active_autopilot_run,
    get_autopilot_job,
    get_autopilot_run,
    get_settings,
    list_autopilot_jobs,
    list_discovered_jobs,
    most_recent_submit_attempt,
    release_application_identity,
    release_job_lock,
    save_autopilot_job,
    save_autopilot_run,
    save_settings,
)
from app.services.application_assistant import company_cap
from app.services.application_assistant.company_blacklist import partition_by_blacklist
from app.services.application_assistant.submission_pacing import seconds_until_next_submission
from app.services.application_assistant.submission_outcome import (
    classify_unproven_outcome,
    explain_unknown_submission,
    submit_was_attempted,
)
from app.services.application_assistant.structured_answer_engine import resolve_application_question
from app.services.observability import (
    tracer,
    agent_tracker,
    error_store,
    set_correlation_context,
    get_correlation_context,
)


logger = logging.getLogger("career_os.autopilot_runner")

MAX_JOB_ATTEMPTS = 3
# How long one application may take end to end before it is abandoned.
#
# 480s was tight for a Greenhouse posting: filling a long form is ~40s, and
# waiting for the emailed security code is allowed 150s on its own, so a slow
# board could exhaust the budget while doing exactly the right thing. Both
# values are env-tunable so a slow network does not mean editing code.
PLAYWRIGHT_WATCHDOG_TIMEOUT = float(os.environ.get("AUTOPILOT_JOB_TIMEOUT_SEC", "600"))
PLAYWRIGHT_INNER_TIMEOUT = max(60.0, PLAYWRIGHT_WATCHDOG_TIMEOUT - 60.0)
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


def _tailoring_mode_for_score(
    score: float, configured_mode: str, submit_bar: float | None = None
) -> str:
    """Pick a tailoring mode from the pre-tailoring match score.

    Bands:
        >= submit_bar             : "off"        - already clears the bar
        >= TAILORING_HONEST_FLOOR : "honest"     - near miss, re-emphasise
        below that                : "aggressive" - distant, push the framing

    ``submit_bar`` is the batch's own match floor, not the module default: the
    bands describe distance from *the bar this run is actually judged against*,
    so lowering the floor for a run has to move them with it.

    An operator who has explicitly turned tailoring off keeps it off: the bands
    decide how much to tailor, not whether the feature is enabled at all.
    """
    bar = MIN_MATCH_SCORE_TO_SUBMIT if submit_bar is None else submit_bar
    if configured_mode == "off":
        return "off"
    if score >= bar:
        return "off"
    if score >= min(TAILORING_HONEST_FLOOR, bar):
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
QUEUE_REFILL_THRESHOLD = 5
# Boards this automation can actually complete an application on, end to end.
#
# Measured over real runs, not assumed: Greenhouse (including the emailed
# security-code step), Lever and Ashby submit; everything else either has no
# driveable form at that URL, hands off to an employer's own app, or sits behind
# an account or a CAPTCHA. Spending a batch slot to rediscover that costs a full
# browser session each time and is why a run of ten produced one submission.
#
# This is a claim-time filter, not an eligibility verdict: the jobs stay queued
# and visible, they are simply not what an autonomous batch reaches for first.
SUBMITTABLE_ATS_HOSTS = (
    "greenhouse.io",
    "lever.co",
    "ashbyhq.com",
    "coinbase.com",
    "brex.com",
    "zipline.com",
    "hioscar.com",
    "block.xyz",
    "ripple.com",
    "riotgames.com",
    "datadoghq.com",
    "mongodb.com",
    "samsara.com",
    "fieldwire.com",
    "pantheon.io",
)


def _is_submittable_board(job: dict[str, Any]) -> bool:
    """True when the posting lives on a board a batch can finish unattended."""
    url = str(job.get("applicationUrl") or "").lower()
    if not url:
        return False
    # Roblox career pages start their apply flow externally/SSO and have no embedded form
    if "roblox.com" in url:
        return False
    # Greenhouse's embed endpoint only renders a form while framed by the
    # employer's page, so it is not submittable as a top-level URL.
    if "/embed/job_app" in url:
        return False
    if "gh_jid=" in url or "gh_src=" in url:
        return True
    return any(host in url for host in SUBMITTABLE_ATS_HOSTS)
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


def recover_stranded_applying_jobs(worker_id: str | None = None) -> dict[str, int]:
    """Return jobs stuck in APPLYING to the queue. Starts nothing.

    A job is left in APPLYING when the process dies mid-attempt. Until now the
    only thing that cleaned those up was starting a run, which meant a stranded
    job either sat there indefinitely or forced the user to kick off a batch
    they did not want just to clear it. Autopilot must not run unless the user
    asks it to, so recovery has to be available without starting anything.

    The submit marker decides the outcome, exactly as in the run-time sweep: a
    job whose submit click was already issued becomes SUBMISSION_UNKNOWN and is
    never silently retried, because recovery must not become the duplicate.
    Only an attempt that provably never reached submit goes back to the queue.
    """
    requeued = 0
    uncertain = 0
    with session_scope() as session:
        for job in list_autopilot_jobs(session):
            if job.get("status") != AutopilotJobStatus.APPLYING.value:
                continue
            if worker_id and job.get("lockedBy") == worker_id:
                # Belongs to a live worker in this process; leave it alone.
                continue
            if submit_was_attempted(job):
                job["status"] = AutopilotJobStatus.SUBMISSION_UNKNOWN.value
                job["lastErrorType"] = ApplicationErrorType.SUBMISSION_UNCERTAIN.value
                job["aiExplanation"] = explain_unknown_submission(job)
                uncertain += 1
            else:
                job["status"] = AutopilotJobStatus.QUEUED.value
                requeued += 1
            job["lockedBy"] = None
            job["lockedAt"] = None
            job["lockExpiresAt"] = None
            save_autopilot_job(session, job)
            release_application_identity(session, application_identity(job), str(job.get("id")))

    if requeued or uncertain:
        logger.info(
            "Recovered %d stranded APPLYING job(s): %d requeued, %d submission-uncertain.",
            requeued + uncertain,
            requeued,
            uncertain,
        )
    return {"requeued": requeued, "submissionUnknown": uncertain}


def collect_priority_ids(opts: dict[str, Any]) -> list[str]:
    """The job ids the user explicitly asked for, in the order given.

    Both spellings are accepted. The readiness gate already honoured the
    plural, but only the singular was ever consumed when priorities were
    recorded, so a ``priorityJobIds`` batch skipped the gate and then quietly
    lost its priority. Duplicates are collapsed, keeping the first position.
    """
    raw = [opts.get("priorityJobId"), *(opts.get("priorityJobIds") or [])]
    seen: dict[str, None] = {}
    for pid in raw:
        if pid:
            seen.setdefault(str(pid), None)
    return list(seen)


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

        # The same ids, but never drained. `priority_job_ids` is popped as jobs
        # are claimed, so by the time a job reaches the per-job pacing check its
        # id has already left that list. Clicking Apply is an explicit
        # instruction to send *this* application, so it overrides the
        # per-company rate limits — and that has to stay true for the whole of
        # the job's journey through the run, not just until it is claimed.
        self.manual_apply_job_ids: set[str] = set()

        # ── Concurrency state ──
        self.concurrency: int = APPLY_CONCURRENCY
        self.stagger_delay: float = DEFAULT_STAGGER_DELAY
        self.self_healing_enabled: bool = True
        self.worker_states: dict[int, WorkerState] = {}
        self.metrics = ConcurrencyMetrics()

        # ── Per-batch configuration ──
        # The match floor is a dial the operator sets per run from the batch
        # console, not a constant. It used to be read straight off the module
        # from inside the apply path, so the `minMatchScore` the UI sent was
        # only ever used to *order* the queue while the actual submit decision
        # silently kept using the environment default.
        self.min_match_score: float = MIN_MATCH_SCORE_TO_SUBMIT
        # Tier-1 guardrail: the operator's dream companies are applied to by
        # hand, so an unattended batch must never drive their forms.
        self.tier_guardrails: bool = True
        self.batch_size: int = 0
        # Claim only boards a batch can finish on its own (see
        # SUBMITTABLE_ATS_HOSTS). Defaults on: an unattended run should spend
        # its slots on work it can actually complete.
        self.submittable_boards_only: bool = True
        self._logged_board_filter: bool = False
        self._logged_company_cap: bool = False

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

    def _last_run_settings(self) -> dict[str, Any]:
        """Settings from the most recent run, used to fill in an omitted option.

        Start paths that are not the batch console (per-job retry, reprocess
        sweeps, the self-healer) send only the job they care about. Reading the
        previous run's settings keeps the operator's chosen match floor, model
        and guardrails in force across those, instead of snapping back to the
        environment defaults behind their back.
        """
        try:
            with session_scope() as db:
                run = get_active_autopilot_run(db) or get_autopilot_run(db, self.active_run_id or "")
                if run and isinstance(run.get("settings"), dict):
                    return dict(run["settings"])
        except Exception:
            logger.debug("Could not read previous run settings; using defaults.", exc_info=True)
        return {}

    async def start(self, options: dict[str, Any] | None = None, db: Session | None = None, **kwargs: Any) -> dict[str, Any]:
        """Start or resume a fault-tolerant Autopilot run."""
        # Normalize positional / keyword options
        if isinstance(options, Session):
            local_session = options
            opts = kwargs.get("options") or db or {}
        else:
            opts = options or kwargs.get("options") or {}
        # ── Pre-flight: refuse rather than discover a gap mid-application ────
        #
        # A missing answer used to be found only once the browser had opened the
        # posting and scraped the form: the attempt was abandoned and the job
        # filed in review. 872 jobs are in that state, 484 of them blocked on a
        # field nothing could answer, and each one cost a real browser run.
        #
        # Checked here, at the very top: before the options are parsed, before
        # the run row is written, and before the resume branch below, so a
        # resume of a live run cannot slip past it. Its own short session, since
        # reading inside the run-row write transaction is the hazard called out
        # in _ensure_queue_preprocessor's docstring.
        #
        # `start()` is not only the console's path - per-job retry, the
        # reprocess sweeps and the self-healer all call it. A deliberate
        # single-job retry is the user asking for exactly that job, so
        # priorityJobId bypasses the gate; only unattended batches are held.
        if not (opts.get("priorityJobId") or opts.get("priorityJobIds")):
            from app.db.store import get_kv
            from app.services.application_assistant.profile_readiness import (
                evaluate_profile_readiness,
            )

            with session_scope() as readiness_db:
                readiness = evaluate_profile_readiness(get_kv(readiness_db, "profile"))
            if not readiness.ready:
                self.log_event(
                    f"Run refused before starting: {readiness.summary()}",
                    level="warning",
                    metadata={"blockingCount": len(readiness.blocking)},
                )
                return {
                    "success": False,
                    "refused": True,
                    "reason": "profile_incomplete",
                    "message": readiness.summary(),
                    "readiness": readiness.to_dict(),
                }

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

        # Batch configuration chosen in the console. `minMatchScore` reaching
        # the apply path is the point: it is the bar a tailored resume has to
        # clear before anything is sent to an employer.
        #
        # Not every start comes from the console: a per-job "Retry", a
        # reprocess-failed sweep and the self-healer all call start() with only
        # a priorityJobId. Those must not silently reset the operator's floor to
        # the environment default - a retry at 80% of a job the operator queued
        # at 60% judges it by a bar they never chose. So an omitted option falls
        # back to the last run's saved settings before the module default.
        self.batch_size = target_count
        last_settings = self._last_run_settings()

        def _opt(key: str, default: Any) -> Any:
            if opts.get(key) is not None:
                return opts[key]
            if last_settings.get(key) is not None:
                return last_settings[key]
            return default

        raw_floor = _opt("minMatchScore", None)
        try:
            self.min_match_score = (
                MIN_MATCH_SCORE_TO_SUBMIT if raw_floor is None else float(raw_floor)
            )
        except (TypeError, ValueError):
            self.min_match_score = MIN_MATCH_SCORE_TO_SUBMIT
        self.tier_guardrails = bool(_opt("tierGuardrails", True))
        self.submittable_boards_only = bool(_opt("submittableBoardsOnly", True))
        self._logged_board_filter = False
        self._logged_company_cap = False
        # Carry the resolved configuration onto this run so the next start that
        # omits it reads back the same values rather than the defaults.
        opts = {
            **opts,
            "minMatchScore": self.min_match_score,
            "tierGuardrails": self.tier_guardrails,
            "submittableBoardsOnly": self.submittable_boards_only,
        }

        # A model chosen for the batch is persisted into settings rather than
        # held on the runner: every stage that talks to a model (match scoring,
        # field mapping, answer generation) builds its own client from settings,
        # so this is the only place a single choice reaches all of them.
        chosen_model = str(_opt("aiModel", "") or "").strip()
        if chosen_model:
            with session_scope() as model_db:
                current = get_settings(model_db)
                if str((current.get("llm") or {}).get("model") or "") != chosen_model:
                    save_settings(
                        model_db,
                        {"llm": {**(current.get("llm") or {}), "model": chosen_model}},
                    )
                    self.log_event(f"Batch model set to {chosen_model}", level="info")

        requested_priority = collect_priority_ids(opts)
        for priority_job_id in reversed(requested_priority):
            if priority_job_id in self.priority_job_ids:
                self.priority_job_ids.remove(priority_job_id)
            self.priority_job_ids.insert(0, priority_job_id)
        self.manual_apply_job_ids.update(requested_priority)

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
                    # targetProcessCount ratchets upward across resumes and stops
                    # meaning "batch size" after the first one - "24 / 38" reads as
                    # a batch of 38 when it is really four resumes' worth of
                    # 10-job requests layered on top of each other. resumeCount is
                    # the honest number: how many times this run has been resumed,
                    # for the UI to show as "Batch N" instead.
                    existing["resumeCount"] = int(existing.get("resumeCount") or 1) + 1
                    # The resolved opts (tierGuardrails, minMatchScore, selfHealing,
                    # ...) reflect this start() call and are already governing the
                    # runner in-memory below - without writing them back here, the
                    # persisted run row keeps whatever settings it was *first*
                    # created with, silently lying about what's actually running
                    # and becoming the fallback (_last_run_settings) for the next
                    # start() call that omits a field.
                    existing["settings"] = opts
                    self.active_run_id = existing["id"]
                    if hb_str:
                        try:
                            hb_dt = datetime.fromisoformat(hb_str.replace("Z", "+00:00"))
                            now_dt = datetime.now(timezone.utc)
                            if (now_dt - hb_dt).total_seconds() > 60:
                                self.log_event("Stale heartbeat detected — entering RECOVERING mode", level="warning")
                                existing["status"] = AutopilotRunStatus.RECOVERING.value
                                save_autopilot_run(local_db, existing)
                                self._recover_stale_run_sync(existing, local_db)
                        except Exception:
                            pass
                    saved_run = save_autopilot_run(local_db, existing)

            if not saved_run:
                run_id = new_id("aprun_")
                run_payload = {
                    "id": run_id,
                    "targetProcessCount": target_count,
                    "resumeCount": 1,
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

        self._stop_requested = False
        self._pause_requested = False

        self.log_event(
            f"Autopilot run started (Target batch: {target_count} jobs, applications run sequentially)",
            level="info",
            metadata={"runId": self.active_run_id, "concurrency": self.concurrency},
        )

        self._ensure_queue_preprocessor()

        if self._loop_task and not self._loop_task.done():
            logger.info("Cancelling lingering _loop_task for clean start of %s...", self.active_run_id)
            self._loop_task.cancel()
            try:
                await asyncio.wait_for(asyncio.shield(self._loop_task), timeout=1.0)
            except (asyncio.TimeoutError, asyncio.CancelledError, Exception):
                pass
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
                await asyncio.wait_for(asyncio.shield(self._loop_task), timeout=15)
            except asyncio.TimeoutError:
                logger.warning("Autopilot loop task still running 15s after stop() request; canceling.")
                self._loop_task.cancel()
            except (asyncio.CancelledError, Exception):
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
        # A posting independently re-discovered after it had already been
        # submitted can end up applied to twice - a real duplicate submission
        # to the employer, not a database artifact. The row stays SUBMITTED
        # (that is factually what happened) but is flagged duplicateSubmission
        # so it is not double-counted here; excluding it entirely from the
        # jobs list would hide a real submission from the application history.
        submitted_jobs = [
            j for j in jobs
            if j.get("status") == AutopilotJobStatus.SUBMITTED.value and not j.get("duplicateSubmission")
        ]
        # MANUAL_REVIEW counts here too. These are attempts the automation made
        # and could not finish — the posting was reached and no application was
        # sent, leaving the work for the candidate by hand. Leaving them out
        # made the success rate read 49% when 1,252 manual-review jobs sat
        # beside 1,040 submissions; the honest figure over the same rows is 31%.
        # SKIPPED and INELIGIBLE stay out on purpose: those were filtered before
        # any attempt, so they were never a chance to succeed.
        staged_jobs = [
            j for j in jobs
            if j.get("status") in (
                AutopilotJobStatus.STAGED.value,
                "NEEDS_REVIEW",
                AutopilotJobStatus.MANUAL_REVIEW.value,
            )
        ]
        skipped_jobs = [j for j in jobs if j.get("status") == AutopilotJobStatus.SKIPPED.value]
        failed_jobs = [
            j for j in jobs
            if j.get("status") in (AutopilotJobStatus.FAILED.value, "ERROR") or j.get("technicalFailure")
        ]
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

        # What the batch is actually configured to do, reported from the runner
        # rather than echoed back from the request the console sent, so the
        # console shows the values in force instead of the ones it asked for.
        batch_config = {
            "batchSize": self.batch_size,
            "minMatchScore": self.min_match_score,
            "tierGuardrails": self.tier_guardrails,
            "selfHealing": self.self_healing_enabled,
            "aiModel": (get_settings(db).get("llm") or {}).get("model", ""),
            "tailoringMode": get_settings(db).get("tailoringMode", "off"),
        }

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
                "batchConfig": batch_config,
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
            "batchConfig": batch_config,
        }

    def _recover_stale_run_sync(self, run: dict[str, Any], db: Session | None = None) -> None:
        """Inspect previous active job, release stale locks, and recover batch run."""
        def _do_recover(session: Session) -> None:
            current_job_id = run.get("currentJobId")
            if current_job_id:
                job = get_autopilot_job(session, current_job_id)
                if job and job.get("status") == AutopilotJobStatus.APPLYING.value:
                    # The durable submit marker decides this, not the checkpoint
                    # history. CheckpointStep.SUBMITTING was only ever read here
                    # and never actually recorded by any code path, so this guard
                    # never fired and every interrupted submit was requeued.
                    if submit_was_attempted(job):
                        job["status"] = AutopilotJobStatus.SUBMISSION_UNKNOWN.value
                        job["lastErrorType"] = ApplicationErrorType.SUBMISSION_UNCERTAIN.value
                        job["aiExplanation"] = explain_unknown_submission(job)
                        save_autopilot_job(session, job)
                        run["submissionUnknownCount"] = (run.get("submissionUnknownCount") or 0) + 1
                    else:
                        job["status"] = AutopilotJobStatus.QUEUED.value
                        save_autopilot_job(session, job)
                    release_job_lock(session, current_job_id, self.worker_id)
                    release_application_identity(session, application_identity(job), current_job_id)

            run["status"] = AutopilotRunStatus.RUNNING.value
            run["currentJobId"] = None
            save_autopilot_run(session, run)

            # Sweep any other orphaned APPLYING jobs across the entire queue whose lease expired
            now = now_iso()
            for aj in list_autopilot_jobs(session):
                if aj.get("status") == AutopilotJobStatus.APPLYING.value:
                    exp = aj.get("lockExpiresAt")
                    if not exp or exp <= now or aj.get("lockedBy") != self.worker_id:
                        # Same rule as above: an orphaned job whose submit click
                        # had already been issued must never be swept back onto
                        # the queue, or recovery itself becomes the duplicate.
                        if submit_was_attempted(aj):
                            aj["status"] = AutopilotJobStatus.SUBMISSION_UNKNOWN.value
                            aj["lastErrorType"] = ApplicationErrorType.SUBMISSION_UNCERTAIN.value
                            aj["aiExplanation"] = explain_unknown_submission(aj)
                        else:
                            aj["status"] = AutopilotJobStatus.QUEUED.value
                        aj["lockedBy"] = None
                        aj["lockedAt"] = None
                        aj["lockExpiresAt"] = None
                        save_autopilot_job(session, aj)
                        release_application_identity(session, application_identity(aj), str(aj.get("id")))

            self.log_event("Batch run recovered successfully", level="info")

        if db is not None:
            _do_recover(db)
        else:
            with session_scope() as session:
                _do_recover(session)

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
        """Top up the QUEUED pool when it drops below the target threshold.

        Preserves the same Mistral match caching, profile tailoring,
        ranking and duplicate protection as the original queue-population path.
        Safe to run concurrently with in-progress job processing - it only
        ever adds new QUEUED rows, never touches a job that is already claimed.
        """
        def _sync_refill() -> tuple[int, int, int]:
            from app.db.store import get_kv
            from app.services.application_assistant.persistence import is_duplicate_application

            with session_scope() as db:
                existing_autopilot_jobs = list_autopilot_jobs(db)
                profile = get_kv(db, "profile") or {}
                documents = get_kv(db, "documents") or {}
                from app.db.store import list_entities
                accomplishments = list_entities(db, "accomplishment")
                raw_jobs = list_discovered_jobs(db, active_only=True, exclude_demo=True)

            if not raw_jobs:
                return (0, 0, 0)

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
                existing_autopilot_jobs,
                raw_jobs,
                profile,
                refill_settings,
                precomputed_matches=precomputed,
                documents=documents,
                accomplishments=accomplishments,
            )
            if not ranked:
                return (0, 0, 0)

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
            return (len(ranked), enqueued_count, len(ranked) - enqueued_count)

        self.log_event(f"Queue refill: scanning discovered postings for {deficit} more eligible matches...", level="info")
        ranked_len, enqueued_count, dedup_count = await asyncio.to_thread(_sync_refill)
        if ranked_len == 0:
            self.log_event("Queue refill: no new unapplied job postings found in database.", level="info")
            return

        self.log_event(f"Queue refill: selected {ranked_len} eligible job postings matching target criteria", level="info")
        if dedup_count > 0:
            self.log_event(f"Queue refill: deduplicated {dedup_count} already-applied jobs", level="info")
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

            # Completion is keyed on how many jobs this cycle has ATTEMPTED
            # (processedCount), not how many were SUBMITTED. A job that lands
            # in NEEDS_REVIEW/MANUAL_REVIEW/SKIPPED/FAILED is still a
            # processed attempt — that is the whole point of "failed/skipped/
            # review-required jobs do not count as successful submissions"
            # rather than not counting at all. Keying this on submittedCount
            # instead left a batch that fully worked through its target but
            # submitted fewer than target_count permanently unable to
            # progress: remaining_budget below is target_count - processed_
            # count, which had already hit zero, so no job could ever be
            # claimed again, yet this check never became true either — a
            # deadlock that showed up live as "Could not claim any jobs" on
            # an endless ~2s loop even with dozens of jobs still queued.
            if processed_count >= target_count:
                self.log_event(
                    f"Batch cycle complete: {processed_count} processed, "
                    f"{submitted_count} submitted this cycle — starting next batch of {target_count}",
                    level="info",
                    metadata={"runId": run["id"], "processedCount": processed_count, "submittedCount": submitted_count},
                )
                # Reset counters for the next batch rather than terminating the run.
                # This enables continuous overnight operation with repeated batches of N.
                with session_scope() as db:
                    r = get_autopilot_run(db, run["id"])
                    if r:
                        r["processedCount"] = 0
                        r["submittedCount"] = 0
                        r["failedCount"] = 0
                        r["skippedCount"] = 0
                        r["ineligibleCount"] = 0
                        r["status"] = AutopilotRunStatus.RUNNING.value
                        r["lastHeartbeatAt"] = now_iso()
                        r["currentJobId"] = None
                        save_autopilot_run(db, r)
                # Re-enter the batch loop to claim the next wave of jobs.
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
                queued = list_autopilot_jobs(db, status=AutopilotJobStatus.QUEUED.value)
            deficit = QUEUE_REFILL_THRESHOLD - len(queued)

            if deficit > 0 and (self._refill_task is None or self._refill_task.done()):
                run_settings = run.get("settings") or {}
                if queued:
                    self._refill_task = asyncio.create_task(self._refill_queue(deficit, run_settings))
                else:
                    await self._refill_queue(deficit, run_settings)
                    with session_scope() as db:
                        queued = list_autopilot_jobs(db, status=AutopilotJobStatus.QUEUED.value)

            if not queued:
                self.log_event(
                    "No more eligible jobs in queue — attempting queue refill, continuing batch loop.",
                    level="info",
                    metadata={"runId": run["id"]},
                )
                # Refill the queue from discovered postings before deciding the batch is done.
                self._ensure_queue_preprocessor()
                with session_scope() as db:
                    queued = list_autopilot_jobs(db, status=AutopilotJobStatus.QUEUED.value)
                deficit = QUEUE_REFILL_THRESHOLD - len(queued)
                if deficit > 0:
                    if self._refill_task is None or self._refill_task.done():
                        run_settings = run.get("settings") or {}
                        if queued:
                            self._refill_task = asyncio.create_task(self._refill_queue(deficit, run_settings))
                        else:
                            await self._refill_queue(deficit, run_settings)
                            with session_scope() as db:
                                queued = list_autopilot_jobs(db, status=AutopilotJobStatus.QUEUED.value)
                if not queued:
                    # Truly no jobs left — mark as paused rather than completed so the
                    # run stays alive and can be restarted later manually or via scheduler.
                    with session_scope() as db:
                        r = get_autopilot_run(db, run["id"])
                        if r:
                            r["status"] = AutopilotRunStatus.PAUSED.value
                            r["lastHeartbeatAt"] = now_iso()
                            r["currentJobId"] = None
                            save_autopilot_run(db, r)
                    self.log_event("Queue empty and no new postings available — run paused.", level="info")
                    # Do NOT trigger post-batch self-healing here; that happens when a
                    # batch actually completes its target. Just wait for manual restart or
                    # new postings.
                    break
                # Continue the loop — we have jobs to process after refill.
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

            # Retire jobs at a blacklisted company before anything else runs.
            #
            # Unlike the pacing hold below, this is not something the batch
            # exempts a manually-clicked job from: a blacklist entry is the
            # candidate's own standing "never again" decision, not automation
            # flood control, so it binds even on a job the candidate clicked
            # Apply on earlier (before adding the company to the list, or from
            # a stale queue view). Removing the company from Settings is the
            # override, not a per-job click.
            with session_scope() as db:
                blacklist = get_settings(db).get("companyBlacklist") or []
            queued, blacklisted = partition_by_blacklist(queued, blacklist)
            if blacklisted:
                with session_scope() as db:
                    for blocked_job in blacklisted:
                        save_autopilot_job(db, blocked_job)
                companies = sorted({str(j.get("company") or "?") for j in blacklisted})
                self.log_event(
                    f"{len(blacklisted)} queued application(s) filed ineligible — "
                    f"on your do-not-apply list ({', '.join(companies[:4])}"
                    f"{'…' if len(companies) > 4 else ''}).",
                    level="info",
                )

            # Pace per employer before anything is claimed.
            #
            # This has to happen here rather than inside the per-job pipeline.
            # A held job keeps its QUEUED status by design, so if the pipeline
            # were the only gate the loop would claim it, skip it, and claim it
            # again on the next pass — spinning on the same postings and burning
            # processedCount against work it never attempted.
            #
            # `queued` is already sorted best-match-first, and partition_by_cap
            # preserves that order, so the jobs released when a window rolls are
            # the best-matching ones without ranking anything twice.
            with session_scope() as db:
                cap_all_jobs = list_autopilot_jobs(db)
            # A job the user clicked Apply on is exempt. Pacing exists to stop
            # the *automation* flooding one employer; an explicit click is the
            # user deciding this particular application is worth sending now.
            # Held out of the partition rather than filtered afterwards, so its
            # slot is not spent on behalf of some other queued job.
            manual = [j for j in queued if j.get("id") in self.manual_apply_job_ids]
            paceable = [j for j in queued if j.get("id") not in self.manual_apply_job_ids]
            queued, cap_held = company_cap.partition_by_cap(paceable, cap_all_jobs)
            for job in manual:
                company_cap.clear_hold(job)
            queued = manual + queued
            if cap_held:
                with session_scope() as db:
                    for held_job in cap_held:
                        save_autopilot_job(db, held_job)
                if not self._logged_company_cap:
                    self._logged_company_cap = True
                    companies = sorted({str(j.get("company") or "?") for j in cap_held})
                    by_tier: dict[str, int] = {}
                    for held_job in cap_held:
                        tier = str(held_job.get("companyCapTier") or "?")
                        by_tier[tier] = by_tier.get(tier, 0) + 1
                    limits = ", ".join(
                        f"{cap}/{name}" for name, cap, _days in company_cap.COMPANY_CAP_TIERS
                    )
                    tiers = ", ".join(f"{n} by the {t} limit" for t, n in sorted(by_tier.items()))
                    self.log_event(
                        f"{len(cap_held)} queued application(s) are pacing against the "
                        f"per-company limits ({limits}; {tiers}) "
                        f"({', '.join(companies[:4])}{'…' if len(companies) > 4 else ''}). "
                        "They stay queued and resume automatically, best matches first.",
                        level="info",
                        metadata={
                            "heldCount": len(cap_held),
                            "companies": companies[:20],
                            "heldByTier": by_tier,
                        },
                    )

            # Jobs the user explicitly clicked "Apply" on jump the queue first —
            # see priority_job_ids above.
            if self.priority_job_ids:
                by_id = {j["id"]: j for j in queued}
                prioritized = [by_id.pop(pid) for pid in list(self.priority_job_ids) if pid in by_id]
                queued = prioritized + list(by_id.values())

            # Prefer boards that can actually be finished unattended. This is a
            # preference, not an exclusion: if nothing submittable is left, the
            # run falls back to the full queue rather than stalling with work
            # still waiting.
            if self.submittable_boards_only:
                submittable = [j for j in queued if _is_submittable_board(j)]
                if submittable:
                    skipped = len(queued) - len(submittable)
                    if skipped and not self._logged_board_filter:
                        self._logged_board_filter = True
                        self.log_event(
                            f"Batch is preferring boards it can complete unattended "
                            f"(Greenhouse/Lever/Ashby): {len(submittable)} of {len(queued)} "
                            f"queued jobs qualify; the other {skipped} stay queued for manual work.",
                            level="info",
                        )
                    queued = submittable
                else:
                    self.log_event(
                        "No submittable-board jobs left in the queue — falling back to the "
                        "full queue for this pass.",
                        level="info",
                    )

            remaining_budget = max(0, target_count - processed_count)
            claim_limit = min(self.concurrency, remaining_budget)
            claimed_jobs: list[dict[str, Any]] = []
            with session_scope() as db:
                for cand in queued:
                    if len(claimed_jobs) >= claim_limit:
                        break
                    # Lease must outlive the watchdog that bounds actual processing
                    # (PLAYWRIGHT_WATCHDOG_TIMEOUT, default 600s) plus margin for the
                    # save/cleanup after it fires. The 300s persistence-layer default
                    # was shorter than a single slow job's real runtime, so a stale-
                    # lock recovery sweep (every `/autopilot/start`, which happens on
                    # every restart) could reset a job to QUEUED while a worker was
                    # still legitimately mid-submission on it.
                    if claim_job_lock(db, cand["id"], self.worker_id, lease_seconds=int(PLAYWRIGHT_WATCHDOG_TIMEOUT) + 120):
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
            from app.services.application_assistant.submission_outcome import is_retryable_technical_failure

            failed_jobs = [
                j for j in all_jobs
                if (is_retryable_technical_failure(j) or j.get("status") == "ERROR")
                and j.get("lastAttemptRunId") == run_id
            ]

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
        now_ts = now_iso()
        job_item["checkpointHistory"].append({
            "step": step.value,
            "timestamp": now_ts,
            "details": details,
        })
        job_item["currentStep"] = step.value

        # Set correlation context
        ctx = get_correlation_context()
        set_correlation_context(
            run_id=self.active_run_id,
            application_id=job_item.get("id"),
            job_id=job_item.get("jobId") or job_item.get("id"),
            workflow_stage=step.value,
            provider="ollama",
            model=job_item.get("resumeTailoringModel") or "qwen3:4b-instruct",
        )

        # Broadcast structured event for Live Autopilot Activity & Diagnostic observers
        evt_stage = "DISCOVER"
        if step in (CheckpointStep.FORM_DISCOVERED, CheckpointStep.QUESTIONS_COMPLETED, CheckpointStep.RESUME_UPLOADED):
            evt_stage = "PREPARE"
        elif step in (CheckpointStep.PRE_SUBMISSION_CHECK, CheckpointStep.SUBMITTING, CheckpointStep.VERIFYING_SUBMISSION, CheckpointStep.SUBMITTED):
            evt_stage = "APPLY"

        self._broadcast("autopilot_event", {
            "runId": self.active_run_id,
            "applicationId": job_item.get("id"),
            "jobId": job_item.get("jobId") or job_item.get("id"),
            "company": job_item.get("company"),
            "title": job_item.get("title"),
            "stage": evt_stage,
            "workflowStep": step.value,
            "status": "running" if step not in (CheckpointStep.SUBMITTED, CheckpointStep.SKIPPED, CheckpointStep.FAILED) else step.value.lower(),
            "message": details or f"Step {step.value}",
            "provider": "ollama",
            "model": job_item.get("resumeTailoringModel") or "qwen3:4b-instruct",
            "timestamp": now_ts,
            "durationMs": 2100,
            "traceId": ctx.get("trace_id"),
        })

    async def _gemini_match_gate(
        self,
        job_item: dict[str, Any],
        profile: dict[str, Any],
        score: float,
        log: Any,
    ) -> Any:
        """One optional second opinion on a posting the matcher could not settle.

        Returns None when the gate cannot run at all, which is treated exactly
        like "proceed" by the caller - an optional enhancement that is itself
        unavailable must not change what CareerOS does.

        The posting text is loaded from the discovered-job row, because an
        Autopilot job row carries only company, title, URL and location. Without
        the description there is nothing to be ambiguous *about*, so the gate
        steps aside rather than judging a posting it cannot read.
        """
        from app.services.gemini.config import applications_enabled

        if not applications_enabled():
            return None  # Treated as "proceed", exactly like an unavailable gate.
        try:
            from app.services.gemini import match_gate

            job_for_gate = dict(job_item)
            if not str(job_for_gate.get("description") or "").strip():
                source_id = job_item.get("jobId") or job_item.get("id")
                if source_id:
                    from app.db.store import get_entity
                    from app.services.application_assistant.persistence import (
                        ENTITY_DISCOVERED_JOB,
                    )

                    with session_scope() as db:
                        source = get_entity(db, ENTITY_DISCOVERED_JOB, source_id)
                    if source:
                        job_for_gate["description"] = source.get("description") or source.get("snippet") or ""
            if not str(job_for_gate.get("description") or "").strip():
                return None

            decision = await match_gate.evaluate(
                job_for_gate, score=score if score > 0 else None, profile=profile
            )
            if decision.consulted:
                log(f"Gemini match gate: {decision.action} — {decision.reason}")
            return decision
        except Exception:  # noqa: BLE001 - never let an optional gate fail a run
            logger.warning("Gemini match gate failed; continuing deterministically", exc_info=True)
            return None

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

        # Pre-application validation:
        # 1. Management / Director / Executive Role Exclusion
        # Prioritizes individual contributor software engineers (SDE 1, 2, 3, Senior SDE, Staff, Principal, Lead SWE)
        from app.services.application_assistant.ineligibility import (
            IneligibilityReason,
            apply_ineligibility,
            find_duplicate_submission,
        )
        from app.services.application_assistant.persistence import (
            is_strict_duplicate_processed,
            list_autopilot_jobs,
            list_submitted_duplicate_candidates,
        )

        title_raw = str(job_item.get("title") or "").strip()
        title_lower = title_raw.lower()
        MANAGEMENT_KEYWORDS = (
            "director", "manager", "engineering manager", "product manager",
            "program manager", "project manager", "head of", "vp", "vice president",
            "chief", "managing director", "lead manager",
        )
        if any(re.search(rf"\b{re.escape(kw)}\b", title_lower) for kw in MANAGEMENT_KEYWORDS):
            detail = f"Management/director role excluded: '{title_raw}'"
            apply_ineligibility(job_item, IneligibilityReason.ROLE_EXCLUDED, detail)
            job_item["lastError"] = detail
            self._record_checkpoint(job_item, CheckpointStep.SKIPPED, detail)
            with session_scope() as db:
                save_autopilot_job(db, job_item)
            self.log_event(f"Role Excluded: {job_item.get('company')} — {title_raw} ({detail})", level="info")
            return

        # 2. Company pacing caps — COMPANY_CAP_TIERS applications to one employer
        # across three rolling windows at once (5/day, 10/week, 20/month), with
        # every tier raised by FRESH_POSTING_BONUS for a role published in the
        # last day. `job=job_item` is what lets that bonus apply here.
        #
        # A capped posting is held, not disqualified: it keeps its QUEUED status
        # and gains companyCapHoldUntil, so it re-enters the ordinary claim path
        # by itself once the window rolls. This used to mark the job INELIGIBLE
        # with COMPANY_CAP_REACHED, which buried a perfectly live posting in a
        # terminal bucket the user works through expecting genuine dead ends.
        #
        # The batch loop filters held jobs out before claiming, so reaching this
        # branch is the narrow race where the cap filled between that filter and
        # this attempt. Held here as well rather than trusted to the caller.
        #
        # Unless the user clicked Apply on this job: that is an explicit
        # instruction to send this one, and it overrides the limits at both
        # gates. Checked against manual_apply_job_ids rather than
        # priority_job_ids because the latter has already been drained by the
        # claim step before execution reaches here.
        company_raw = str(job_item.get("company") or "").strip()
        manual_apply = job_item.get("id") in self.manual_apply_job_ids
        if manual_apply:
            company_cap.clear_hold(job_item)
            self.log_event(
                f"Manual Apply overrides the per-company limits for {company_raw or 'this employer'}.",
                level="info",
            )
        if not manual_apply:
            with session_scope() as db:
                all_db_jobs = list_autopilot_jobs(db)

            cap_release = company_cap.company_hold(
                [j for j in all_db_jobs if j.get("id") != job_item.get("id")],
                company_raw,
                job=job_item,
            )
            if cap_release is not None:
                company_cap.apply_hold(job_item, cap_release)
                job_item["status"] = AutopilotJobStatus.QUEUED.value
                detail = (
                    job_item.get("companyCapReason") or f"{company_raw} is at its application cap"
                )
                self._record_checkpoint(job_item, CheckpointStep.SKIPPED, detail)
                with session_scope() as db:
                    save_autopilot_job(db, job_item)
                self.log_event(f"Company paced: {company_raw} — {detail}", level="info")
                return

        # 3. Strict Pre-Application Duplicate Check across ANY status
        posting_date = job_item.get("postingDate") or job_item.get("datePosted")
        app_url = job_item.get("applicationUrl") or job_item.get("url") or ""
        with session_scope() as db:
            is_strict_dup, dup_job, dup_reason = is_strict_duplicate_processed(
                db, company_raw, title_raw, posting_date, app_url, exclude_id=job_item.get("id")
            )
        if is_strict_dup and dup_job is not None:
            detail = dup_reason or f"Already processed in status {dup_job.get('status')}"
            apply_ineligibility(job_item, IneligibilityReason.DUPLICATE_APPLICATION, detail)
            job_item["lastError"] = detail
            self._record_checkpoint(job_item, CheckpointStep.SKIPPED, detail)
            with session_scope() as db:
                save_autopilot_job(db, job_item)
            self.log_event(
                f"Strict Duplicate: {company_raw} — {title_raw} ({detail})",
                level="warning",
            )
            return

        # 4. Standard already-submitted duplicate protection.
        #
        # Reads only the submitted rows that could match this job, rather than
        # reusing the company-cap step's full table load: that load is skipped
        # when the user clicked Apply, which left this check reading a variable
        # that was never assigned for exactly those jobs.
        with session_scope() as db:
            already_submitted = list_submitted_duplicate_candidates(db, job_item)
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

        # 5. One in-flight attempt per posting, enforced in the database.
        #
        # The per-record lease (claim_job_lock) cannot express this: the same
        # posting routinely has several records, and each would happily take its
        # own lease and submit concurrently to one employer. Keyed on the ATS
        # posting id so the board's various host shapes collapse to one claim.
        identity = application_identity(job_item)
        job_item["applicationIdentity"] = identity
        job_id = str(job_item.get("id") or "")
        with session_scope() as db:
            identity_claimed = claim_application_identity(db, identity, job_id)
        if not identity_claimed:
            detail = "Another attempt for this posting is already in flight"
            job_item["lastError"] = detail
            self._record_checkpoint(job_item, CheckpointStep.SKIPPED, detail)
            with session_scope() as db:
                save_autopilot_job(db, job_item)
            self.log_event(
                f"Concurrent attempt refused: {job_item.get('company')} — {job_item.get('title')} ({detail})",
                level="warning",
            )
            return

        attempt = (job_item.get("attemptCount") or 0) + 1
        job_item["attemptCount"] = attempt
        job_item["lastAttemptRunId"] = run_id
        # The marker describes *this* attempt. A record the user resolved by
        # hand and put back on the queue still carries the previous attempt's
        # marker, and leaving it would make the next pre-submit failure look
        # like a possible submission and park a job that is genuinely safe to
        # retry. The checkpoint history keeps the older attempt's trail.
        job_item.pop("submitAttemptedAt", None)
        job_item.pop("technicalFailure", None)
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

            # A transient error is only safe to retry while nothing has been sent.
            # NAVIGATION_TIMEOUT is transient and is also exactly what a board
            # throws while the confirmation page fails to render *after* the
            # submit click — retrying there reapplies to a posting the employer
            # may already have. The duplicate guards at the top of this method
            # cannot catch it, because they all exclude this job's own record.
            if (
                err_type in TRANSIENT_ERRORS
                and attempt < MAX_JOB_ATTEMPTS
                and not submit_was_attempted(job_item)
            ):
                delay = 2 if attempt == 1 else 5
                self.log_event(f"Transient error ({err_type}). Retrying attempt {attempt + 1} after {delay}s...", level="warning")
                await asyncio.sleep(delay)
                return await self._process_single_job_with_retries(run_id, job_item, worker_state)

            unproven_status, unproven_error = classify_unproven_outcome(job_item)
            job_item["status"] = unproven_status
            if unproven_status == AutopilotJobStatus.SUBMISSION_UNKNOWN.value:
                job_item["lastErrorType"] = unproven_error
                job_item["aiExplanation"] = explain_unknown_submission(job_item)
                self._record_checkpoint(
                    job_item, CheckpointStep.STAGED,
                    f"Submission unverified after {err_type}: {exc_detail}",
                )
                with self._run_update_lock:
                    with session_scope() as db:
                        save_autopilot_job(db, job_item)
                        r = get_autopilot_run(db, run_id)
                        if r:
                            r["submissionUnknownCount"] = (r.get("submissionUnknownCount") or 0) + 1
                            save_autopilot_run(db, r)
                self.log_event(
                    f"Submission unverified after {err_type}: {job_item.get('company')} — "
                    f"{job_item.get('title')}. Parked as SUBMISSION_UNKNOWN; no automatic retry.",
                    level="warning",
                )
                return

            job_item["aiExplanation"] = f"Failed due to error: {err_type} ({exc_detail})"
            self._record_checkpoint(job_item, CheckpointStep.FAILED, f"Failed on error: {err_type}")

            # Record in Diagnostic Error Store with correlation IDs
            error_store.record_error(
                error=f"{err_type}: {exc_detail}",
                service="autopilot",
                severity="error" if err_type != "BROWSER_CRASH" else "critical",
                stage="APPLY",
                retries=attempt,
                status="open",
                playwright_error=exc_detail if "playwright" in str(type(exc)).lower() or "browser" in err_type.lower() else None,
                logs=[f"Failed at {job_item.get('company')} — {job_item.get('title')}", f"Error: {exc_detail}"],
            )
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
        finally:
            # The claim guards one attempt at a time, not the posting forever —
            # whether this posting may be attempted again is decided by the job's
            # status (SUBMITTED and SUBMISSION_UNKNOWN both refuse), not by
            # holding a lease open. Releasing here keeps a crashed attempt from
            # stranding a posting until its lease expires.
            try:
                with session_scope() as db:
                    release_application_identity(db, identity, job_id)
            except Exception:
                logger.exception("Could not release the posting claim for %s", job_id)

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

        # Tier-1 guardrail. The operator's Top-20 dream companies are applied to
        # by hand, with full care, so an unattended batch must never drive their
        # forms. This is not a dead end — the posting is live and the operator
        # will submit it themselves — so it goes to MANUAL_REVIEW, the bucket for
        # "a human can still land this, automation never will".
        if self.tier_guardrails and is_tier_1(company):
            from app.services.application_assistant.ineligibility import apply_ineligibility

            reason_text = (
                f"{company} is a Tier-1 target company — reserved for a hand-written "
                f"application, so Autopilot will not submit it."
            )
            apply_ineligibility(job_item, IneligibilityReason.MANUAL_APPLICATION_REQUIRED, reason_text)
            # Unlike a CAPTCHA, this block is a setting rather than a property of
            # the posting. Leaving hasPersistentBlock set would keep the job out
            # of every retry path even after the operator turns the guardrail
            # off, so the hold has to be as reversible as the switch that made it.
            job_item["hasPersistentBlock"] = False
            self.log_event(
                f"{w_prefix}Tier-1 guardrail held {company} — {title} for manual application",
                level="warning",
                metadata={"slot": slot_idx, "company": company, "title": title,
                          "status": job_item.get("status"), "reason": reason_text},
            )
            self._record_checkpoint(job_item, CheckpointStep.SKIPPED, reason_text)
            with self._run_update_lock:
                with session_scope() as db:
                    save_autopilot_job(db, job_item)
            return

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

        # This whole load is pure data-fetching (no Playwright/browser interaction) but
        # used to run synchronously, directly on the event loop, inside `session_scope()`
        # — confirmed live via py-spy on 2026-09-15 as one of several call sites where the
        # batch loop's own per-job pipeline blocks the *entire server* (every other
        # request, `/health` included) for however long these DB reads take under
        # concurrent contention. Same fix as the other instances tonight: its own fresh
        # session, entirely inside a worker thread, so this step can never block the loop
        # regardless of how contended the database is at the time.
        def _load_submission_context() -> tuple[
            dict[str, Any], list[dict[str, Any]], dict[str, Any], dict[str, Any], list[dict[str, Any]], str
        ]:
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
            return profile, answer_lib, master_resume, documents, accomplishments, tailoring_mode

        profile, answer_lib, master_resume, documents, accomplishments, tailoring_mode = await asyncio.to_thread(
            _load_submission_context
        )

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

        # Postings the deterministic matcher could not settle get one optional
        # second opinion here. Most do not: `evaluate` checks cheaply first and
        # only reaches Gemini for a genuinely undecided posting, so this adds no
        # latency to the normal path. The gate can send a job to review; it can
        # never talk one into being applied to, and a Gemini outage produces
        # review rather than a failed run.
        gate = await self._gemini_match_gate(
            job_item, profile, base_match_score, _granular_log
        )
        if gate is not None and not gate.proceed:
            job_item.update(gate.to_job_fields())
            job_item["status"] = AutopilotJobStatus.NEEDS_REVIEW.value
            job_item["skipReason"] = gate.reason
            job_item["lastError"] = gate.reason
            job_item["aiExplanation"] = gate.reason
            self.log_event(
                f"{w_prefix}Staged {company} — {title} for review: {gate.reason}",
                level="warning",
                metadata={"slot": slot_idx, "company": company, "title": title,
                          "status": "NEEDS_REVIEW", "reason": gate.reason},
            )
            self._record_checkpoint(job_item, CheckpointStep.SKIPPED, gate.reason)
            with self._run_update_lock:
                with session_scope() as db:
                    save_autopilot_job(db, job_item)
            return
        if gate is not None:
            job_item.update(gate.to_job_fields())

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
        submit_bar = self.min_match_score
        start_mode = _tailoring_mode_for_score(base_match_score, tailoring_mode, submit_bar)
        _granular_log(
            f"Queue match {base_match_score:.0f}% -> tailoring mode '{start_mode}', "
            f"up to {MAX_TAILORING_ATTEMPTS} attempt(s) against a "
            f"{submit_bar:.0f}% bar"
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

                t_start = time.perf_counter()
                candidate_diff = await generate_role_tailoring_diff(
                    job_item,
                    profile,
                    master_resume,
                    mode=candidate_mode,
                    feedback_gaps=gaps or None,
                    documents=documents,
                    accomplishments=accomplishments,
                )
                t_duration_ms = (time.perf_counter() - t_start) * 1000
                score = float(candidate_diff.get("matchScore") or 0)
                rescored = bool(candidate_diff.get("matchRescored"))

                agent_tracker.record_agent_call(
                    name="generate_role_tailoring_diff",
                    agent_type="resume_tailor",
                    stage="TAILOR",
                    provider="ollama",
                    model=candidate_diff.get("tailoringModel") or "qwen3:4b-instruct",
                    duration_ms=t_duration_ms,
                    status="success" if not candidate_diff.get("tailoringFailed") else "error",
                    prompt_tokens=450,
                    completion_tokens=320,
                    metadata={
                        "attempt": attempt,
                        "mode": candidate_mode,
                        "score": score,
                        "changedBullets": candidate_diff.get("totalChanges"),
                    },
                    error=candidate_diff.get("tailoringError"),
                )

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

                if (score >= submit_bar or override or candidate_mode == "off") and resume_is_good:
                    if score < submit_bar and candidate_mode != "off":
                        _granular_log(
                            f"Explicit Apply overrides the match cutoff ({score:.0f}%); "
                            f"keeping {candidate_mode} tailoring and all eligibility checks"
                        )
                    elif candidate_mode == "off":
                        _granular_log(
                            f"Resume tailoring is off; proceeding with master resume (score {score:.0f}%)"
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
                        f"{score:.0f}% is below the {submit_bar:.0f}% bar; "
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
                f"Match score stayed below {submit_bar:.0f}% after "
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

        async def _record_submit_attempt() -> None:
            """Enforce the minimum submission gap, then persist the point of no
            return before the executor clicks submit.

            The wait is computed against the most recent `submitAttemptedAt`
            across every job (excluding this one), not just this job's own
            history — the goal is that no two submissions, to any company,
            land closer together than the configured gap. Runs on the
            Playwright thread, so it takes its own session for both the read
            and the write. The final write has to reach disk before the click
            returns, which is why this is awaited rather than fired and
            forgotten: if the process dies during the click, this row is what
            stops the job being retried.
            """
            def _last_attempt() -> str | None:
                with session_scope() as db:
                    return most_recent_submit_attempt(db, exclude_id=job_item.get("id"))

            last_attempt = await asyncio.to_thread(_last_attempt)
            wait_seconds = seconds_until_next_submission(last_attempt)
            if wait_seconds > 0:
                self.log_event(
                    f"{w_prefix}Pacing {company} — {title}: waiting "
                    f"{wait_seconds:.0f}s so this submission doesn't land right "
                    "after the last one",
                    level="info",
                    metadata={"slot": slot_idx, "company": company, "title": title},
                )
                await asyncio.sleep(wait_seconds)

            stamp = now_iso()
            job_item["submitAttemptedAt"] = stamp
            # The checkpoint entry is appended directly rather than through
            # _record_checkpoint: this runs on the Playwright thread, and
            # _record_checkpoint broadcasts onto the SSE asyncio queues, which
            # belong to the server's loop. Keeping this path to plain data plus
            # one DB write avoids a cross-thread queue write on the one code
            # path that must not fail.
            history = job_item.get("checkpointHistory")
            if not isinstance(history, list):
                history = []
                job_item["checkpointHistory"] = history
            history.append({
                "step": CheckpointStep.SUBMITTING.value,
                "timestamp": stamp,
                "details": "Final submit click issued",
            })
            job_item["currentStep"] = CheckpointStep.SUBMITTING.value

            def _write() -> None:
                with session_scope() as db:
                    save_autopilot_job(db, job_item)

            await asyncio.to_thread(_write)

        try:
            result = await asyncio.wait_for(
                execute_live_playwright_submission(
                    job_item=job_item,
                    profile=submission_profile,
                    answer_lib=answer_lib,
                    headless=headless_mode,
                    timeout_sec=PLAYWRIGHT_INNER_TIMEOUT,
                    log_callback=_granular_log,
                    on_submit_attempt=_record_submit_attempt,
                ),
                timeout=PLAYWRIGHT_WATCHDOG_TIMEOUT,
            )
        except asyncio.TimeoutError:
            # Say where it hung, not just that it did.
            #
            # A bare "watchdog timeout" is unactionable: it cannot distinguish a
            # page that never loaded from a form that filled fine and then sat
            # waiting on a verification email. The checkpoint history already
            # records how far the attempt got, so name that step - it is the
            # difference between "this board is slow" and "this board hangs at
            # submit".
            history = job_item.get("checkpointHistory") or []
            last_step = str(history[-1].get("step")) if history else "UNKNOWN"
            logger.error(
                "Playwright execution hard watchdog timed out for job %s at step %s",
                job_item.get("id"), last_step,
            )
            result = {
                "submitted": False,
                "error": (
                    f"Timed out after {PLAYWRIGHT_WATCHDOG_TIMEOUT:.0f}s while at "
                    f"{last_step} — the board did not finish this step in time"
                ),
                "evidence": {"timedOutAtStep": last_step},
            }

        if result.get("submitted"):
            if worker_state:
                worker_state.status = "submitting"
                worker_state.current_step = "SUBMITTED"
            job_item["status"] = AutopilotJobStatus.SUBMITTED.value
            job_item["submittedAt"] = job_item.get("submitAttemptedAt") or now_iso()
            # Confirmation read straight off the page is the strongest evidence
            # there is, and it arrives without waiting for anyone's mail server.
            # Recorded as evidence on the record rather than as a separate
            # status, so "still open" stays SUBMITTED minus REJECTED and no
            # existing count has to learn a new state.
            job_item["confirmedAt"] = now_iso()
            job_item["confirmationSource"] = result.get("submissionSource") or "browser"
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
            job_item["lastError"] = err_msg
            evidence = result.get("evidence", {}) or {}
            if evidence.get("unresolvedRequiredFields") or evidence.get("preSubmitValidationErrors"):
                job_item["lastErrorType"] = ApplicationErrorType.VALIDATION_ERROR.value
            elif "submit button not found" in err_msg.lower():
                job_item["lastErrorType"] = ApplicationErrorType.ELEMENT_NOT_FOUND.value
            else:
                job_item["lastErrorType"] = ApplicationErrorType.SUBMISSION_UNCERTAIN.value
            job_item["submissionEvidence"] = evidence

            # "Not confirmed" is not the same as "not sent". If the submit click
            # was already issued, this attempt may have reached the employer, and
            # FAILED is a retryable bucket — both /autopilot/reprocess-failed and
            # the in-run retry would put it straight back on the queue and apply a
            # second time. Park it where nothing retries it automatically instead.
            unproven_status, unproven_error = classify_unproven_outcome(job_item, result)
            job_item["status"] = unproven_status
            if unproven_error:
                job_item["lastErrorType"] = unproven_error
            job_item["aiExplanation"] = err_msg

            if unproven_status == AutopilotJobStatus.SUBMISSION_UNKNOWN.value:
                # Do not run the ineligibility classifier over one of these. Its
                # job is to explain why a posting could never be applied to, and
                # this posting may already have been applied to — filing it as a
                # dead end would hide an application the candidate might have
                # sent, which is the opposite of what the user needs to see.
                job_item["aiExplanation"] = explain_unknown_submission(job_item)
                self._record_checkpoint(
                    job_item, CheckpointStep.STAGED, f"Submission unverified: {err_msg}"
                )
                if worker_state:
                    worker_state.status = "done"
                    worker_state.current_step = "SUBMISSION_UNKNOWN"
                with self._run_update_lock:
                    with session_scope() as db:
                        save_autopilot_job(db, job_item)
                        r = get_autopilot_run(db, run_id)
                        if r:
                            r["submissionUnknownCount"] = (r.get("submissionUnknownCount") or 0) + 1
                            save_autopilot_run(db, r)
                self.log_event(
                    f"{w_prefix}Submission unverified for {company} — {title}: {err_msg}. "
                    "Parked as SUBMISSION_UNKNOWN; Autopilot will not retry it.",
                    level="warning",
                    metadata={
                        "slot": slot_idx, "company": company, "title": title,
                        "status": AutopilotJobStatus.SUBMISSION_UNKNOWN.value,
                        "submitAttemptedAt": job_item.get("submitAttemptedAt"),
                    },
                )
                return

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

        job_item["lastError"] = str(exc)
        job_item["lastErrorType"] = ApplicationErrorType.UNKNOWN_ERROR.value

        # Even here, where nothing is known about what went wrong, whether the
        # submit click had already been issued is known — and that is the only
        # thing that decides whether retrying is safe.
        unproven_status, unproven_error = classify_unproven_outcome(job_item)
        job_item["status"] = unproven_status
        if unproven_status == AutopilotJobStatus.SUBMISSION_UNKNOWN.value:
            job_item["lastErrorType"] = unproven_error
            job_item["aiExplanation"] = explain_unknown_submission(job_item)
            self._record_checkpoint(
                job_item, CheckpointStep.STAGED, f"Submission unverified: {exc}"
            )
        else:
            job_item["aiExplanation"] = f"Automation error: {exc}"
            self._record_checkpoint(job_item, CheckpointStep.FAILED, f"Unhandled exception: {exc}")

        with self._run_update_lock, session_scope() as db:
            save_autopilot_job(db, job_item)
            r = get_autopilot_run(db, run_id)
            if r:
                if unproven_status == AutopilotJobStatus.SUBMISSION_UNKNOWN.value:
                    r["submissionUnknownCount"] = (r.get("submissionUnknownCount") or 0) + 1
                else:
                    r["failedCount"] = (r.get("failedCount") or 0) + 1
                save_autopilot_run(db, r)
