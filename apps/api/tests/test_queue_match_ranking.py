"""Queue ranking and Mistral match sanitisation.

Covers the two invariants the persistent Autopilot queue depends on:

1. Role/location tiering — Senior, Forward Deployed, Principal, SDE 2, Staff,
   SDE 1; within a role, Washington State above the rest of the US.
2. The anti-fabrication guard on Mistral's match payload — a skill the resume
   does not evidence can never end up in ``keyMatchingSkills`` or raise a
   posting's score.
"""

from __future__ import annotations

import pytest

# These pin the author's hand-tuned order, the opt-in "owner" ranking preset.
pytestmark = pytest.mark.usefixtures("owner_ranking_preset")

from app.services.application_assistant.job_filter_ranker import (
    ROLE_RANK_FORWARD_DEPLOYED,
    ROLE_RANK_PRINCIPAL,
    ROLE_RANK_SDE_1,
    ROLE_RANK_SDE_2,
    ROLE_RANK_SENIOR,
    ROLE_RANK_STAFF,
    evaluate_hard_filters,
    is_management_title,
    is_washington_location,
    queue_priority_score,
    role_location_priority_bonus,
    role_priority_rank,
    software_role_rejection,
)


def job(title: str, location: str, score: float = 0.0) -> dict:
    return {"title": title, "location": location, "matchScore": score}


@pytest.mark.parametrize(
    "title,expected",
    [
        ("Senior Software Engineer", ROLE_RANK_SENIOR),
        ("Sr. Backend Engineer", ROLE_RANK_SENIOR),
        ("Senior Forward Deployed Engineer", ROLE_RANK_SENIOR),
        ("Forward Deployed Engineer", ROLE_RANK_FORWARD_DEPLOYED),
        ("Forward-Deployed Software Engineer", ROLE_RANK_FORWARD_DEPLOYED),
        ("Principal Software Engineer", ROLE_RANK_PRINCIPAL),
        ("Senior Principal Engineer", ROLE_RANK_PRINCIPAL),
        ("Software Development Engineer II", ROLE_RANK_SDE_2),
        ("Software Engineer 2", ROLE_RANK_SDE_2),
        ("Staff Software Engineer", ROLE_RANK_STAFF),
        ("Senior Staff Software Engineer", ROLE_RANK_STAFF),
        ("Software Engineer I", ROLE_RANK_SDE_1),
        ("SDE 1", ROLE_RANK_SDE_1),
        ("Software Engineer in Test", 0),
        ("Member of Technical Staff", 0),
        ("Software Engineer", 0),
    ],
)
def test_role_priority_rank(title: str, expected: int) -> None:
    assert role_priority_rank(title) == expected


@pytest.mark.parametrize(
    "location,is_wa",
    [
        ("Seattle, WA", True),
        ("Bellevue, Washington, United States", True),
        ("US-WA-Redmond", True),
        ("Kirkland , Washington, united states", True),
        ("Auburn, WA", True),
        ("Washington, District of Columbia", False),
        ("Washington, D.C.", False),
        ("Washington DC", False),
        ("Des Moines, Iowa, United States", False),
        ("Ottawa, Ontario", False),
        ("Honolulu, Hawaii", False),
        ("Remote - US", False),
        ("", False),
    ],
)
def test_washington_location(location: str, is_wa: bool) -> None:
    assert is_washington_location({"location": location}) is is_wa


def test_non_engineering_titles_get_no_bonus() -> None:
    assert role_location_priority_bonus(job("Product Manager", "Seattle, WA")) == 0.0
    assert role_location_priority_bonus(job("Software Engineer Intern", "Seattle, WA")) == 0.0


@pytest.mark.parametrize(
    "title",
    [
        "Software Engineer Manager",
        "Engineering Manager – AI Platform & SRE",
        "Senior Manager, Full-stack Engineer (People Leader)-EDT",
        "Senior Director, Full-stack Engineer (Remote-Eligible)",
        "VP of Engineering",
        "Chief Software Engineer",
        "Director, Principal Software Engineer",
        "Vice President, Senior Full Stack Engineer - SMA Solutions",
        "Software Engineer - Assistant Vice President",
    ],
)
def test_management_titles(title: str) -> None:
    assert is_management_title(title)


@pytest.mark.parametrize(
    "title",
    [
        "Full-stack Engineer 4 (Manager, IC)",
        "Full-stack Engineer 5 (Senior Manager, IC)-EDT",
        "Senior Software Engineer",
    ],
)
def test_individual_contributor_titles_with_management_words(title: str) -> None:
    assert not is_management_title(title)


def test_ai_family_outranks_location_and_level() -> None:
    """The AI/ML family applies first regardless of location or level.

    Owner-set order (2026-10-21): AI engineering roles go out before everything
    else, even a Seattle Staff role with a far higher match score.
    """
    wa_staff = job("Senior Staff Machine Learning Engineer", "Seattle, WA", 99)
    us_senior = job("Senior Software Engineer", "Remote - US", 10)
    assert queue_priority_score(wa_staff) > queue_priority_score(us_senior)


def test_seattle_senior_still_outranks_remote_us_senior() -> None:
    """Within the same application family tier, location still decides."""
    wa_senior = job("Senior Software Engineer", "Seattle, WA", 10)
    us_senior = job("Senior Software Engineer", "Remote - US", 99)
    assert queue_priority_score(wa_senior) > queue_priority_score(us_senior)


def test_location_breaks_ties_within_a_role() -> None:
    """FDE Seattle, FDE US, Senior Seattle, Senior US — in that order.

    Owner-set family order (2026-10-21): Forward Deployed applies before
    Senior SWE, so the old Senior-before-FDE expectation was reversed; location
    then decides inside each family.
    """
    jobs = [
        job("Forward Deployed Engineer", "Remote - US", 99),
        job("Senior Software Engineer", "Remote - US", 99),
        job("Forward Deployed Engineer", "Bellevue, WA", 10),
        job("Senior Software Engineer", "Seattle, WA", 10),
    ]
    ordered = sorted(jobs, key=queue_priority_score, reverse=True)
    assert [(j["title"], j["location"]) for j in ordered] == [
        ("Forward Deployed Engineer", "Bellevue, WA"),
        ("Forward Deployed Engineer", "Remote - US"),
        ("Senior Software Engineer", "Seattle, WA"),
        ("Senior Software Engineer", "Remote - US"),
    ]


def test_requested_role_order_within_a_location() -> None:
    """AI/ML engineering first, then FDE, then Senior SWE, then the rest.

    One title per family tier, each with a worse match score than every tier
    below it — the tier must override an 80-point score deficit. The tier-0
    tail keeps its old role-level ordering.
    """
    titles = [
        "AI Engineer",
        "Forward Deployed Engineer",
        "Senior Software Engineer",
        "Principal Software Engineer",
        "Software Engineer II",
        "Staff Software Engineer",
        "Software Engineer I",
    ]
    scores = (10, 20, 30, 40, 50, 60, 70, 80)
    for location in ("Seattle, WA", "Austin, TX"):
        jobs = [job(title, location, score) for title, score in zip(titles, scores)]
        ordered = sorted(jobs, key=queue_priority_score, reverse=True)
        assert [j["title"] for j in ordered] == titles


@pytest.mark.parametrize(
    "title",
    ["Forward Deployed Engineer", "Forward-Deployed Engineer, Federal", "Senior Forward Deployed Software Engineer"],
)
def test_forward_deployed_engineer_is_a_software_role(title: str) -> None:
    assert software_role_rejection(title) is None


@pytest.mark.parametrize(
    "title",
    [
        "Senior ML Ops Engineer (Machine Learning Infrastructure)",
        "Senior Security Engineer, Corporate Security",
        "Senior Staff Data Engineer",
        "Lead Data Engineer - Healthcare Data & Audience Applications",
    ],
)
def test_adjacent_engineering_families_are_applied_to(title: str) -> None:
    assert software_role_rejection(title) is None


@pytest.mark.parametrize("title", ["Power Platform Developer", "Senior HR Business Partner – Global Technology"])
def test_non_software_titles_stay_excluded(title: str) -> None:
    assert software_role_rejection(title) is not None


def test_match_score_breaks_ties_within_a_tier() -> None:
    strong = job("Senior Software Engineer", "Seattle, WA", 88)
    weak = job("Senior Software Engineer", "Redmond, WA", 61)
    assert queue_priority_score(strong) > queue_priority_score(weak)


@pytest.mark.parametrize(
    "url,should_pass",
    [
        ("https://job-boards.greenhouse.io/acme/jobs/123", True),
        # Index paths that identify the posting in the query are real postings.
        ("https://www.coupang.jobs/en/jobs/?gh_jid=7849003", True),
        # These are careers indexes: the executor opens them, fills nothing, and
        # fails with "Submit button not found" after a full browser session.
        ("https://www.coupang.jobs/en/jobs", False),
        ("https://acme.com/careers/", False),
        ("https://acme.com/careers/?utm_source=newsletter", False),
        ("", False),
    ],
)
def test_unapplyable_urls_never_reach_the_browser(url: str, should_pass: bool) -> None:
    posting = {
        "company": "Acme",
        "title": "Senior Software Engineer",
        "location": "Seattle, WA",
        "applicationUrl": url,
    }
    passed, reason = evaluate_hard_filters(posting, {}, [], {"allowDuplicates": True})
    assert passed is should_pass, reason
