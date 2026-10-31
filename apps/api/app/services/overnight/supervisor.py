"""Loop A — the Auto Apply supervisor. Deterministic, no model calls.

Every cycle (default 30 minutes) it observes the worker through the normal API,
decides with a pure function (`decide`), acts at most once, and records the
result and the next check. Policy, most important first:

* A run with an active worker is healthy: do nothing. Never restart it.
* More than one API process, or concurrency above 1: hold and flag. Two loops
  could claim the same queue.
* A run marked RUNNING whose loop died (every worker idle and no heartbeat for
  `stale_minutes`, e.g. after an API restart): ask the runner to resume it via
  POST /autopilot/start. The runner itself refuses to start a second loop when
  one is alive, and its stale-run recovery moves an interrupted APPLYING job to
  SUBMISSION_UNKNOWN when the submit was clicked, so this cannot double-apply.
* PAUSED because the queue ran dry, and the queue has jobs again: resume.
* PAUSED after a fatal worker infrastructure error: resume, at most
  `infra_resume_budget` times a night, with backoff.
* PAUSED by the user, browser missing, an unknown pause, or STOPPED: hold and
  flag for a human. The supervisor does not override a person's decision.
* No run at all: hold, unless the session was started with `auto_start`.
* API unreachable: record it; flag after two cycles. It never restarts the API.

Resumes go through the runner's start route only, so the live-apply gates,
rate limits, pacing and company caps all apply exactly as for a console start.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Any, Callable

from app.services.overnight.api_client import Api, ApiError, read_jobs, status_counts
from app.services.overnight.state import StateStore, memory_snapshot, now_iso, parse_iso

LOOP = "supervisor"

ACTIVE_WORKER = lambda w: str((w or {}).get("status") or "idle") not in ("idle", "done")  # noqa: E731

QUEUE_EMPTY_LOG = "Queue empty and no new postings"
INFRA_ERROR_LOG = "Fatal worker infrastructure error"
USER_PAUSE_LOG = "Autopilot run paused"

# Actions
NOTHING = "nothing"
RESUME = "resume"
START = "start"
HOLD = "hold"  # needs a human; flagged
WAIT = "wait"  # transient; check again next cycle


@dataclass
class Policy:
    interval_minutes: float = 30.0
    stale_minutes: float = 15.0
    infra_resume_budget: int = 3
    infra_backoff_minutes: float = 30.0
    queue_resume_budget: int = 8
    api_down_flag_after: int = 2
    auto_start: bool = False
    requeue_cap: int = 25  # per cycle, so a repaired group trickles in
    start_options: dict[str, Any] = field(default_factory=dict)


@dataclass
class Decision:
    action: str
    reason: str
    flag: bool = False


def _pause_cause(observation: dict[str, Any]) -> str:
    run = observation.get("run") or {}
    if run.get("pauseReason"):
        return "browser-missing"
    logs = list(observation.get("recentLogs") or []) + list(run.get("logs") or [])
    logs.sort(key=lambda entry: str((entry or {}).get("timestamp") or ""))
    for entry in reversed(logs):
        message = str((entry or {}).get("message") or "")
        if QUEUE_EMPTY_LOG in message:
            return "queue-empty"
        if INFRA_ERROR_LOG in message:
            return "infra-error"
        if message.startswith(USER_PAUSE_LOG):
            return "user"
    return "unknown"


def decide(
    observation: dict[str, Any],
    memory: dict[str, Any],
    policy: Policy,
    now: datetime | None = None,
) -> Decision:
    """Pure policy. `observation` is GET /autopilot/status plus `apiProcesses`
    (or `apiError`); `memory` is the supervisor's persisted state."""
    now = now or datetime.now(timezone.utc)

    if observation.get("apiError"):
        down = int(memory.get("apiDownCycles") or 0) + 1
        return Decision(WAIT, f"API unreachable ({observation['apiError']}); {down} cycle(s) in a row",
                        flag=down >= policy.api_down_flag_after)

    if int(observation.get("apiProcesses") or 1) > 1:
        return Decision(HOLD, f"{observation['apiProcesses']} API processes are running; only one may own the queue", True)
    if int(observation.get("concurrency") or 1) > 1:
        return Decision(HOLD, f"Worker concurrency is {observation['concurrency']}; overnight mode expects exactly 1", True)

    workers = observation.get("workers") or []
    if any(ACTIVE_WORKER(w) for w in workers):
        return Decision(NOTHING, "Worker is mid-application; healthy, leaving it alone")

    run = observation.get("run") or None
    status = str(observation.get("status") or (run or {}).get("status") or "STOPPED")
    queue = int(observation.get("queueSize") or 0)

    if run is None:
        if policy.auto_start and queue > 0 and not memory.get("autoStarted"):
            return Decision(START, f"No run exists and {queue} job(s) are queued; auto-start is on")
        return Decision(HOLD, "No autopilot run is active; start one from the console (or arm auto-start)", False)

    if status in ("RUNNING", "RECOVERING", "STARTING"):
        heartbeat = parse_iso(run.get("lastHeartbeatAt"))
        age_min = (now - heartbeat).total_seconds() / 60 if heartbeat else float("inf")
        if age_min < policy.stale_minutes:
            return Decision(NOTHING, f"Run {status}, between jobs (heartbeat {age_min:.0f} min ago)")
        return Decision(RESUME, f"Run says {status} but no worker is active and the heartbeat is {age_min:.0f} min old; the loop died")

    if status == "PAUSED":
        cause = _pause_cause(observation)
        if cause == "queue-empty":
            if queue <= 0:
                return Decision(NOTHING, "Paused on an empty queue; nothing queued yet")
            if int(memory.get("queueResumes") or 0) >= policy.queue_resume_budget:
                return Decision(HOLD, "Queue-empty resume budget used up for tonight; jobs are queued but keep re-pausing (company caps?)", True)
            return Decision(RESUME, f"Paused on an empty queue; {queue} job(s) are queued now")
        if cause == "infra-error":
            used = int(memory.get("infraResumes") or 0)
            if used >= policy.infra_resume_budget:
                return Decision(HOLD, f"Worker hit fatal infrastructure errors {used} times tonight; needs a human", True)
            last = parse_iso(memory.get("lastInfraResumeAt"))
            if last and now - last < timedelta(minutes=policy.infra_backoff_minutes * (2 ** max(used - 1, 0))):
                return Decision(WAIT, "Backing off before resuming after an infrastructure error")
            return Decision(RESUME, f"Paused after a fatal infrastructure error (resume {used + 1}/{policy.infra_resume_budget})")
        if cause == "browser-missing":
            return Decision(HOLD, "Paused because the browser is missing; install or restore it, then resume", True)
        if cause == "user":
            return Decision(HOLD, "Paused by the user; leaving it paused", False)
        return Decision(HOLD, "Paused for an unrecognised reason; not overriding it", True)

    if status == "PAUSING":
        return Decision(WAIT, "Run is pausing; check again next cycle")
    if status == "STOPPING":
        return Decision(WAIT, "Run is stopping; check again next cycle")
    return Decision(HOLD, f"Run is {status}; the supervisor only resumes runs it can prove were interrupted")


def count_api_processes() -> int:
    """API server processes on this machine (uvicorn serving app.main).

    Launcher wrappers are not counted (see `api_server_processes`). Dev servers
    with --reload are excluded: they are not the overnight worker.
    """
    from app.services.overnight.api_client import api_server_processes

    return sum(1 for s in api_server_processes() if not s["reload"])


def observe(api: Api, processes: Callable[[], int] = count_api_processes) -> dict[str, Any]:
    try:
        obs = dict(api.get("/autopilot/status") or {})
    except ApiError as exc:
        return {"apiError": str(exc)}
    try:
        obs["apiProcesses"] = processes()
    except Exception as exc:
        obs["apiProcessesError"] = str(exc)
    return obs


def _job_brief(job: dict[str, Any] | None) -> dict[str, Any] | None:
    if not job:
        return None
    return {k: job.get(k) for k in ("id", "company", "title", "status")}


def run_cycle(
    store: StateStore,
    api: Api,
    policy: Policy,
    jobs_reader: Callable[[], list[dict[str, Any]]] | None = read_jobs,
    processes: Callable[[], int] = count_api_processes,
    now: datetime | None = None,
    requeue: bool = True,
) -> dict[str, Any]:
    """One supervisor cycle: observe, decide, act once, record."""
    now = now or datetime.now(timezone.utc)
    memory = store.read("supervisor.json")
    obs = observe(api, processes)
    decision = decide(obs, memory, policy, now)
    outcome: dict[str, Any] = {"action": decision.action, "reason": decision.reason, "flag": decision.flag}

    if decision.action in (RESUME, START):
        options = dict(policy.start_options)
        try:
            result = api.post("/autopilot/start", options)
            outcome["result"] = "accepted"
            outcome["runStatus"] = (result or {}).get("status") if isinstance(result, dict) else None
            if decision.action == START:
                memory["autoStarted"] = True
            cause = _pause_cause(obs) if obs.get("status") == "PAUSED" else ""
            if cause == "infra-error":
                memory["infraResumes"] = int(memory.get("infraResumes") or 0) + 1
                memory["lastInfraResumeAt"] = now.isoformat(timespec="seconds")
            elif cause == "queue-empty":
                memory["queueResumes"] = int(memory.get("queueResumes") or 0) + 1
        except ApiError as exc:
            # 409 = the runner refused (gate closed, already running...). That
            # is its decision, recorded verbatim, never retried around.
            outcome["result"] = "refused" if exc.status == 409 else "error"
            outcome["detail"] = exc.body if exc.body is not None else str(exc)
            outcome["flag"] = True

    memory["apiDownCycles"] = int(memory.get("apiDownCycles") or 0) + 1 if obs.get("apiError") else 0

    # Requeue jobs of fixes a person has marked live, through the per-job
    # route (its refusal and duplicate checks apply). Skipped while the API is
    # down; the runner picks them up on its own schedule.
    if requeue and jobs_reader is not None and not obs.get("apiError"):
        try:
            from app.services.overnight.promotion import requeue_ready

            rq = requeue_ready(store, api, jobs_reader, cap=policy.requeue_cap)
            if rq.get("requeued") or rq.get("error"):
                outcome["requeue"] = rq
        except Exception as exc:
            outcome["requeueError"] = repr(exc)
            outcome["flag"] = True

    counts: dict[str, int] | None = None
    if jobs_reader is not None:
        try:
            counts = status_counts(jobs_reader())
        except Exception as exc:
            outcome["countsError"] = str(exc)
            outcome["flag"] = True

    previous = memory.get("counts") or {}
    delta = {k: counts.get(k, 0) - previous.get(k, 0) for k in ("SUBMITTED", "FAILED", "NEEDS_REVIEW", "MANUAL_REVIEW", "SUBMISSION_UNKNOWN")} if counts and previous else {}

    workers = obs.get("workers") or []
    snapshot = {
        "lastCycleAt": now.isoformat(timespec="seconds"),
        "nextCheckAt": (now + timedelta(minutes=policy.interval_minutes)).isoformat(timespec="seconds"),
        "lastDecision": outcome,
        "runStatus": obs.get("status"),
        "runId": (obs.get("run") or {}).get("id"),
        "workerStatus": [w.get("status") for w in workers],
        "activeJob": _job_brief(obs.get("activeJob")),
        "queueSize": obs.get("queueSize"),
        "apiProcesses": obs.get("apiProcesses"),
        "counts": counts or previous,
        "countsAtStart": memory.get("countsAtStart") or counts or {},
        "delta": delta,
        "resources": memory_snapshot(),
    }
    if outcome.get("result") != "error" and not obs.get("apiError"):
        snapshot["lastSuccessfulCycleAt"] = snapshot["lastCycleAt"]
    else:
        snapshot["lastSuccessfulCycleAt"] = memory.get("lastSuccessfulCycleAt")
    memory.update(snapshot)
    store.write("supervisor.json", memory)
    store.event(LOOP, "flag" if outcome["flag"] else decision.action, decision.reason, **{
        k: v for k, v in outcome.items() if k not in ("reason",)
    })
    return memory


def run_forever(
    store: StateStore,
    api: Api,
    policy: Policy,
    sleep: Callable[[float], None] = time.sleep,
    max_cycles: int | None = None,
    jobs_reader: Callable[[], list[dict[str, Any]]] | None = read_jobs,
    after_cycle: Callable[[dict[str, Any]], None] | None = None,
) -> None:
    """Loop until the stop file appears. Never waits on Loop B or any model.
    `after_cycle` (the CLI's report refresh) runs after each cycle; its failure
    is logged and flagged, never fatal."""
    with store.lock("supervisor", f"overnight supervisor (pid-locked) {now_iso()}"):
        store.event(LOOP, "start", f"Supervisor started; every {policy.interval_minutes:g} min")
        cycles = 0
        while not store.stop_requested():
            try:
                result = run_cycle(store, api, policy, jobs_reader=jobs_reader)
            except Exception as exc:  # a broken cycle is recorded, the loop goes on
                store.event(LOOP, "error", f"Cycle failed: {exc!r}", flag=True)
                result = {"error": repr(exc)}
            if after_cycle is not None:
                try:
                    after_cycle(result)
                except Exception as exc:
                    store.event(LOOP, "error", f"After-cycle hook failed: {exc!r}", flag=True)
            cycles += 1
            if max_cycles is not None and cycles >= max_cycles:
                break
            # Sleep in short slices so a stop request is honoured promptly.
            deadline = time.monotonic() + policy.interval_minutes * 60
            while time.monotonic() < deadline and not store.stop_requested():
                sleep(min(15.0, max(0.0, deadline - time.monotonic())))
        store.event(LOOP, "stop", "Supervisor stopped")
