"""Promotion of validated fixes, and requeue of repaired groups once live.

The user's safeguard, enforced here: the improvement loop never touches the live
Auto Apply process. A fix the improver validated in its own worktree moves on
only when

1. the worker is idle (no active job, run not RUNNING/RECOVERING/STARTING/
   PAUSING/STOPPING),
2. the target tree (the prod-readiness worktree) has no tracked changes and is
   on the expected branch, never `main`,
3. the fix cherry-picks cleanly onto the target's current HEAD in a throwaway
   integration worktree, and every gate (compile, the fix's tests, the overnight
   tests, submission guards, production security gates) passes there.

Only then is the target fast-forwarded (`git merge --ff-only`, never a reset or
a forced checkout). That is "promoted", not "live": the live API runs from its
own tree and only a person moves code there (merge to main + restart). After
that person runs `mark-live`, the supervisor requeues the group's jobs through
the normal per-job route `/autopilot/jobs/{id}/reprocess`, which re-applies the
submission-outcome refusal and the strict duplicate check. Posting availability
is checked by the runner's own preflight when the job is picked up.

State: `promotion.json` (keyed by fix branch) is written by promotion and
`mark-live` under a short lock; `requeue.json` is written only by the
supervisor. No two processes write the same file without a lock.
"""

from __future__ import annotations

import shutil
import time
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

from app.services.overnight import gates
from app.services.overnight.api_client import Api, ApiError
from app.services.overnight.grouping import requeue_candidates
from app.services.overnight.state import LockHeld, StateStore, acquire_file_lock, now_iso, release_file_lock

LOOP = "promotion"
BUSY_STATUSES = frozenset({"RUNNING", "RECOVERING", "STARTING", "PAUSING", "STOPPING"})
FORBIDDEN_TARGET_BRANCHES = frozenset({"main", "master"})


@dataclass
class PromotionConfig:
    target_repo: Path
    target_branch: str = "prod-readiness"
    worktrees_dir: Path | None = None
    runner: gates.Runner = gates.subprocess_runner

    def __post_init__(self) -> None:
        self.target_repo = Path(self.target_repo)
        if self.worktrees_dir is None:
            self.worktrees_dir = self.target_repo.parent / "CareerOS-worktrees"


def _git(cfg: PromotionConfig, args: list[str], cwd: Path | None = None, timeout: float = 120) -> tuple[int, str]:
    return cfg.runner(["git", *args], cwd or cfg.target_repo, timeout)


def worker_idle(api: Api, processes: Callable[[], int]) -> tuple[bool, str]:
    """True only when it is provable that no application is in flight."""
    from app.services.overnight.supervisor import ACTIVE_WORKER

    try:
        obs = dict(api.get("/autopilot/status") or {})
    except ApiError as exc:
        try:
            running = processes()
        except Exception:
            running = -1
        if running == 0:
            return True, "API not running, so no worker"
        return False, f"cannot see the worker ({exc}); not promoting blind"
    status = str(obs.get("status") or "")
    if status in BUSY_STATUSES:
        return False, f"run is {status}"
    if obs.get("activeJob") or any(ACTIVE_WORKER(w) for w in obs.get("workers") or []):
        return False, "a worker has an active job"
    return True, f"run is {status or 'absent'}, no active job"


@contextmanager
def _state_lock(store: StateStore, wait_s: float = 60.0):
    """Short lock for read-modify-write of promotion.json."""
    path = store.path("locks/promotion-state.lock")
    deadline = time.monotonic() + wait_s
    while True:
        try:
            acquire_file_lock(path, "promotion.json writer")
            break
        except LockHeld:
            if time.monotonic() > deadline:
                raise
            time.sleep(0.5)
    try:
        yield
    finally:
        release_file_lock(path)


def state(store: StateStore) -> dict[str, Any]:
    doc = store.read("promotion.json")
    doc.setdefault("fixes", {})
    return doc


def awaiting(store: StateStore) -> list[dict[str, Any]]:
    """Validated fixes from the improver that promotion has not handled yet."""
    done = state(store)["fixes"]
    fixes = (store.read("improver.json").get("fixes") or [])
    return [f for f in fixes if f.get("step") == "validated" and f.get("branch") and f.get("commit")
            and f["branch"] not in done]


def _record(store: StateStore, fix: dict[str, Any], outcome: str, detail: str, **extra: Any) -> dict[str, Any]:
    with _state_lock(store):
        return _record_locked(store, fix, outcome, detail, **extra)


def _record_locked(store: StateStore, fix: dict[str, Any], outcome: str, detail: str, **extra: Any) -> dict[str, Any]:
    doc = state(store)
    entry = {
        "branch": fix.get("branch"),
        "commit": fix.get("commit"),
        "signature": fix.get("signature"),
        "category": fix.get("category"),
        "status": outcome,
        "detail": detail[:600],
        "at": now_iso(),
        **extra,
    }
    doc["fixes"][fix["branch"]] = {**doc["fixes"].get(fix["branch"], {}), **entry}
    store.write("promotion.json", doc)
    store.event(LOOP, outcome, f"{fix.get('signature')}: {detail}"[:600], branch=fix.get("branch"))
    return entry


def _target_problem(cfg: PromotionConfig) -> str | None:
    code, branch = _git(cfg, ["rev-parse", "--abbrev-ref", "HEAD"])
    branch = branch.strip()
    if code != 0:
        return f"cannot read target branch: {branch[-200:]}"
    if branch in FORBIDDEN_TARGET_BRANCHES:
        return f"target is on '{branch}'; overnight promotion never writes to it"
    if branch != cfg.target_branch:
        return f"target is on '{branch}', expected '{cfg.target_branch}'"
    code, dirty = _git(cfg, ["status", "--porcelain", "--untracked-files=no"])
    if code != 0:
        return f"git status failed: {dirty[-200:]}"
    if dirty.strip():
        return "target has uncommitted tracked changes; not touching it"
    return None


def promote_one(
    store: StateStore, cfg: PromotionConfig, api: Api, processes: Callable[[], int], fix: dict[str, Any]
) -> dict[str, Any]:
    idle, why = worker_idle(api, processes)
    if not idle:
        return {"skipped": f"worker busy: {why}"}
    problem = _target_problem(cfg)
    if problem:
        return {"skipped": problem}

    _, target_head = _git(cfg, ["rev-parse", "HEAD"])
    target_head = target_head.strip()
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d%H%M%S")
    integ = cfg.worktrees_dir / f"overnight-integrate-{stamp}"
    cfg.worktrees_dir.mkdir(parents=True, exist_ok=True)
    code, out = _git(cfg, ["worktree", "add", "--detach", str(integ), target_head])
    if code != 0:
        return _record(store, fix, "rejected", f"integration worktree failed: {out.strip()[-300:]}")
    try:
        code, out = _git(cfg, ["-c", "user.name=CareerOS overnight", "-c", "user.email=overnight@careeros.local",
                               "cherry-pick", fix["commit"]], integ)
        if code != 0:
            _git(cfg, ["cherry-pick", "--abort"], integ)
            return _record(store, fix, "conflict", f"does not apply on {target_head[:9]}: {out.strip()[-300:]}")
        _, new_head = _git(cfg, ["rev-parse", "HEAD"], integ)
        new_head = new_head.strip()
        _, names = _git(cfg, ["diff", "--name-only", target_head, new_head], integ)
        changed = [n for n in names.splitlines() if n.strip()]
        tests = [p.split("apps/api/", 1)[1] for p in changed if p.startswith("apps/api/tests/test_")]
        report = gates.standard_gates(integ / "apps" / "api", tests + list(gates.OVERNIGHT_TESTS), cfg.runner)
        if not report.ok:
            failed = "; ".join(f"{r.name}: {r.detail}" for r in report.failed())
            return _record(store, fix, "rejected", f"gates failed on integration — {failed}", gates=report.to_dict())

        # The gates take minutes; check the worker and the target again.
        idle, why = worker_idle(api, processes)
        if not idle:
            return {"skipped": f"worker became busy during gates: {why}"}
        problem = _target_problem(cfg)
        _, head_now = _git(cfg, ["rev-parse", "HEAD"])
        if problem or head_now.strip() != target_head:
            return {"skipped": problem or "target moved during gates; will retry"}
        code, out = _git(cfg, ["merge", "--ff-only", new_head])
        if code != 0:
            return _record(store, fix, "rejected", f"fast-forward refused: {out.strip()[-300:]}")
        return _record(store, fix, "promoted",
                       f"fast-forwarded {cfg.target_branch} to {new_head[:9]}; NOT live until a person deploys it",
                       promotedCommit=new_head, gates=report.to_dict(), liveAt=None)
    finally:
        _git(cfg, ["worktree", "remove", "--force", str(integ)])
        if integ.exists():
            shutil.rmtree(integ, ignore_errors=True)
        _git(cfg, ["worktree", "prune"])


def promote_ready(store: StateStore, cfg: PromotionConfig, api: Api, processes: Callable[[], int]) -> list[dict[str, Any]]:
    """Promote every awaiting fix, oldest first; stop at the first skip."""
    results = []
    with store.lock("promotion", "overnight promotion"):
        for fix in awaiting(store):
            result = promote_one(store, cfg, api, processes, fix)
            results.append({"branch": fix["branch"], **result})
            if "skipped" in result:
                store.event(LOOP, "wait", f"{fix['branch']}: {result['skipped']}")
                break
    return results


def mark_live(store: StateStore, branch: str, note: str = "") -> dict[str, Any]:
    """A person confirms the fix is running in the live API. Enables requeue."""
    with _state_lock(store):
        return _mark_live_locked(store, branch, note)


def _mark_live_locked(store: StateStore, branch: str, note: str) -> dict[str, Any]:
    doc = state(store)
    entry = doc["fixes"].get(branch)
    if entry is None:
        fix = next((f for f in store.read("improver.json").get("fixes") or []
                    if f.get("branch") == branch and f.get("step") == "validated"), None)
        if fix is None:
            raise KeyError(f"No validated fix on branch {branch}")
        entry = {"branch": branch, "commit": fix.get("commit"), "signature": fix.get("signature"),
                 "category": fix.get("category"), "status": "validated"}
    entry["liveAt"] = now_iso()
    entry["liveNote"] = note
    doc["fixes"][branch] = entry
    store.write("promotion.json", doc)
    store.event(LOOP, "live", f"{entry.get('signature')}: marked live by a person", branch=branch)
    return entry


def requeue_ready(
    store: StateStore, api: Api, jobs_reader: Callable[[], list[dict[str, Any]]], cap: int = 25
) -> dict[str, Any]:
    """Requeue jobs of live fixes through the normal per-job route.

    Candidates are re-derived from a fresh read each time (same signature,
    eligible, not sent, no pending questions). A job is requeued at most once per
    fix: if it fails the same way again, the fix did not work for it and it stays
    in review instead of looping.
    """
    live = [e for e in state(store)["fixes"].values() if e.get("liveAt") and e.get("signature")]
    if not live:
        return {"requeued": 0}
    book = store.read("requeue.json")
    book.setdefault("fixes", {})
    jobs = jobs_reader()
    total = 0
    summary: dict[str, Any] = {}
    for fix in live:
        entry = book["fixes"].setdefault(fix["branch"], {"signature": fix["signature"], "requeued": [], "refused": {}})
        tried = set(entry["requeued"]) | set(entry["refused"].keys())
        for job in requeue_candidates(jobs, fix["signature"]):
            if total >= cap:
                break
            job_id = str(job.get("id"))
            if job_id in tried:
                continue
            try:
                result = api.post(f"/autopilot/jobs/{job_id}/reprocess") or {}
            except ApiError as exc:
                if exc.status is None:  # API down: stop, try next cycle
                    summary["error"] = str(exc)
                    break
                result = {"success": False, "message": f"HTTP {exc.status}: {exc.body}"}
            if result.get("success"):
                entry["requeued"].append(job_id)
                total += 1
            else:
                entry["refused"][job_id] = str(result.get("message") or "refused")[:200]
        summary[fix["branch"]] = {"requeued": len(entry["requeued"]), "refused": len(entry["refused"])}
        if "error" in summary:
            break
    book["updatedAt"] = now_iso()
    store.write("requeue.json", book)
    if total:
        store.event(LOOP, "requeue", f"Requeued {total} job(s) for live fixes", detail=summary)
    summary["requeued"] = total
    return summary
