"""Overnight command: `python -m app.services.overnight <command>` from apps/api.

    start          launch both loops detached (supervisor + improver)
    stop [--now]   ask both loops to exit at their next safe boundary
                   (--now also ends our own loop processes; the improver
                   cleans up its half-done attempt on the next start)
    resume         clear the stop flag and launch again, keeping the session
    status         locks, last cycles, current improvement, flags (JSON)
    supervise      run Loop A in the foreground   (start uses this)
    improve        run Loop B in the foreground   (start uses this)
    supervise-once / improve-once   one cycle, for inspection
    groups         recompute and print the failure groups (read-only)
    report         rebuild morning-report.md and dashboard.html
    promote        try to promote validated fixes now (idle worker only)
    mark-live BRANCH [--note ...]   a person confirms a fix runs in the live API

Nothing here writes a job row: the supervisor acts through the normal API and
everything else reads the DB read-only.
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from functools import partial
from pathlib import Path
from typing import Any

from app.services.overnight import improver as improver_mod
from app.services.overnight import promotion, report, supervisor
from app.services.overnight.api_client import DEFAULT_BASE_URL, HttpApi, default_db_path, read_jobs
from app.services.overnight.state import API_DIR, DEFAULT_STATE_DIR, StateStore, now_iso, pid_alive

LOOPS = ("supervisor", "improver")


def _jobs_reader(args: argparse.Namespace):
    return partial(read_jobs, Path(args.db)) if args.db else read_jobs


def _policy(args: argparse.Namespace) -> supervisor.Policy:
    return supervisor.Policy(interval_minutes=args.interval, auto_start=args.auto_start)


def _improver_cfg(args: argparse.Namespace) -> improver_mod.ImproverConfig:
    return improver_mod.ImproverConfig(jobs_reader=_jobs_reader(args))


def _promotion_cfg() -> promotion.PromotionConfig:
    return promotion.PromotionConfig(target_repo=improver_mod.REPO_ROOT)


def _refresh_report(store: StateStore, args: argparse.Namespace) -> None:
    report.write_outputs(store, _jobs_reader(args))


# ---- detached launch -------------------------------------------------------
def _spawn(store: StateStore, args: argparse.Namespace, loop: str) -> int:
    cmd = [sys.executable, "-m", "app.services.overnight", "--state-dir", str(store.root),
           "--api", args.api, "--interval", str(args.interval)]
    if args.db:
        cmd += ["--db", args.db]
    if args.auto_start:
        cmd.append("--auto-start")
    cmd.append("supervise" if loop == "supervisor" else "improve")
    log = store.path(f"{loop}.log").open("a", encoding="utf-8")
    kwargs: dict[str, Any] = {}
    if os.name == "nt":
        kwargs["creationflags"] = (subprocess.DETACHED_PROCESS | subprocess.CREATE_NEW_PROCESS_GROUP
                                   | subprocess.CREATE_NO_WINDOW)
    else:
        kwargs["start_new_session"] = True
    proc = subprocess.Popen(cmd, cwd=str(API_DIR), stdout=log, stderr=subprocess.STDOUT,
                            stdin=subprocess.DEVNULL, **kwargs)
    return proc.pid


def cmd_start(store: StateStore, args: argparse.Namespace, resume: bool = False) -> dict[str, Any]:
    running = {loop: store.lock_holder(loop) for loop in LOOPS}
    if all(running.values()):
        return {"started": [], "alreadyRunning": running}
    store.clear_stop()
    session = store.read("session.json")
    if not resume or not session.get("startedAt"):
        session = {"startedAt": now_iso()}
    session.update(resumedAt=now_iso() if resume else None, api=args.api,
                   db=str(args.db or default_db_path()), autoStart=args.auto_start,
                   intervalMinutes=args.interval, pids=session.get("pids") or {})
    started = []
    for loop in LOOPS:
        if running[loop]:
            continue
        session["pids"][loop] = _spawn(store, args, loop)
        started.append(loop)
    store.write("session.json", session)
    store.event("cli", "resume" if resume else "start", f"Launched {', '.join(started)}", pids=session["pids"])
    return {"started": started, "pids": session["pids"], "stateDir": str(store.root),
            "dashboard": str(store.path("dashboard.html"))}


def cmd_stop(store: StateStore, now: bool) -> dict[str, Any]:
    store.request_stop()
    store.event("cli", "stop", "Stop requested" + (" (now)" if now else ""))
    ended = []
    if now:
        import psutil

        for loop in LOOPS:
            held = store.lock_holder(loop)
            # Only a process that holds our own loop lock is ever ended.
            if held and pid_alive(held.get("pid")):
                try:
                    proc = psutil.Process(int(held["pid"]))
                    for child in proc.children(recursive=True):
                        child.kill()
                    proc.kill()
                    ended.append({"loop": loop, "pid": held["pid"]})
                except psutil.Error as exc:
                    ended.append({"loop": loop, "pid": held["pid"], "error": str(exc)})
    return {"stopRequested": True, "ended": ended,
            "note": "loops exit at their next boundary" if not now else "the improver recovers on next start"}


def cmd_status(store: StateStore) -> dict[str, Any]:
    sup = store.read("supervisor.json")
    imp = store.read("improver.json")
    events = store.events()
    return {
        "stateDir": str(store.root),
        "session": store.read("session.json"),
        "stopRequested": store.stop_requested(),
        "running": {loop: store.lock_holder(loop) for loop in (*LOOPS, "promotion")},
        "supervisor": {k: sup.get(k) for k in ("lastCycleAt", "nextCheckAt", "lastSuccessfulCycleAt",
                                               "lastDecision", "runStatus", "queueSize", "activeJob", "delta")},
        "improver": {"current": imp.get("current"), "usage": imp.get("usage"),
                     "fixes": [{k: f.get(k) for k in ("step", "signature", "branch", "commit", "detail")}
                               for f in (imp.get("fixes") or [])[-10:]]},
        "promotion": promotion.state(store)["fixes"],
        "recentFlags": [e for e in events if e.get("kind") == "flag" or e.get("flag")][-10:],
    }


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="python -m app.services.overnight", description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--state-dir", default=str(DEFAULT_STATE_DIR))
    p.add_argument("--db", default=None, help="SQLite DB to read (default: the live API's DB, read-only)")
    p.add_argument("--api", default=DEFAULT_BASE_URL)
    p.add_argument("--interval", type=float, default=30.0, help="supervisor interval, minutes")
    p.add_argument("--auto-start", action="store_true",
                   help="supervisor may start a run when none exists and jobs are queued (off by default)")
    sub = p.add_subparsers(dest="command", required=True)
    for name in ("start", "resume", "status", "supervise", "improve", "supervise-once", "improve-once",
                 "groups", "report", "promote"):
        sub.add_parser(name)
    s = sub.add_parser("stop")
    s.add_argument("--now", action="store_true")
    m = sub.add_parser("mark-live")
    m.add_argument("branch")
    m.add_argument("--note", default="")
    return p


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    store = StateStore(Path(args.state_dir))
    api = HttpApi(base_url=args.api)
    c = args.command
    out: Any
    if c == "start":
        out = cmd_start(store, args)
    elif c == "resume":
        out = cmd_start(store, args, resume=True)
    elif c == "stop":
        out = cmd_stop(store, args.now)
    elif c == "status":
        out = cmd_status(store)
    elif c == "supervise":
        supervisor.run_forever(store, api, _policy(args), jobs_reader=_jobs_reader(args),
                               after_cycle=lambda _r: _refresh_report(store, args))
        return 0
    elif c == "improve":
        cfg = _improver_cfg(args)

        def after(_result: dict[str, Any]) -> None:
            try:
                promotion.promote_ready(store, _promotion_cfg(), api, supervisor.count_api_processes)
            finally:
                _refresh_report(store, args)

        improver_mod.run_forever(store, cfg, after_cycle=after)
        return 0
    elif c == "supervise-once":
        out = supervisor.run_cycle(store, api, _policy(args), jobs_reader=_jobs_reader(args))
        _refresh_report(store, args)
    elif c == "improve-once":
        with store.lock("improver", "overnight improver (once)"):
            out = improver_mod.Improver(store, _improver_cfg(args)).cycle()
        _refresh_report(store, args)
    elif c == "groups":
        groups = improver_mod.Improver(store, _improver_cfg(args)).compute_groups()
        out = [{**g.to_dict(), "eligibleIds": f"{g.eligible} ids (see groups.json)"} for g in groups[:25]]
    elif c == "report":
        out = report.write_outputs(store, _jobs_reader(args))
    elif c == "promote":
        out = promotion.promote_ready(store, _promotion_cfg(), api, supervisor.count_api_processes)
    elif c == "mark-live":
        out = promotion.mark_live(store, args.branch, args.note)
    else:  # pragma: no cover - argparse rejects unknown commands
        return 2
    print(json.dumps(out, indent=2, default=str))
    return 0


if __name__ == "__main__":
    sys.exit(main())
