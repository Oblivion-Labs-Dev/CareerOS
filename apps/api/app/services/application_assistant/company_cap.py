"""How many applications one employer may receive, across three rolling windows.

Applying to forty roles at one company in a week reads as spray-and-pray to the
people on the other end, and it crowds the queue with one employer while better
matches elsewhere wait. The cap is a pacing rule, not a judgement about the
postings.

**Three tiers apply at once** — 5 a day, 10 a week, 20 a month — and a company is
paced when *any* of them is exhausted. A single monthly figure was not enough on
its own: twenty a month still allowed the entire month's allowance to be spent
in one overnight batch, which is the exact pattern the cap exists to prevent.

**Fresh postings get a little more room.** A role published in the last 24 hours
is worth applying to promptly — that is when an application is most likely to be
read — so a posting that fresh is measured against every tier raised by
``FRESH_POSTING_BONUS``: 8 a day, 13 a week, 23 a month. The bonus lifts every
tier rather than only the daily one, so the monthly ceiling stays a real ceiling:
a company can never receive more than 23 applications in 30 days however fresh
its postings are. A posting with no known publication date does not get the
bonus, because we cannot claim it is fresh without inventing the fact.

Three further things follow, and they are the rest of the design:

**A capped posting is not ineligible.** Nothing is wrong with it — it is simply
not this employer's turn. It stays ``QUEUED`` and carries ``companyCapHoldUntil``,
the moment the employer's window frees up again. Filing these as ``INELIGIBLE``
would bury live postings in a terminal bucket the user works through expecting
dead ends, and it would need a second pass to dig them back out.

**When the window rolls, the best matches go first.** The runner already claims
in ``queue_priority_score`` order, so held jobs re-enter that same ordering on
their own. There is no separate queue and no second ranking to keep in sync.

**Windows are rolling, not calendar.** A company that took five applications this
afternoon frees them one at a time over the following afternoon, rather than the
whole allowance reappearing at midnight. ``until`` is keyed on the *oldest*
submission still inside the binding window, which is the first one due to age
out, and when several tiers are exhausted the latest release wins because that is
the one that actually governs.

Counting is derived from the job rows themselves rather than kept in a separate
per-company counter. A counter would be a second source of truth that drifts the
moment a job is re-marked, deduplicated or reconciled, and would need a backfill
and a repair path; deriving cannot drift. To keep that affordable,
``build_submission_index`` walks the jobs **once** into ``company -> timestamps``
and every tier answers from that by bisection. The previous shape rescanned every
job once per company per check and measured 844 ms on a real 5,375-job table;
this measures under 10 ms.
"""

from __future__ import annotations

import bisect
import re
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any, Iterable, Mapping, Sequence

#: (name, allowance, window length in days). Ordered narrowest window first so
#: that messages naturally name the tightest constraint when several bind.
COMPANY_CAP_TIERS: tuple[tuple[str, int, int], ...] = (
    ("day", 5, 1),
    ("week", 10, 7),
    ("month", 20, 30),
)

#: Extra allowance at every tier for a posting published very recently.
FRESH_POSTING_BONUS = 3

#: How new a posting must be to earn that bonus.
FRESH_POSTING_WINDOW_HOURS = 24

#: The widest window, which bounds how much history has to be kept.
COMPANY_CAP_WINDOW_DAYS = max(days for _name, _cap, days in COMPANY_CAP_TIERS)

#: The monthly allowance. Retained under its original name because callers and
#: tests refer to "the" cap when they mean the widest one.
COMPANY_APPLICATION_CAP = next(
    cap for _name, cap, days in COMPANY_CAP_TIERS if days == COMPANY_CAP_WINDOW_DAYS
)

#: Statuses that count against an employer's allowance. Only applications that
#: actually reached the employer count: a job in review or one that failed was
#: never sent, so holding the queue against it would pace on work that never
#: happened. SUBMISSION_UNKNOWN counts because it may well have been sent, and
#: pacing should fail safe.
_COUNTED_STATUSES = frozenset({"SUBMITTED", "REJECTED", "SUBMISSION_UNKNOWN"})


@dataclass(frozen=True)
class TierHold:
    """Which tier paced an employer, and when it frees up again."""

    tier: str
    cap: int
    window_days: int
    used: int
    until: datetime
    fresh: bool = False


def normalise_company(name: Any) -> str:
    """Company names as they compare: lowercase, alphanumerics only.

    Boards spell one employer several ways ("DoorDash USA", "Doordashusa"), and
    a cap that treats those as different employers is not a cap. This also
    delivers the case-insensitive matching the rule requires.
    """
    return re.sub(r"[^a-z0-9]+", "", str(name or "").lower())


def _parse(value: Any) -> datetime | None:
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except (TypeError, ValueError):
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)


def posting_date(job: Mapping[str, Any]) -> datetime | None:
    """When the employer published the role, if the board told us.

    ``datePosted`` is the alias carried by some sources; the rest of the
    codebase already reads both, so this does too.
    """
    return _parse(job.get("postingDate")) or _parse(job.get("datePosted"))


def is_fresh_posting(job: Mapping[str, Any], *, now: datetime | None = None) -> bool:
    """Whether the role was published inside the bonus window.

    Absent a publication date this is ``False``. Treating an undated posting as
    fresh would hand out the bonus on a guess, and most postings in the table
    have no date at all.
    """
    published = posting_date(job)
    if published is None:
        return False
    now = now or datetime.now(timezone.utc)
    if published > now:
        # A future-dated posting is a board quirk, not freshness evidence.
        return False
    return (now - published) <= timedelta(hours=FRESH_POSTING_WINDOW_HOURS)


def _submitted_at(job: Mapping[str, Any]) -> datetime | None:
    return _parse(job.get("submittedAt")) or _parse(job.get("updatedAt"))


def build_submission_index(
    jobs: Iterable[Mapping[str, Any]], *, now: datetime | None = None
) -> dict[str, list[datetime]]:
    """``company key -> in-window submission times, oldest first``.

    One pass over the jobs, so a batch pays this once instead of once per
    employer per tier. Anything older than the widest window is dropped here,
    which is what keeps the per-company lists short.
    """
    now = now or datetime.now(timezone.utc)
    cutoff = now - timedelta(days=COMPANY_CAP_WINDOW_DAYS)

    index: dict[str, list[datetime]] = {}
    for job in jobs:
        if (job.get("status") or "").upper() not in _COUNTED_STATUSES:
            continue
        key = normalise_company(job.get("company"))
        if not key:
            continue
        when = _submitted_at(job)
        if when is None or when < cutoff:
            continue
        index.setdefault(key, []).append(when)

    for stamps in index.values():
        stamps.sort()
    return index


def submission_times(
    jobs: Iterable[Mapping[str, Any]], company: str, *, now: datetime | None = None
) -> list[datetime]:
    """When this employer's in-window applications were sent, oldest first."""
    key = normalise_company(company)
    if not key:
        return []
    return build_submission_index(jobs, now=now).get(key, [])


def blocking_tier(
    stamps: Sequence[datetime], *, now: datetime | None = None, fresh: bool = False
) -> TierHold | None:
    """The tier pacing this employer, or ``None`` if every tier has room.

    ``stamps`` must be sorted oldest first. When more than one tier is
    exhausted the one that frees up *latest* is returned, because that is the
    constraint actually governing the wait.
    """
    now = now or datetime.now(timezone.utc)
    bonus = FRESH_POSTING_BONUS if fresh else 0

    worst: TierHold | None = None
    for name, base_cap, window_days in COMPANY_CAP_TIERS:
        cap = base_cap + bonus
        window = timedelta(days=window_days)
        # Everything at or after this point is inside the tier's window.
        used = len(stamps) - bisect.bisect_left(stamps, now - window)
        if used < cap:
            continue
        # The cap-th most recent submission is the one whose expiry opens a slot.
        releases = stamps[len(stamps) - cap] + window
        if worst is None or releases > worst.until:
            worst = TierHold(
                tier=name,
                cap=cap,
                window_days=window_days,
                used=used,
                until=releases,
                fresh=fresh,
            )
    return worst


def company_hold(
    jobs: Iterable[Mapping[str, Any]],
    company: str,
    *,
    job: Mapping[str, Any] | None = None,
    now: datetime | None = None,
) -> TierHold | None:
    """Whether this employer is paced right now, and by which tier.

    Pass ``job`` when the hold is being decided for a specific posting, so a
    freshly published one is measured against the raised caps.
    """
    now = now or datetime.now(timezone.utc)
    stamps = submission_times(jobs, company, now=now)
    fresh = bool(job is not None and is_fresh_posting(job, now=now))
    return blocking_tier(stamps, now=now, fresh=fresh)


def hold_until(
    jobs: Iterable[Mapping[str, Any]],
    company: str,
    *,
    job: Mapping[str, Any] | None = None,
    now: datetime | None = None,
) -> datetime | None:
    """When this employer can be applied to again, or ``None`` if it can now."""
    hold = company_hold(jobs, company, job=job, now=now)
    return hold.until if hold else None


def describe_hold(company: str, hold: TierHold, *, now: datetime | None = None) -> str:
    """The sentence shown on a held job.

    Names the tier that actually bound, so the countdown in the UI matches the
    reason given for it.
    """
    now = now or datetime.now(timezone.utc)
    days = max(0, (hold.until - now).days)
    when = hold.until.date().isoformat()
    unit = "day" if days == 1 else "days"
    span = "day" if hold.window_days == 1 else f"{hold.window_days} days"
    allowance = f"{hold.cap} per {hold.tier}"
    if hold.fresh:
        allowance += f", including the +{FRESH_POSTING_BONUS} for a posting published today"
    return (
        f"{company} has had {hold.used} applications in the last {span} "
        f"(limit {allowance}). Waiting {days} more {unit} (until {when}); "
        "this posting stays in the queue and the best-matching held roles go first."
    )


def apply_hold(job: dict[str, Any], hold: TierHold, *, now: datetime | None = None) -> None:
    """Mark a job as paced, without changing its status.

    Deliberately leaves ``status`` alone. The job is queued and stays queued;
    only the hold fields change, so the moment the window rolls it is picked up
    by the ordinary claim path with no un-doing required.
    """
    job["companyCapHoldUntil"] = hold.until.isoformat()
    job["companyCapTier"] = hold.tier
    job["companyCapReason"] = describe_hold(
        str(job.get("company") or "this company"), hold, now=now
    )


def clear_hold(job: dict[str, Any]) -> None:
    """Drop the hold once the window has rolled."""
    job.pop("companyCapHoldUntil", None)
    job.pop("companyCapTier", None)
    job.pop("companyCapReason", None)


def is_held(job: Mapping[str, Any], *, now: datetime | None = None) -> bool:
    """Whether a recorded hold is still in force."""
    until = _parse(job.get("companyCapHoldUntil"))
    if until is None:
        return False
    return until > (now or datetime.now(timezone.utc))


def partition_by_cap(
    queued: list[dict[str, Any]],
    all_jobs: Iterable[Mapping[str, Any]],
    *,
    now: datetime | None = None,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Split queued jobs into (applyable now, held by a cap).

    ``queued`` is expected in claim order, best match first, and that order is
    preserved in both halves — so the first jobs released when a window rolls
    are the best-matching ones, without ranking anything a second time.

    The index is built once for the whole batch, and each admitted job is added
    to it immediately, so a single pass cannot push an employer past a cap
    before any of its applications has been recorded as submitted.
    """
    now = now or datetime.now(timezone.utc)
    index = build_submission_index(all_jobs, now=now)

    applyable: list[dict[str, Any]] = []
    held: list[dict[str, Any]] = []

    for job in queued:
        key = normalise_company(job.get("company"))
        if not key:
            applyable.append(job)
            continue

        stamps = index.setdefault(key, [])
        hold = blocking_tier(stamps, now=now, fresh=is_fresh_posting(job, now=now))
        if hold is not None:
            apply_hold(job, hold, now=now)
            held.append(job)
        else:
            # Spend the slot now, so later jobs in this same batch see it.
            bisect.insort(stamps, now)
            clear_hold(job)
            applyable.append(job)

    return applyable, held
