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
from app.services.application_assistant.mistral_resume_match import (
    is_empty_payload,
    sanitize_match_payload,
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


def test_role_outranks_location() -> None:
    """A Senior role anywhere in the US sits above a Seattle-area Staff role."""
    wa_staff = job("Senior Staff Machine Learning Engineer", "Seattle, WA", 99)
    us_senior = job("Senior Software Engineer", "Remote - US", 10)
    assert queue_priority_score(us_senior) > queue_priority_score(wa_staff)


def test_location_breaks_ties_within_a_role() -> None:
    """Senior Seattle, Senior US, FDE Seattle, FDE US — in that order."""
    jobs = [
        job("Forward Deployed Engineer", "Remote - US", 99),
        job("Senior Software Engineer", "Remote - US", 99),
        job("Forward Deployed Engineer", "Bellevue, WA", 10),
        job("Senior Software Engineer", "Seattle, WA", 10),
    ]
    ordered = sorted(jobs, key=queue_priority_score, reverse=True)
    assert [(j["title"], j["location"]) for j in ordered] == [
        ("Senior Software Engineer", "Seattle, WA"),
        ("Senior Software Engineer", "Remote - US"),
        ("Forward Deployed Engineer", "Bellevue, WA"),
        ("Forward Deployed Engineer", "Remote - US"),
    ]


def test_requested_role_order_within_a_location() -> None:
    titles = [
        "Senior Software Engineer",
        "Forward Deployed Engineer",
        "Principal Software Engineer",
        "Software Engineer II",
        "Staff Software Engineer",
        "Software Engineer I",
    ]
    for location in ("Seattle, WA", "Austin, TX"):
        jobs = [job(title, location, score) for title, score in zip(titles, (10, 20, 30, 40, 50, 60))]
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


EVIDENCE_TEXT = (
    "senior software engineer at microsoft and amazon. built distributed systems "
    "in c# and .net on azure, plus python services and kusto dashboards."
).lower()
EVIDENCE_TERMS = {
    "senior", "software", "engineer", "microsoft", "amazon", "distributed",
    "systems", "azure", "python", "kusto", "net", "c#",
}


def test_unevidenced_skills_are_moved_to_gaps_and_cost_score() -> None:
    raw = {
        "matchScore": 90,
        "matchReason": "Strong overlap.",
        "keyMatchingSkills": ["Python", "distributed systems", "Kubernetes", "Rust"],
        "missingSkills": ["Terraform"],
    }
    result = sanitize_match_payload(raw, evidence_text=EVIDENCE_TEXT, evidence_terms=EVIDENCE_TERMS)

    assert result["keyMatchingSkills"] == ["Python", "distributed systems"]
    # Fabricated claims become gaps rather than silently disappearing.
    assert set(result["missingSkills"]) == {"Terraform", "Kubernetes", "Rust"}
    assert result["unevidencedClaimsDropped"] == ["Kubernetes", "Rust"]
    # A posting cannot keep the score it earned on invented skills.
    assert result["matchScore"] < 90
    assert "no resume evidence" in result["matchReason"]


def test_honest_payload_keeps_its_score() -> None:
    raw = {
        "matchScore": 82,
        "matchReason": "Directly relevant background.",
        "keyMatchingSkills": ["C#", "Azure", "distributed systems"],
        "missingSkills": ["Go"],
    }
    result = sanitize_match_payload(raw, evidence_text=EVIDENCE_TEXT, evidence_terms=EVIDENCE_TERMS)
    assert result["matchScore"] == 82.0
    assert result["keyMatchingSkills"] == ["C#", "Azure", "distributed systems"]
    assert result["missingSkills"] == ["Go"]
    assert result["unevidencedClaimsDropped"] == []
    assert result["matchMethod"] == "ollama-local"


def test_resume_speak_is_normalised_before_the_evidence_check() -> None:
    """"Experience with X" is a claim about X, and must be checked as X."""
    raw = {
        "matchScore": 70,
        "matchReason": "Backend overlap.",
        "keyMatchingSkills": ["Experience with distributed systems", "Proficiency in Python"],
        "missingSkills": [],
    }
    result = sanitize_match_payload(raw, evidence_text=EVIDENCE_TEXT, evidence_terms=EVIDENCE_TERMS)
    assert result["keyMatchingSkills"] == ["distributed systems", "Python"]
    assert result["unevidencedClaimsDropped"] == []


def test_blank_model_output_is_not_a_zero_score() -> None:
    """A blank answer is an unscored posting, not a posting that scored zero."""
    assert is_empty_payload({"matchScore": 0, "matchReason": "", "keyMatchingSkills": [], "missingSkills": []})
    assert not is_empty_payload({"matchScore": 0, "matchReason": "No overlap at all.", "keyMatchingSkills": [], "missingSkills": []})
    assert not is_empty_payload({"matchScore": 41, "matchReason": "", "keyMatchingSkills": [], "missingSkills": []})
