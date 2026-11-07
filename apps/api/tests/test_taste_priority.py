"""Owner-taste priority ordering (docs/job-preferences.md, issue #99).

The owner asked for application order to follow their taste first and move on
to the rest afterwards, and for the review/failed lists to sort the same way.
These tests pin the encoded ranking: interest families P0-P2, the
deprioritized roles, the company affinity bonus, and how taste composes with
the existing recency-band and role-family tiers.
"""

from __future__ import annotations

import pytest

# These pin the author's hand-tuned order, the opt-in "owner" ranking preset.
pytestmark = pytest.mark.usefixtures("owner_ranking_preset")

from app.services.application_assistant.job_filter_ranker import (
    TASTE_UNIT_WEIGHT,
    queue_priority_score,
    taste_priority_score,
)


def _job(**overrides):
    job = {
        "title": "Senior Software Engineer",
        "location": "Remote (United States)",
        "matchScore": 80.0,
    }
    job.update(overrides)
    return job


# ---------------------------------------------------------------- families


def test_p0_agentic_beats_p1_backend_within_a_band():
    """P0 (agentic AI platforms) applies before P1 (backend platforms)."""
    assert (
        taste_priority_score(_job(title="Senior Software Engineer, Agentic AI Platform"))
        > taste_priority_score(_job(title="Senior Software Engineer, Backend Platform"))
    )


def test_family_order_follows_the_preference_doc_weights():
    agentic = taste_priority_score(_job(title="Agentic AI Platform Engineer"))
    applied = taste_priority_score(_job(title="Senior AI Engineer, Applied AI"))
    automation = taste_priority_score(_job(title="Senior Software Engineer, Automation"))
    backend = taste_priority_score(_job(title="Senior Backend Engineer"))
    assert agentic > applied > automation > backend


def test_p2_fintech_still_sits_below_p1_backend():
    """The P2 families apply after the P1 ones and after a plain Senior SWE base."""
    fintech = taste_priority_score(_job(title="Senior Software Engineer, Fintech"))
    backend = taste_priority_score(_job(title="Senior Software Engineer, Backend"))
    assert fintech < backend


# -------------------------------------------------- composition with bands


def test_taste_outranks_role_level_and_location_within_a_band():
    """Taste first, then everything else — Per the owner's ask for apply order."""
    tastier = _job(title="Senior Software Engineer, Agentic AI Platform", location="Austin, Texas")
    senior = _job(title="Senior Software Engineer", location="Seattle, WA")
    assert queue_priority_score(tastier) > queue_priority_score(senior)
    # The margin has to come from taste, not from a fluke of the location tier.
    assert (
        queue_priority_score(tastier) - queue_priority_score(senior) > TASTE_UNIT_WEIGHT * 10
    )


def test_fresher_band_still_wins_across_bands():
    """Fresh-jobs-first intake survives taste: an older posting cannot leap a band.

    Both jobs sit in the AI application family, but the fresher one is a P1
    family (95) against an older P0 (100) — the recency band gap still wins.
    """
    from datetime import datetime, timedelta, timezone

    now = datetime.now(timezone.utc)
    fresher = _job(
        title="Senior AI Engineer, Applied AI",
        datePosted=(now - timedelta(hours=2)).isoformat(),
    )
    older_tasty = _job(
        title="Agentic AI Platform Engineer",
        datePosted=(now - timedelta(days=25)).isoformat(),
    )
    assert queue_priority_score(fresher) > queue_priority_score(older_tasty)


def test_ai_family_tier_still_dominates_plain_swe_regardless_of_taste():
    """The AI application family outranks non-AI families even when they out-score."""
    ai_role = _job(title="Agentic AI Platform Engineer", matchScore=1.0)
    swe_role = _job(title="Senior Backend Engineer", matchScore=99.0)
    assert queue_priority_score(ai_role) > queue_priority_score(swe_role)


# ------------------------------------------------------------ depend tricks


def test_deprioritized_roles_sort_below_a_generic_senior_swe():
    deprioritized_titles = (
        "Frontend Engineer",
        "Prompt Engineer",
        "Site Reliability Engineer",
        "IT Support Engineer",
        "Research Scientist, ML",
        "Engineering Manager",
    )
    plain = taste_priority_score(_job())
    for title in deprioritized_titles:
        assert taste_priority_score(_job(title=title, matchScore=95.0)) < plain, title


def test_ai_reliability_is_not_dragged_into_the_sre_bucket():
    """The AI family guard keeps an AI reliability role at its family weight."""
    assert (
        taste_priority_score(_job(title="Senior AI Reliability Engineer"))
        > taste_priority_score(_job(title="Senior Site Reliability Engineer"))
    )


def test_prompt_engineer_loses_the_ai_application_tier():
    """Prompt-writing work must not take the AI/ML application family tier."""
    assert "prompt engineer" not in str(
        __import__(
            "app.services.application_assistant.job_filter_ranker",
            fromlist=["_is_ai_priority_role"],
        )._is_ai_priority_role("Prompt Engineer")
    )


def test_devtools_p0_titles_take_the_ai_application_tier():
    """AI developer tools / engineering productivity are P0 (100) in the doc."""
    ranker = __import__(
        "app.services.application_assistant.job_filter_ranker", fromlist=["_is_ai_priority_role"]
    )
    assert ranker._is_ai_priority_role("Senior Software Engineer, Developer Productivity")
    assert ranker._is_ai_priority_role("Senior Software Engineer, Developer Tools")


# -------------------------------------------------- company / description


def test_company_affinity_breaks_ties():
    at_cursor = _job(title="Senior Software Engineer", company="Cursor")
    at_acme = _job(title="Senior Software Engineer", company="Acme Corp")
    assert queue_priority_score(at_cursor) > queue_priority_score(at_acme)


def test_generic_title_is_lifted_by_agent_signal_in_description():
    with_agents = _job(
        description="You will build agentic workflows and a coding agent platform.",
    )
    without = _job(description="Maintain the existing billing monolith.")
    assert taste_priority_score(with_agents) > taste_priority_score(without)
