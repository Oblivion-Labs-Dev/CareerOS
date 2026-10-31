"""Morning report (Markdown) and a static, self-refreshing dashboard (HTML).

Both are rebuilt from the state files and a read-only DB snapshot; nothing here
writes a job. Numbers that cannot be known are shown as "unknown", never 0.

"Verified submissions" counts jobs in SUBMITTED: since production-readiness
pass 2 the runner only sets SUBMITTED with confirmation evidence; an unproven
submit lands in SUBMISSION_UNKNOWN, reported separately as a risk.
"""

from __future__ import annotations

import html
import json
from datetime import datetime, timedelta, timezone
from typing import Any, Callable

from app.services.overnight.state import StateStore, atomic_write_text, memory_snapshot, now_iso, parse_iso

REVIEW = ("NEEDS_REVIEW", "MANUAL_REVIEW")


def session_start(store: StateStore) -> datetime:
    started = parse_iso((store.read("session.json") or {}).get("startedAt"))
    return started or datetime.now(timezone.utc) - timedelta(hours=12)


def _since(job: dict[str, Any], key: str, start: datetime) -> bool:
    at = parse_iso(job.get(key))
    return at is not None and at >= start


def collect(store: StateStore, jobs_reader: Callable[[], list[dict[str, Any]]] | None) -> dict[str, Any]:
    start = session_start(store)
    sup = store.read("supervisor.json")
    imp = store.read("improver.json")
    groups = store.read("groups.json")
    promo = (store.read("promotion.json").get("fixes") or {})
    requeue = (store.read("requeue.json").get("fixes") or {})
    session = store.read("session.json")

    jobs: list[dict[str, Any]] | None = None
    jobs_error = None
    if jobs_reader is not None:
        try:
            jobs = jobs_reader()
        except Exception as exc:
            jobs_error = str(exc)

    requeued_ids = {i for e in requeue.values() for i in e.get("requeued") or []}
    metrics: dict[str, Any] = {k: None for k in (
        "attempted", "verifiedSubmissions", "failed", "newManualReviews", "submissionUnknown",
        "requeuedResolved", "queued")}
    if jobs is not None:
        by_id = {str(j.get("id")): j for j in jobs}
        metrics.update(
            attempted=sum(_since(j, "applicationStartedAt", start) for j in jobs),
            verifiedSubmissions=sum(j.get("status") == "SUBMITTED" and _since(j, "submittedAt", start) for j in jobs),
            failed=sum(j.get("status") == "FAILED" and _since(j, "updatedAt", start) for j in jobs),
            newManualReviews=sum(j.get("status") in REVIEW and _since(j, "updatedAt", start) for j in jobs),
            submissionUnknown=sum(j.get("status") == "SUBMISSION_UNKNOWN" and _since(j, "updatedAt", start) for j in jobs),
            requeuedResolved=sum((by_id.get(i) or {}).get("status") == "SUBMITTED" for i in requeued_ids),
            queued=sum(j.get("status") == "QUEUED" for j in jobs),
        )

    fixes = [f for f in imp.get("fixes") or [] if (parse_iso(f.get("finishedAt")) or start) >= start]
    validated = [f for f in fixes if f.get("step") == "validated"]
    gate_failures = [f for f in fixes if "tests failed" in str(f.get("detail") or "") or "gates failed" in str(f.get("detail") or "")]
    promoted = [e for e in promo.values() if e.get("status") == "promoted"]
    live = [e for e in promo.values() if e.get("liveAt")]
    awaiting_promo = [f for f in validated if f.get("branch") not in promo]
    promo_failures = [e for e in promo.values() if e.get("status") in ("rejected", "conflict")]
    code_groups = [g for g in groups.get("groups") or [] if g.get("kind") == "code"]
    remaining = sorted((g for g in code_groups if not g.get("blocked")), key=lambda g: -int(g.get("eligible") or 0))

    events = store.events(start)
    flags = [e for e in events if e.get("kind") == "flag" or e.get("flag")]
    usage = imp.get("usage") or {}
    return {
        "generatedAt": now_iso(),
        "sessionStart": start.isoformat(timespec="seconds"),
        "session": session,
        "metrics": metrics,
        "jobsError": jobs_error,
        "supervisor": sup,
        "improver": {
            "current": imp.get("current"),
            "fixes": fixes,
            "validated": validated,
            "awaitingPromotion": awaiting_promo,
            "gateFailures": gate_failures,
            "usage": usage,
        },
        "promotion": {"promoted": promoted, "live": live, "failures": promo_failures},
        "requeued": sum(len(e.get("requeued") or []) for e in requeue.values()),
        "requeueRefused": sum(len(e.get("refused") or {}) for e in requeue.values()),
        "groupsRepaired": len(live),
        "remaining": remaining[:3],
        "largestRemaining": remaining[0] if remaining else None,
        "groupsComputedAt": groups.get("computedAt"),
        "flags": flags[-20:],
        "resources": memory_snapshot(),
        "locks": {name: store.lock_holder(name) for name in ("supervisor", "improver", "promotion")},
    }


def _n(value: Any) -> str:
    return "unknown" if value is None else str(value)


def render_markdown(data: dict[str, Any]) -> str:
    m = data["metrics"]
    imp = data["improver"]
    usage = imp["usage"]
    lines = [
        "# CareerOS overnight report",
        "",
        f"Session from {data['sessionStart']} to {data['generatedAt']}.",
        "",
        "## Metrics",
        "",
        f"- Applications attempted: {_n(m['attempted'])}",
        f"- Verified submissions: {_n(m['verifiedSubmissions'])}",
        f"- Failed: {_n(m['failed'])}",
        f"- New manual reviews: {_n(m['newManualReviews'])}",
        f"- Manual reviews resolved by requeue (now submitted): {_n(m['requeuedResolved'])}",
        f"- Groups repaired (fix live and requeued): {data['groupsRepaired']}",
        f"- Jobs requeued: {data['requeued']} (refused by the requeue guard: {data['requeueRefused']})",
        f"- Fixes validated: {len(imp['validated'])} of {len(imp['fixes'])} attempts",
        f"- LLM usage: {usage.get('agentRuns', 0)} Claude runs, {usage.get('reviewRuns', 0)} Codex reviews, "
        f"${float(usage.get('costUsd') or 0):.2f} reported by Claude (Codex cost not reported)",
    ]
    if data.get("jobsError"):
        lines.append(f"- DB read failed, job metrics unknown: {data['jobsError']}")
    big = data["largestRemaining"]
    lines.append(f"- Largest remaining group: {big['signature']} ({big['eligible']} eligible)" if big
                 else "- Largest remaining group: none computed")

    lines += ["", "## Top remaining groups", ""]
    if data["remaining"]:
        for g in data["remaining"]:
            lines.append(f"1. **{g['signature']}**: {g['eligible']} eligible, score {g['score']}, "
                         f"attempts {g['attempts']}. Example: {str(g.get('sample_reason') or '')[:160]}")
    else:
        lines.append("No groups computed yet (run `groups`).")

    risks = []
    if m["submissionUnknown"]:
        risks.append(f"{m['submissionUnknown']} application(s) reached SUBMISSION_UNKNOWN this session: "
                     "check the employer's portal before any retry.")
    for e in data["flags"]:
        risks.append(f"{e.get('at')} [{e.get('loop')}] {e.get('message')}")
    for e in data["promotion"]["failures"]:
        risks.append(f"Promotion {e['status']} for {e.get('signature')}: {e.get('detail')}")
    lines += ["", "## Security and submission risks", ""]
    lines += [f"- {r}" for r in risks] or ["- None flagged."]

    lines += ["", "## Changes awaiting your approval", ""]
    pending = [(f.get("branch"), f.get("commit"), f.get("signature"), "validated, not promoted (worker was busy or target not clean)")
               for f in imp["awaitingPromotion"]]
    pending += [(e.get("branch"), e.get("promotedCommit"), e.get("signature"),
                 "promoted to prod-readiness; merge to main + restart, then `mark-live`")
                for e in data["promotion"]["promoted"] if not e.get("liveAt")]
    lines += [f"- `{b}` @ `{str(c or '')[:9]}`: {s}. {why}" for b, c, s, why in pending] or ["- Nothing awaiting approval."]

    lines += ["", "## Failed tests", ""]
    lines += [f"- {f.get('signature')}: {f.get('detail')}" for f in imp["gateFailures"]] or ["- None."]

    lines += ["", "## Branches and commits", ""]
    for f in imp["fixes"]:
        lines.append(f"- {f.get('step')}: {f.get('signature')} on `{f.get('branch')}`"
                     + (f" @ `{str(f.get('commit'))[:9]}`" if f.get("commit") else "")
                     + f". {str(f.get('detail') or '')[:200]}")
    if not imp["fixes"]:
        lines.append("- No improvement attempts this session.")
    return "\n".join(lines) + "\n"


_CSS = """
:root{--bg:#f6f3ee;--card:#fffdf9;--ink:#1d1b18;--muted:#5f5a52;--line:#e4ddd2;--accent:#2f6fde;--bad:#b3261e;--ok:#1f7a4d;--warn:#9a6700}
@media (prefers-color-scheme:dark){:root:not([data-theme=light]){--bg:#0d1117;--card:#161b22;--ink:#e8ebef;--muted:#a3acb7;--line:#2a313b;--accent:#6ea8ff;--bad:#ff7b72;--ok:#56d364;--warn:#e3b341}}
*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--ink);font:15px/1.5 system-ui,-apple-system,Segoe UI,sans-serif;padding:24px 16px}
main{max-width:1100px;margin:0 auto}h1{font-size:22px;margin:0 0 4px}.sub{color:var(--muted);margin:0 0 20px}
.grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(300px,1fr));gap:16px}
section{background:var(--card);border:1px solid var(--line);border-radius:12px;padding:16px 18px}
h2{font-size:13px;letter-spacing:.06em;text-transform:uppercase;color:var(--muted);margin:0 0 10px}
dl{display:grid;grid-template-columns:1fr auto;gap:6px 12px;margin:0}dt{color:var(--muted)}dd{margin:0;font-variant-numeric:tabular-nums;text-align:right;font-weight:600}
.ok{color:var(--ok)}.bad{color:var(--bad)}.warn{color:var(--warn)}ul{margin:0;padding-left:18px}li{margin:4px 0}
code{font-size:12px;word-break:break-all}
"""


def render_html(data: dict[str, Any]) -> str:
    e = html.escape
    sup = data["supervisor"] or {}
    m = data["metrics"]
    imp = data["improver"]
    cur = imp.get("current") or {}
    res = data["resources"]
    gates = ((cur.get("gates") or {}).get("results") or [])
    passed = sum(1 for g in gates if g.get("ok"))
    decision = (sup.get("lastDecision") or {})
    nxt = data["remaining"][0] if data["remaining"] else None
    if nxt and cur.get("signature") == nxt.get("signature") and len(data["remaining"]) > 1:
        nxt = data["remaining"][1]

    def row(label: str, value: Any, cls: str = "") -> str:
        return f"<dt>{e(label)}</dt><dd class='{cls}'>{e(_n(value))}</dd>"

    worker = ", ".join(sup.get("workerStatus") or []) or "unknown"
    active = sup.get("activeJob") or {}
    flag_cls = "bad" if decision.get("flag") else ""
    auto = "".join([
        row("Run status", sup.get("runStatus")),
        row("Worker", worker),
        row("Running application", f"{active.get('title')} @ {active.get('company')}" if active else "none"),
        row("Queued", m["queued"] if m["queued"] is not None else sup.get("queueSize")),
        row("Verified submissions", m["verifiedSubmissions"], "ok"),
        row("Failures", m["failed"], "bad" if m["failed"] else ""),
        row("New manual reviews", m["newManualReviews"]),
        row("Submission unknown", m["submissionUnknown"], "warn" if m["submissionUnknown"] else ""),
        row("Last decision", f"{decision.get('action')}: {decision.get('reason')}" if decision else None, flag_cls),
    ])
    improvement = "".join([
        row("Current group", cur.get("signature") or "idle"),
        row("Affected (eligible)", cur.get("eligible")),
        row("Step", cur.get("step")),
        row("Tests passed / failed", f"{passed} / {len(gates) - passed}" if gates else None),
        row("Fixes validated", len(imp["validated"])),
        row("Requeued", data["requeued"]),
        row("Next group", f"{nxt['signature']} ({nxt['eligible']})" if nxt else None),
    ])
    usage = imp["usage"]
    resources = "".join([
        row("RAM free", f"{res.get('ramAvailableMb')} MB of {res.get('ramTotalMb')} MB" if "ramAvailableMb" in res else None),
        row("CPU", f"{res.get('cpuPercent')}%" if "cpuPercent" in res else None),
        row("Model usage", f"{usage.get('agentRuns', 0)} Claude, {usage.get('reviewRuns', 0)} Codex, ${float(usage.get('costUsd') or 0):.2f}"),
        row("Last successful cycle", sup.get("lastSuccessfulCycleAt")),
        row("Next check", sup.get("nextCheckAt")),
        row("Supervisor", "running" if data["locks"].get("supervisor") else "stopped"),
        row("Improver", "running" if data["locks"].get("improver") else "stopped"),
    ])
    flags = "".join(f"<li><code>{e(str(f.get('at')))}</code> {e(str(f.get('message')))}</li>" for f in data["flags"][-8:]) or "<li>None</li>"
    return f"""<!doctype html><html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1"><meta http-equiv="refresh" content="60">
<title>CareerOS overnight</title><style>{_CSS}</style></head><body><main>
<h1>CareerOS overnight</h1><p class="sub">Updated {e(data['generatedAt'])}, session since {e(data['sessionStart'])}. Refreshes every minute.</p>
<div class="grid">
<section><h2>Auto Apply</h2><dl>{auto}</dl></section>
<section><h2>Improvement</h2><dl>{improvement}</dl></section>
<section><h2>Resources</h2><dl>{resources}</dl></section>
<section><h2>Flags</h2><ul>{flags}</ul></section>
</div></main></body></html>
"""


def write_outputs(store: StateStore, jobs_reader: Callable[[], list[dict[str, Any]]] | None) -> dict[str, str]:
    data = collect(store, jobs_reader)
    md = render_markdown(data)
    # Both loops refresh these; atomic writes so a reader never sees half a file.
    atomic_write_text(store.path("morning-report.md"), md)
    atomic_write_text(store.path("dashboard.html"), render_html(data))
    store.write("report.json", json.loads(json.dumps(data, default=str)))
    return {"report": str(store.path("morning-report.md")), "dashboard": str(store.path("dashboard.html"))}
