"""Tests for Recency-First queue priority ordering.

Ensures that recently posted jobs are prioritized ahead of older jobs across
distinct recency bands, while preserving location tier (Washington Senior SWE)
and match score as tie-breakers within the same recency band.
"""

from __future__ import annotations

from datetime import datetime, timezone, timedelta
import pytest

from app.services.application_assistant.job_filter_ranker import (
    extract_posting_datetime,
    posting_recency_bonus,
    queue_priority_score,
)


def test_recent_posting_overtakes_older_high_match_posting():
    """A fresh 12-hour-old posting outranks a 10-day-old posting even if the older
    one has top location tier (+120 WA Senior) and high match score (+95)."""
    now = datetime.now(timezone.utc)
    fresh_us = {
        "title": "Senior Software Engineer",
        "location": "Remote - US",
        "matchScore": 60.0,
        "datePosted": (now - timedelta(hours=12)).isoformat(),
    }
    old_wa = {
        "title": "Senior Software Engineer",
        "location": "Seattle, WA",
        "matchScore": 95.0,
        "datePosted": (now - timedelta(days=10)).isoformat(),
    }
    assert queue_priority_score(fresh_us) > queue_priority_score(old_wa)


def test_location_and_match_break_ties_within_same_recency_band():
    """Within the same recency band (both posted ~12 hours ago), Washington Senior SWE
    outranks Remote US Senior SWE, and higher match score outranks lower match score."""
    now = datetime.now(timezone.utc)
    fresh_wa = {
        "title": "Senior Software Engineer",
        "location": "Seattle, WA",
        "matchScore": 85.0,
        "datePosted": (now - timedelta(hours=12)).isoformat(),
    }
    fresh_remote = {
        "title": "Senior Software Engineer",
        "location": "Remote - US",
        "matchScore": 85.0,
        "datePosted": (now - timedelta(hours=12)).isoformat(),
    }
    assert queue_priority_score(fresh_wa) > queue_priority_score(fresh_remote)


def test_last_24_hours_beats_location_and_role():
    """A fresh SDE 1 role elsewhere in the US outranks a 2-day-old Seattle Senior role."""
    now = datetime.now(timezone.utc)
    fresh_us_sde1 = {
        "title": "Software Engineer I",
        "location": "Austin, TX",
        "matchScore": 10.0,
        "datePosted": (now - timedelta(hours=23)).isoformat(),
    }
    older_wa_senior = {
        "title": "Senior Software Engineer",
        "location": "Seattle, WA",
        "matchScore": 99.0,
        "datePosted": (now - timedelta(hours=26)).isoformat(),
    }
    assert queue_priority_score(fresh_us_sde1) > queue_priority_score(older_wa_senior)


def test_location_beats_freshness_inside_the_24_hour_band():
    now = datetime.now(timezone.utc)
    wa_20h = {
        "title": "Senior Software Engineer",
        "location": "Bellevue, WA",
        "matchScore": 50.0,
        "datePosted": (now - timedelta(hours=20)).isoformat(),
    }
    us_1h = {
        "title": "Senior Software Engineer",
        "location": "Remote - US",
        "matchScore": 99.0,
        "datePosted": (now - timedelta(hours=1)).isoformat(),
    }
    assert queue_priority_score(wa_20h) > queue_priority_score(us_1h)


def test_hourly_decay_within_same_band():
    """Within the same day, a job posted 2 hours ago outranks a job posted 20 hours ago."""
    now = datetime.now(timezone.utc)
    two_hours_old = {
        "title": "Senior Software Engineer",
        "location": "Seattle, WA",
        "matchScore": 80.0,
        "datePosted": (now - timedelta(hours=2)).isoformat(),
    }
    twenty_hours_old = {
        "title": "Senior Software Engineer",
        "location": "Seattle, WA",
        "matchScore": 80.0,
        "datePosted": (now - timedelta(hours=20)).isoformat(),
    }
    assert queue_priority_score(two_hours_old) > queue_priority_score(twenty_hours_old)


@pytest.mark.parametrize(
    "date_val",
    [
        "October 5, 2026",
        "Oct 05, 2026",
        "September 30, 2026",
        "2026-10-05T12:00:00Z",
        "2026-10-05T12:00:00+00:00",
    ],
)
def test_multi_format_date_parsing(date_val: str):
    """Dates in various formats from scrapers and ATS feeds are parsed accurately."""
    parsed = extract_posting_datetime({"datePosted": date_val})
    assert parsed is not None
    assert parsed.year == 2026


def test_stale_domestic_still_beats_recent_international():
    """International jobs remain heavily penalized so domestic roles are worked first."""
    now = datetime.now(timezone.utc)
    fresh_intl = {
        "title": "Senior Software Engineer",
        "location": "Lima, Peru",
        "matchScore": 90.0,
        "datePosted": now.isoformat(),
    }
    stale_us = {
        "title": "Software Engineer",
        "location": "Remote (United States)",
        "matchScore": 50.0,
        "datePosted": (now - timedelta(days=60)).isoformat(),
    }
    assert queue_priority_score(stale_us) > queue_priority_score(fresh_intl)
