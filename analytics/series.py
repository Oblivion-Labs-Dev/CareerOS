"""Time buckets built from persisted job records; no synthetic samples."""
from datetime import datetime, timedelta, timezone


def timestamp(value):
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        return parsed.replace(tzinfo=timezone.utc) if parsed.tzinfo is None else parsed
    except (ValueError, TypeError):
        return None


def build_series(jobs, period, now=None):
    now = now or datetime.now(timezone.utc)
    seconds, count = {"1h": (300, 12), "24h": (3600, 24), "7d": (21600, 28)}[period]
    start = now - timedelta(seconds=seconds * count)
    buckets = [{"timestamp": (start + timedelta(seconds=i * seconds)).isoformat(), "submitted": 0, "failed": 0, "review": 0, "skipped": 0, "other": 0, "durationSec": None, "samples": 0} for i in range(count)]
    durations = [[] for _ in buckets]
    status_keys = {"SUBMITTED": "submitted", "FAILED": "failed", "ERROR": "failed", "STAGED": "review", "NEEDS_REVIEW": "review", "SKIPPED": "skipped"}
    for job in jobs:
        updated = timestamp(job.get("updatedAt") or job.get("createdAt"))
        if updated is None or updated < start or updated > now:
            continue
        index = min(count - 1, int((updated - start).total_seconds() // seconds))
        buckets[index][status_keys.get(job.get("status"), "other")] += 1
        times = sorted(t for cp in job.get("checkpointHistory", []) if (t := timestamp(cp.get("timestamp"))) is not None)
        if len(times) >= 2 and times[-1] > times[0]:
            durations[index].append((times[-1] - times[0]).total_seconds())
    for bucket, values in zip(buckets, durations):
        bucket["samples"] = len(values)
        bucket["durationSec"] = round(sum(values) / len(values), 1) if values else None
    return {"period": period, "bucketSeconds": seconds, "buckets": buckets, "updatedAt": now.isoformat(), "basis": "Current job status grouped by last update; duration is the recorded checkpoint span, not submission latency."}
