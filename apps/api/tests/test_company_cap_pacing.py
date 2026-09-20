"""At most 20 applications to one employer per rolling 30 days, as a hold.

A capped posting is live and wanted — it is simply not this employer's turn. It
must stay QUEUED with a countdown rather than being filed INELIGIBLE, and when
the window rolls the best-matching held postings must go first.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from app.services.application_assistant import company_cap
from app.services.application_assistant.company_cap import (
    COMPANY_APPLICATION_CAP,
    COMPANY_CAP_WINDOW_DAYS,
    hold_until,
    is_held,
    normalise_company,
    partition_by_cap,
    submission_times,
)

NOW = datetime(2026, 9, 19, 12, 0, tzinfo=timezone.utc)


def _submitted(company: str, days_ago: float, job_id: str = "") -> dict:
    return {
        "id": job_id or f"sub_{company}_{days_ago}",
        "company": company,
        "status": "SUBMITTED",
        "submittedAt": (NOW - timedelta(days=days_ago)).isoformat(),
    }


def _queued(company: str, score: float, job_id: str) -> dict:
    return {"id": job_id, "company": company, "status": "QUEUED", "matchScore": score}


# ── Counting the window ──────────────────────────────────────────────────────


def test_only_submissions_inside_the_window_count():
    jobs = [_submitted("Cloudflare", 5), _submitted("Cloudflare", 29.9), _submitted("Cloudflare", 31)]

    stamps = submission_times(jobs, "Cloudflare", now=NOW)

    assert len(stamps) == 2, "a 31-day-old application has aged out of the window"


def test_company_names_are_compared_loosely():
    """Boards spell one employer several ways; a cap fooled by that is no cap."""
    assert normalise_company("DoorDash USA") == normalise_company("doordashusa")

    jobs = [_submitted("DoorDash USA", 1), _submitted("doordashusa", 2), _submitted("Door-Dash  USA", 3)]
    assert len(submission_times(jobs, "DoorDash", now=NOW)) == 0
    assert len(submission_times(jobs, "DoorDash USA", now=NOW)) == 3


def test_unsent_applications_do_not_consume_the_allowance():
    """Pacing is about what reached the employer, not what was attempted."""
    jobs = [
        {"id": "a", "company": "Acme", "status": "NEEDS_REVIEW", "updatedAt": NOW.isoformat()},
        {"id": "b", "company": "Acme", "status": "FAILED", "updatedAt": NOW.isoformat()},
        {"id": "c", "company": "Acme", "status": "SKIPPED", "updatedAt": NOW.isoformat()},
    ]

    assert submission_times(jobs, "Acme", now=NOW) == []


def test_a_maybe_sent_application_does_consume_the_allowance():
    """SUBMISSION_UNKNOWN may well have reached the employer, so pace on it."""
    jobs = [{
        "id": "u", "company": "Acme", "status": "SUBMISSION_UNKNOWN",
        "submittedAt": NOW.isoformat(),
    }]

    assert len(submission_times(jobs, "Acme", now=NOW)) == 1


# ── The cap itself ───────────────────────────────────────────────────────────


def test_under_the_cap_there_is_no_hold():
    jobs = [_submitted("Acme", i, f"j{i}") for i in range(COMPANY_APPLICATION_CAP - 1)]

    assert hold_until(jobs, "Acme", now=NOW) is None


def test_at_the_cap_the_hold_expires_with_the_oldest_submission():
    """A rolling window frees one slot at a time, not all twenty at once."""
    jobs = [_submitted("Acme", i, f"j{i}") for i in range(COMPANY_APPLICATION_CAP)]
    oldest_days_ago = COMPANY_APPLICATION_CAP - 1

    until = hold_until(jobs, "Acme", now=NOW)

    assert until is not None
    expected = NOW - timedelta(days=oldest_days_ago) + timedelta(days=COMPANY_CAP_WINDOW_DAYS)
    assert abs((until - expected).total_seconds()) < 1


def test_the_hold_lifts_once_the_window_rolls():
    jobs = [_submitted("Acme", i, f"j{i}") for i in range(COMPANY_APPLICATION_CAP)]
    until = hold_until(jobs, "Acme", now=NOW)

    later = until + timedelta(minutes=1)
    assert hold_until(jobs, "Acme", now=later) is None


# ── Held, not disqualified ───────────────────────────────────────────────────


def test_a_capped_job_stays_queued_and_is_never_marked_ineligible():
    """The regression this exists for.

    Filing a live posting as INELIGIBLE buries it in a terminal bucket the user
    works through expecting genuine dead ends.
    """
    submitted = [_submitted("Acme", i, f"j{i}") for i in range(COMPANY_APPLICATION_CAP)]
    queued = [_queued("Acme", 90.0, "q1")]

    applyable, held = partition_by_cap(queued, submitted + queued, now=NOW)

    assert applyable == []
    assert len(held) == 1
    job = held[0]
    assert job["status"] == "QUEUED"
    assert job.get("ineligibilityReason") is None
    assert "INELIGIBLE" not in str(job.get("status"))


def test_a_held_job_carries_a_countdown_the_user_can_read():
    submitted = [_submitted("Acme", 0, f"j{i}") for i in range(COMPANY_APPLICATION_CAP)]
    queued = [_queued("Acme", 90.0, "q1")]

    _, held = partition_by_cap(queued, submitted + queued, now=NOW)
    job = held[0]

    assert is_held(job, now=NOW) is True
    assert job["companyCapHoldUntil"]
    assert str(COMPANY_CAP_WINDOW_DAYS) in job["companyCapReason"]
    assert "queue" in job["companyCapReason"].lower()


def test_the_hold_clears_itself_when_the_window_rolls():
    submitted = [_submitted("Acme", 29.5, f"j{i}") for i in range(COMPANY_APPLICATION_CAP)]
    queued = [_queued("Acme", 90.0, "q1")]

    _, held = partition_by_cap(queued, submitted + queued, now=NOW)
    assert held and is_held(held[0], now=NOW)

    later = NOW + timedelta(days=1)
    applyable, still_held = partition_by_cap(queued, submitted + queued, now=later)

    assert still_held == []
    assert [j["id"] for j in applyable] == ["q1"]
    assert applyable[0].get("companyCapHoldUntil") is None


# ── Best matches go first ────────────────────────────────────────────────────


def test_released_jobs_keep_best_match_first_ordering():
    """The runner sorts by queue_priority_score before calling this, and that
    order must survive — the twenty that go next are the twenty best."""
    queued = [_queued("Acme", s, f"q{s}") for s in (95.0, 88.0, 70.0, 55.0)]

    applyable, held = partition_by_cap(queued, queued, now=NOW)

    assert [j["id"] for j in applyable] == ["q95.0", "q88.0", "q70.0", "q55.0"]
    assert held == []


def test_one_batch_is_bounded_by_the_daily_tier_not_the_monthly_one():
    """A single pass must not spend the whole month's allowance at once.

    This is why the daily tier exists. Everything admitted in one batch lands
    inside the same day, so five is the most one employer can take from it,
    even though twenty a month is also permitted. The running tally has to
    include what this same pass already allowed, or the cap only holds between
    batches.
    """
    daily_cap = dict((name, cap) for name, cap, _days in company_cap.COMPANY_CAP_TIERS)["day"]
    queued = [_queued("Acme", 100.0 - i, f"q{i}") for i in range(COMPANY_APPLICATION_CAP + 5)]

    applyable, held = partition_by_cap(queued, queued, now=NOW)

    assert len(applyable) == daily_cap
    assert len(held) == len(queued) - daily_cap
    # And the ones that got through are the best-scoring ones.
    assert [j["id"] for j in applyable] == [f"q{i}" for i in range(daily_cap)]


def test_one_capped_employer_does_not_block_others():
    capped = [_submitted("Acme", i, f"j{i}") for i in range(COMPANY_APPLICATION_CAP)]
    queued = [_queued("Acme", 99.0, "acme1"), _queued("Globex", 60.0, "globex1")]

    applyable, held = partition_by_cap(queued, capped + queued, now=NOW)

    assert [j["id"] for j in applyable] == ["globex1"]
    assert [j["id"] for j in held] == ["acme1"]


def test_a_job_with_no_company_is_not_held():
    queued = [{"id": "nameless", "company": "", "status": "QUEUED"}]

    applyable, held = partition_by_cap(queued, queued, now=NOW)

    assert [j["id"] for j in applyable] == ["nameless"]
    assert held == []


# ── The three tiers ──────────────────────────────────────────────────────────


@pytest.mark.parametrize(
    "tier,cap,window_days",
    [(name, cap, days) for name, cap, days in company_cap.COMPANY_CAP_TIERS],
)
def test_each_tier_paces_on_its_own(tier, cap, window_days):
    """Every tier binds independently; exhausting any one of them holds."""
    # Spread them across the tier's window so no *narrower* tier is the cause.
    spacing = window_days / cap
    jobs = [_submitted("Acme", i * spacing, f"j{i}") for i in range(cap)]

    hold = company_cap.company_hold(jobs, "Acme", now=NOW)

    assert hold is not None, f"{cap} applications in {window_days} day(s) must pace the {tier} tier"
    assert hold.used >= cap


def test_the_daily_tier_binds_before_the_monthly_one():
    """Five today is paced even though twenty a month is far from spent."""
    jobs = [_submitted("Acme", 0.1 * i, f"j{i}") for i in range(5)]

    hold = company_cap.company_hold(jobs, "Acme", now=NOW)

    assert hold is not None
    assert hold.tier == "day"
    assert hold.until <= NOW + timedelta(days=1)


def test_four_today_still_has_room():
    jobs = [_submitted("Acme", 0.1 * i, f"j{i}") for i in range(4)]

    assert company_cap.company_hold(jobs, "Acme", now=NOW) is None


def test_when_several_tiers_bind_the_latest_release_governs():
    """Holding only until the daily window rolls would release into a full
    weekly window and pace again an hour later."""
    # Ten in one day exhausts the daily (5) and weekly (10) tiers at once.
    jobs = [_submitted("Acme", 0.01 * i, f"j{i}") for i in range(10)]

    hold = company_cap.company_hold(jobs, "Acme", now=NOW)

    assert hold is not None
    assert hold.tier == "week", "the weekly window frees up last, so it governs"
    assert hold.until > NOW + timedelta(days=1)


# ── The fresh-posting override ───────────────────────────────────────────────


def _fresh(company: str, job_id: str, hours_old: float = 2.0) -> dict:
    job = _queued(company, 90.0, job_id)
    job["postingDate"] = (NOW - timedelta(hours=hours_old)).isoformat()
    return job


def test_a_posting_published_today_gets_extra_room():
    """The whole point of the override: a same-day posting still goes out."""
    jobs = [_submitted("Acme", 0.1 * i, f"j{i}") for i in range(5)]
    queued = [_fresh("Acme", "fresh1")]

    applyable, held = partition_by_cap(queued, jobs + queued, now=NOW)

    assert [j["id"] for j in applyable] == ["fresh1"]
    assert held == []


def test_a_stale_posting_gets_no_extra_room_at_the_same_moment():
    """Same employer, same instant — only the fresh one is let through."""
    jobs = [_submitted("Acme", 0.1 * i, f"j{i}") for i in range(5)]
    stale = _queued("Acme", 90.0, "stale1")
    stale["postingDate"] = (NOW - timedelta(days=9)).isoformat()

    applyable, held = partition_by_cap([stale], jobs + [stale], now=NOW)

    assert applyable == []
    assert [j["id"] for j in held] == ["stale1"]


def test_an_undated_posting_is_never_assumed_fresh():
    """Most postings carry no publication date; guessing would hand out the
    bonus on a fabricated fact."""
    jobs = [_submitted("Acme", 0.1 * i, f"j{i}") for i in range(5)]
    undated = _queued("Acme", 90.0, "undated")
    assert "postingDate" not in undated

    applyable, held = partition_by_cap([undated], jobs + [undated], now=NOW)

    assert applyable == []
    assert [j["id"] for j in held] == ["undated"]


def test_the_bonus_expires_with_the_posting():
    older = _queued("Acme", 90.0, "day_old")
    older["postingDate"] = (NOW - timedelta(hours=25)).isoformat()

    assert company_cap.is_fresh_posting(older, now=NOW) is False
    assert company_cap.is_fresh_posting(_fresh("Acme", "x", hours_old=23), now=NOW) is True


def test_the_bonus_is_bounded_and_does_not_uncap_the_month():
    """The override raises every tier, so 23 in 30 days remains the ceiling —
    a fresh posting must not be a way around the monthly limit."""
    cap = COMPANY_APPLICATION_CAP + company_cap.FRESH_POSTING_BONUS
    # Spread across the month so neither the daily nor weekly tier is the cause.
    jobs = [_submitted("Acme", i * (COMPANY_CAP_WINDOW_DAYS / cap), f"j{i}") for i in range(cap)]
    queued = [_fresh("Acme", "fresh1")]

    applyable, held = partition_by_cap(queued, jobs + queued, now=NOW)

    assert applyable == []
    assert [j["id"] for j in held] == ["fresh1"]
    assert held[0]["companyCapTier"] == "month"


def test_a_future_dated_posting_is_not_treated_as_fresh():
    weird = _queued("Acme", 90.0, "future")
    weird["postingDate"] = (NOW + timedelta(days=3)).isoformat()

    assert company_cap.is_fresh_posting(weird, now=NOW) is False


# ── The hold explains itself ─────────────────────────────────────────────────


def test_the_hold_names_the_tier_that_bound():
    """The countdown and the reason must agree, or the message misleads."""
    jobs = [_submitted("Acme", 0.1 * i, f"j{i}") for i in range(5)]
    queued = [_queued("Acme", 90.0, "q1")]

    _, held = partition_by_cap(queued, jobs + queued, now=NOW)

    job = held[0]
    assert job["companyCapTier"] == "day"
    assert "5 per day" in job["companyCapReason"]


# ── Cost ─────────────────────────────────────────────────────────────────────


def test_the_index_is_built_once_per_batch_not_once_per_company():
    """Guards the 844ms -> <10ms fix: the earlier shape rescanned every job
    once per employer per check, which does not survive a real table."""
    submitted = [
        _submitted(f"Co{i % 60}", i % 29, f"s{i}") for i in range(3000)
    ]
    queued = [_queued(f"Co{i % 60}", 90.0 - i, f"q{i}") for i in range(300)]

    scans = 0
    real_index = company_cap.build_submission_index

    def counting_index(*args, **kwargs):
        nonlocal scans
        scans += 1
        return real_index(*args, **kwargs)

    company_cap.build_submission_index = counting_index
    try:
        partition_by_cap(queued, submitted + queued, now=NOW)
    finally:
        company_cap.build_submission_index = real_index

    assert scans == 1, f"the job table was walked {scans} times for one batch"
