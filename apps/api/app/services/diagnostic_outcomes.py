"""Autopilot outcome history: what happened in a window, and why.

Backs `/diagnostic/outcomes`. The aggregate `/metrics` endpoint only knows each
job's *current* status, which loses history: a job staged on day 3 and
submitted on day 20 looks like a single submission. This report counts
per-attempt outcome events from each job's `checkpointHistory` instead: every
SUBMITTED / STAGED / FAILED / SKIPPED checkpoint, with the timestamp it was
recorded. That makes any window up to the 30-day reporting limit accurate.

Jobs that never recorded an end-of-attempt checkpoint (rows marked INELIGIBLE by
the queue filters before they were ever claimed, or SUBMITTED by the
manual-submission reconciler) still count: each one becomes a single event,
dated by its last update and marked `synthetic`.

Reasons come from the checkpoint's own details, falling back to the job's
`lastError` when the details are generic ("Failed on error: UNKNOWN_ERROR").
They are bucketed coarsely. Dozens of DOM-verification messages differ only in
the blank field's label, so they share one bucket, and the labels are counted
separately in `topBlankFields`. An unrecognised reason keeps its own first-70-
characters bucket, so a new failure mode shows up as a new row rather than
disappearing into "other".
"""

from __future__ import annotations

import re
from collections import Counter
from datetime import datetime, timedelta, timezone
from typing import Any, Iterator

# Reporting limit. Job rows and their checkpoint history are never deleted by
# this report; the limit only bounds how far back a single request can reach.
MAX_WINDOW_DAYS = 30
MAX_WINDOW_HOURS = 24 * MAX_WINDOW_DAYS

OUTCOMES = ("SUBMITTED", "STAGED", "FAILED", "SKIPPED")
TERMINAL_STEPS = set(OUTCOMES)
EVENT_LIMIT = 1000
# An attempt span longer than this is not a real attempt: it means the claim
# and the outcome came from different runs (e.g. a killed attempt whose job
# was later short-circuited), so it is reported as untimed rather than skewing
# the averages. The per-job watchdog is 600 s, so real attempts sit far below.
MAX_ATTEMPT_SECONDS = 6 * 3600

_PERIOD_RE = re.compile(r"^(\d{1,3})([hd])$")


def parse_period_hours(period: str) -> int:
    """'12h' -> 12, '7d' -> 168. Raises ValueError outside 1h..30d."""
    match = _PERIOD_RE.match((period or "").strip().lower())
    if not match:
        raise ValueError("period must look like '12h' or '7d'")
    amount = int(match.group(1))
    hours = amount * 24 if match.group(2) == "d" else amount
    if hours < 1 or hours > MAX_WINDOW_HOURS:
        raise ValueError(f"period must be between 1h and {MAX_WINDOW_DAYS}d")
    return hours


# Ordered (pattern, label) pairs; first match wins. Order matters in two
# places: the DOM-verification bucket sits above the citizenship/US patterns
# because blank-field labels such as 'Citizenship Status*' would otherwise be
# misread as a posting requirement, and the named bot-protected boards sit
# above the generic reCAPTCHA pattern that also matches Okta's message.
_REASON_PATTERNS: list[tuple[re.Pattern[str], str]] = [
    (re.compile(r"BOT_PROTECTED_BOARD:\s*Roblox|reliably times out in careeros", re.I), "Roblox board times out (known bot-protected)"),
    (re.compile(r"BOT_PROTECTED_BOARD:\s*Okta|Okta uses reCAPTCHA", re.I), "Okta reCAPTCHA (known bot-protected)"),
    (re.compile(r"DOM Verification mismatch|Required fields? remain unfilled", re.I), "Required field left blank in the browser DOM"),
    (re.compile(r"No application form", re.I), "No application form on the posting page"),
    (re.compile(r"reCAPTCHA", re.I), "Blocked by reCAPTCHA"),
    (re.compile(r"DataDome", re.I), "Blocked by DataDome"),
    (re.compile(r"hCaptcha", re.I), "Blocked by hCaptcha"),
    (re.compile(r"Workday requires a candidate account", re.I), "Workday requires a candidate account"),
    (re.compile(r"Tier-1 target company", re.I), "Tier-1 company — reserved for hand-written application"),
    (re.compile(r"Defense/ITAR", re.I), "Defense/ITAR contractor (excluded per preference)"),
    (re.compile(r"outside the United States|does not match United States", re.I), "Location outside the United States"),
    (re.compile(r"\bintern(ship)?\b", re.I), "Internship (excluded)"),
    (re.compile(r"citizenship|clearance|does not sponsor", re.I), "Requires U.S. citizenship / clearance / no sponsorship"),
    (re.compile(r"Already applied", re.I), "Duplicate — already applied to this posting"),
    (re.compile(r"Second opinion", re.I), "Second-opinion match gate did not approve"),
    (re.compile(r"Match score stayed below", re.I), "Match score below the submit bar after tailoring"),
    (re.compile(r"Resume was not usefully tailored", re.I), "Resume not usefully tailored"),
    (re.compile(r"Resume tailoring fell back", re.I), "Resume tailoring fell back to the template"),
    (re.compile(r"not a Software Engineering role", re.I), "Non-SWE role (title filter)"),
    (re.compile(r"NAVIGATION_TIMEOUT|navigation timed out|page\.goto.*timeout", re.I), "Browser navigation timed out"),
    (re.compile(r"could not be verified|Submission unconfirmed|no confirmation page", re.I), "Submission could not be verified"),
    (re.compile(r"security code", re.I), "Greenhouse emailed-security-code step"),
    (re.compile(r"Frame was detached|Target (page, context or browser )?(has been )?closed|browser has been closed", re.I), "Browser page or frame closed mid-run"),
    (re.compile(r"Persistent (contradiction )?block", re.I), "Persistent contradiction block"),
    (re.compile(r"POSTING_EXPIRED|unlisted|removed by the employer|expired link", re.I), "Posting expired or unlisted"),
    (re.compile(r"contradiction", re.I), "Material contradiction with profile"),
    (re.compile(r"Unhandled exception|Unhandled automation error", re.I), "Unhandled automation exception"),
]

_WATCHDOG_RE = re.compile(r"Timed out after \d+s while at (\w+)", re.I)
_FIELD_LABEL_RE = re.compile(r"Required field '([^']+)'")
_GENERIC_DETAIL_RE = re.compile(
    r"^(Failed on error: \w+|Resolving form fields|Attempt \d+/\d+)$", re.I
)
_DETAIL_PREFIX_RE = re.compile(r"^(Failed:\s*|Staged for (Review|human review):\s*)", re.I)


def _categorize(raw: str) -> str:
    if not raw:
        return "No reason recorded"
    watchdog = _WATCHDOG_RE.search(raw)
    if watchdog:
        return f"Watchdog timeout at {watchdog.group(1)}"
    for pattern, label in _REASON_PATTERNS:
        if pattern.search(raw):
            return label
    return raw[:70] + ("…" if len(raw) > 70 else "")


def _timestamp(value: Any) -> datetime | None:
    if not value:
        return None
    try:
        dt = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except (ValueError, TypeError):
        return None
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


def _job_reason_text(job: dict[str, Any]) -> str:
    """Best explanation for a job's current status."""
    for key in ("lastError", "skipReason", "aiExplanation", "matchReason"):
        value = str(job.get(key) or "").strip()
        if value:
            return value
    history = job.get("checkpointHistory") or []
    if history and isinstance(history[-1], dict):
        return str(history[-1].get("details") or "").strip()
    return ""


def _event_reason_text(checkpoint: dict[str, Any], job: dict[str, Any]) -> str:
    detail = str(checkpoint.get("details") or "").strip()
    detail = _DETAIL_PREFIX_RE.sub("", detail)
    if not detail or _GENERIC_DETAIL_RE.match(detail):
        return _job_reason_text(job)
    return detail


_STATUS_TO_OUTCOME = {
    "SUBMITTED": "SUBMITTED",
    "NEEDS_REVIEW": "STAGED",
    "STAGED": "STAGED",
    "FAILED": "FAILED",
    "ERROR": "FAILED",
}


def _iter_events(
    jobs: list[dict[str, Any]], start: datetime, end: datetime
) -> Iterator[tuple[dict[str, Any], str]]:
    """Yield (event, full_reason_text) for every outcome recorded in [start, end]."""
    for job in jobs:
        history = [c for c in (job.get("checkpointHistory") or []) if isinstance(c, dict)]
        terminal = [c for c in history if c.get("step") in TERMINAL_STEPS]
        base = {
            "jobId": job.get("id") or "",
            "company": job.get("company") or "",
            "title": job.get("title") or "",
            "currentStatus": job.get("status") or "",
            "matchScore": job.get("matchScore"),
            "applicationUrl": job.get("applicationUrl") or "",
        }
        if terminal:
            # Walk the history in order so each outcome can be timed against the
            # attempt that produced it: from that attempt's JOB_CLAIMED, or, for
            # paths that record no claim (a persistent-block short-circuit), from
            # the first checkpoint after the previous outcome.
            attempt_start: datetime | None = None
            segment_start: datetime | None = None
            for checkpoint in history:
                ts = _timestamp(checkpoint.get("timestamp"))
                if ts is None:
                    continue
                step = checkpoint.get("step")
                if segment_start is None:
                    segment_start = ts
                if step == "JOB_CLAIMED":
                    attempt_start = ts
                if step not in TERMINAL_STEPS:
                    continue
                began = attempt_start or segment_start
                duration = (ts - began).total_seconds() if began else None
                if duration is not None and not (0 <= duration <= MAX_ATTEMPT_SECONDS):
                    duration = None
                attempt_start = None
                segment_start = None
                if not (start <= ts <= end):
                    continue
                outcome = str(step)
                raw = "" if outcome == "SUBMITTED" else _event_reason_text(checkpoint, job)
                yield {**base, "timestamp": ts.isoformat(), "outcome": outcome,
                       "reason": "" if outcome == "SUBMITTED" else _categorize(raw),
                       "detail": raw[:300],
                       "durationSec": round(duration, 1) if duration is not None else None,
                       "synthetic": False}, raw
            continue

        status = job.get("status")
        if status in (None, "", "QUEUED", "APPLYING"):
            continue
        ts = _timestamp(job.get("submittedAt") or job.get("updatedAt") or job.get("createdAt"))
        if ts is None or not (start <= ts <= end):
            continue
        outcome = _STATUS_TO_OUTCOME.get(str(status), "SKIPPED")
        raw = "" if outcome == "SUBMITTED" else _job_reason_text(job)
        yield {**base, "timestamp": ts.isoformat(), "outcome": outcome,
               "reason": "" if outcome == "SUBMITTED" else _categorize(raw),
               "detail": raw[:300], "durationSec": None, "synthetic": True}, raw


def _count_reasons(items: list[tuple[str, str]], top_n: int = 12) -> list[dict[str, Any]]:
    """items: (reason label, example url)."""
    counter: Counter[str] = Counter()
    example: dict[str, str] = {}
    for label, url in items:
        counter[label] += 1
        if url:
            example.setdefault(label, url)
    return [
        {"reason": label, "count": count, "exampleUrl": example.get(label, "")}
        for label, count in counter.most_common(top_n)
    ]


def _bucket_keys(start: datetime, end: datetime, hourly: bool) -> list[str]:
    step = timedelta(hours=1) if hourly else timedelta(days=1)
    cursor = start.replace(minute=0, second=0, microsecond=0)
    if not hourly:
        cursor = cursor.replace(hour=0)
    keys: list[str] = []
    while cursor <= end:
        keys.append(_bucket_key(cursor, hourly))
        cursor += step
    return keys


def _bucket_key(ts: datetime, hourly: bool) -> str:
    ts = ts.astimezone(timezone.utc)
    return ts.strftime("%Y-%m-%dT%H:00Z") if hourly else ts.strftime("%Y-%m-%d")


ALL_STATUSES = (
    "QUEUED", "APPLYING", "SUBMITTED", "NEEDS_REVIEW", "STAGED",
    "MANUAL_REVIEW", "INELIGIBLE", "FAILED", "ERROR", "SKIPPED",
)


def _duration_stats(values: list[float]) -> dict[str, Any]:
    if not values:
        return {"count": 0, "avgSec": None, "medianSec": None, "p90Sec": None, "maxSec": None, "totalSec": 0}
    ordered = sorted(values)
    n = len(ordered)

    def percentile(p: float) -> float:
        k = (n - 1) * p
        lo = int(k)
        hi = min(lo + 1, n - 1)
        return ordered[lo] + (ordered[hi] - ordered[lo]) * (k - lo)

    return {
        "count": n,
        "avgSec": round(sum(ordered) / n, 1),
        "medianSec": round(percentile(0.5), 1),
        "p90Sec": round(percentile(0.9), 1),
        "maxSec": round(ordered[-1], 1),
        "totalSec": round(sum(ordered), 1),
    }


def build_outcomes_report(
    all_jobs: list[dict[str, Any]],
    *,
    hours: int,
    now: datetime,
    event_limit: int = EVENT_LIMIT,
) -> dict[str, Any]:
    start = now - timedelta(hours=hours)
    hourly = hours <= 48

    pairs = list(_iter_events(all_jobs, start, now))
    pairs.sort(key=lambda pair: pair[0]["timestamp"], reverse=True)
    events = [event for event, _ in pairs]

    outcome_counts = Counter(event["outcome"] for event in events)

    blank_fields: Counter[str] = Counter()
    for event, raw in pairs:
        if event["outcome"] in ("STAGED", "FAILED"):
            for field in _FIELD_LABEL_RE.findall(raw):
                blank_fields[field.strip()] += 1

    window_reasons = {
        outcome: _count_reasons(
            [(e["reason"], e["applicationUrl"]) for e in events if e["outcome"] == outcome]
        )
        for outcome in ("STAGED", "FAILED", "SKIPPED")
    }

    touched_ids = {event["jobId"] for event in events}
    touched_jobs = [job for job in all_jobs if job.get("id") in touched_ids]
    current_counts = Counter(job.get("status") or "UNKNOWN" for job in touched_jobs)

    def _current(statuses: set[str]) -> list[dict[str, Any]]:
        return _count_reasons([
            (_categorize(_job_reason_text(job)), job.get("applicationUrl") or "")
            for job in touched_jobs if job.get("status") in statuses
        ])

    series_index = {key: {"bucket": key, **{o: 0 for o in OUTCOMES}} for key in _bucket_keys(start, now, hourly)}
    for event in events:
        ts = _timestamp(event["timestamp"])
        if ts is None:
            continue
        bucket = series_index.get(_bucket_key(ts, hourly))
        if bucket is not None:
            bucket[event["outcome"]] += 1

    all_time = Counter(job.get("status") or "UNKNOWN" for job in all_jobs)

    timed = [e for e in events if e.get("durationSec") is not None]
    duration_stats = {"ALL": _duration_stats([e["durationSec"] for e in timed])}
    for outcome in OUTCOMES:
        duration_stats[outcome] = _duration_stats(
            [e["durationSec"] for e in timed if e["outcome"] == outcome]
        )
    slowest = sorted(timed, key=lambda e: e["durationSec"], reverse=True)[:10]

    return {
        "durationStats": duration_stats,
        "slowestEvents": slowest,
        "hours": hours,
        "maxDays": MAX_WINDOW_DAYS,
        "windowStart": start.isoformat(),
        "windowEnd": now.isoformat(),
        "bucketUnit": "hour" if hourly else "day",
        "updatedAt": now.isoformat(),
        "allTimeStatusCounts": {s: all_time.get(s, 0) for s in ALL_STATUSES},
        "windowOutcomeCounts": {o: outcome_counts.get(o, 0) for o in OUTCOMES},
        "windowJobsTouched": len(touched_ids),
        "windowCurrentStatusCounts": {s: current_counts.get(s, 0) for s in ALL_STATUSES},
        "windowReasons": window_reasons,
        "currentStatusReasons": {
            "MANUAL_REVIEW": _current({"MANUAL_REVIEW"}),
            "NEEDS_REVIEW": _current({"NEEDS_REVIEW", "STAGED"}),
            "FAILED": _current({"FAILED", "ERROR"}),
            "INELIGIBLE": _current({"INELIGIBLE"}),
        },
        "topBlankFields": [{"field": f, "count": c} for f, c in blank_fields.most_common(10)],
        "series": list(series_index.values()),
        "events": events[:event_limit],
        "eventsTotal": len(events),
        "eventsTruncated": len(events) > event_limit,
    }
