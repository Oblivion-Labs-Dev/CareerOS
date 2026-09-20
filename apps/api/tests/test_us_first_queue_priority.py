"""US postings are worked first; international ones go to the end, not away.

The four tiers in `role_location_priority_bonus` are all US-shaped, so an
international posting gets no tier — but neither does a US posting whose title
misses a tier, which left both at the same score and handed the ordering to
recency. Measured live inside the submittable-board pool the runner actually
draws from: US and international both sat at a median of 8.17, and the claim
order opened with Sezzle Peru, Encora Mexico and three India roles ahead of
every US job.
"""

from __future__ import annotations

import pytest

from app.services.application_assistant.job_filter_ranker import (
    INTERNATIONAL_QUEUE_PENALTY,
    is_international_location,
    queue_priority_score,
)


@pytest.mark.parametrize(
    ("location", "expected"),
    [
        ("Hyderabad, India", True),
        ("Gdansk, Pomeranian Voivodeship, Poland", True),
        ("Toronto, Canada", True),
        ("Peru", True),
        ("Mexico", True),
        # Indian metros beyond the obvious two — an Agoda "Gurugram" posting
        # ranked third on the US-first list before these were covered.
        ("Gurugram", True),
        ("Pune, Maharashtra", True),
        ("Seattle, WA", False),
        ("Remote (United States)", False),
        ("San Jose, CA, USA", False),
        ("", False),
    ],
)
def test_international_detection(location, expected):
    assert is_international_location({"location": location}) is expected


@pytest.mark.parametrize(
    "location",
    [
        # Names a foreign country but is explicitly open to US candidates.
        "Remote, Canada; Remote, United States",
        # US places that happen to share a name with a foreign capital.
        "Vienna, Virginia, United States",
    ],
)
def test_us_eligible_postings_are_not_treated_as_international(location):
    """A foreign mention must not sink a posting that is open to US candidates."""
    assert is_international_location({"location": location}) is False


def test_unknown_location_is_treated_as_us():
    """A missing location must never silently sink a domestic posting."""
    assert is_international_location({}) is False


def test_international_sorts_below_an_otherwise_stronger_posting():
    """The penalty has to outweigh match score and recency, not just tie-break."""
    strong_intl = {
        "title": "Senior Software Engineer",
        "location": "Bangalore, India",
        "matchScore": 99.0,
    }
    weak_us = {
        "title": "Software Engineer",
        "location": "Remote (United States)",
        "matchScore": 1.0,
    }
    assert queue_priority_score(weak_us) > queue_priority_score(strong_intl)


def test_international_postings_keep_their_relative_order():
    """"At the end", not "never" — they still rank sensibly among themselves."""
    better = {"title": "Senior Software Engineer", "location": "Pune, India", "matchScore": 90.0}
    worse = {"title": "Senior Software Engineer", "location": "Pune, India", "matchScore": 10.0}
    assert queue_priority_score(better) > queue_priority_score(worse)


def test_penalty_is_only_applied_to_international():
    """The gap is at least the penalty — a US posting also earns a location tier.

    Asserting equality here would be wrong: the US job legitimately collects the
    Tier-3 "Senior SWE elsewhere in the US" bonus on top, so the observed gap is
    penalty + tier, not penalty alone.
    """
    us = {"title": "Senior Software Engineer", "location": "Austin, Texas", "matchScore": 50.0}
    intl = {"title": "Senior Software Engineer", "location": "Lisbon, Portugal", "matchScore": 50.0}
    assert queue_priority_score(us) - queue_priority_score(intl) >= INTERNATIONAL_QUEUE_PENALTY


def test_recency_can_no_longer_float_an_international_posting_to_the_top():
    """The case that actually broke.

    A freshly-queued international posting used to outrank a stale US one once
    both scored zero on location tier, because recency decided. That is how
    Sezzle Peru reached the top of the claim order ahead of every US job.
    """
    from datetime import UTC, datetime

    just_queued_intl = {
        "title": "Senior Software Engineer",
        "location": "Lima, Peru",
        "matchScore": 80.0,
        "postingDate": datetime.now(UTC).isoformat(),
    }
    stale_us = {
        "title": "Senior Software Engineer",
        "location": "Remote (United States)",
        "matchScore": 40.0,
        "postingDate": "2026-08-01T00:00:00+00:00",
    }
    assert queue_priority_score(stale_us) > queue_priority_score(just_queued_intl)
