"""A minimum gap between consecutive submissions.

Autopilot processes the queue sequentially by default (`AUTOPILOT_APPLY_CONCURRENCY`
defaults to 1), but "sequential" only means one attempt runs at a time — it says
nothing about how long each one takes. A posting with a short, simple form can be
opened, filled, and submitted in well under a minute, and with no minimum gap
enforced, two such submissions could land seconds apart. To whatever a human or
an ATS's own fraud heuristics observe on the other end, that reads as automated in
a way a single submission does not: a real applicant does not finish one
application and start typing into the next one three seconds later.

The gap is enforced once, right before the actual submit click
(`autopilot_runner.py`'s `_record_submit_attempt`, already the hook that persists
`submitAttemptedAt` durably) — not between every step of the pipeline. Claiming a
job, opening the page, filling the form, and resolving questions all proceed at
full speed; only the click that creates an externally-visible timestamp is paced.

This is a global gap across every company, deliberately separate from
`company_cap.py`'s per-company rate limits: that module controls how many
applications one employer receives in a window, this one controls how far apart
any two submissions are in time, regardless of which employers they're to.
"""

from __future__ import annotations

from datetime import datetime, timezone

#: How far apart two consecutive submissions must land.
MIN_SUBMISSION_GAP_SECONDS = 300


def _parse(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except (TypeError, ValueError):
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)


def seconds_until_next_submission(
    last_submit_attempted_at: str | None,
    *,
    now: datetime | None = None,
    gap_seconds: int = MIN_SUBMISSION_GAP_SECONDS,
) -> float:
    """How long to wait before the next submit click, in seconds.

    0 when there is no prior submission, when the last one is unparseable, or
    when the gap has already elapsed — never negative. A malformed timestamp
    fails open (no wait) rather than blocking Autopilot on bad data; the gap
    is a politeness measure, not a safety guard, so this is the direction to
    fail in.
    """
    now = now or datetime.now(timezone.utc)
    last = _parse(last_submit_attempted_at)
    if last is None:
        return 0.0
    elapsed = (now - last).total_seconds()
    remaining = gap_seconds - elapsed
    return max(0.0, remaining)
