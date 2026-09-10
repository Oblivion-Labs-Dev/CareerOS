"""Queue ranking and Mistral match sanitisation.

Covers the two invariants the persistent Autopilot queue depends on:

1. Location/level tiering — Washington Senior SWE above any related Washington
   engineering role, above a Senior SWE elsewhere in the US.
2. The anti-fabrication guard on Mistral's match payload — a skill the resume
   does not evidence can never end up in ``keyMatchingSkills`` or raise a
   posting's score.
"""

from __future__ import annotations

import pytest

from app.services.application_assistant.job_filter_ranker import (
    evaluate_hard_filters,
    queue_priority_score,
    role_location_priority_bonus,
)
from app.services.application_assistant.mistral_resume_match import (
    is_empty_payload,
    sanitize_match_payload,
)


def job(title: str, location: str, score: float = 0.0) -> dict:
    return {"title": title, "location": location, "matchScore": score}


@pytest.mark.parametrize(
    "title,location,expected",
    [
        ("Senior Software Engineer", "Seattle, WA", 120.0),
        ("Senior Software Engineer", "Kirkland , Washington, united states", 120.0),
        ("Staff Software Engineer, Security", "Bellevue, WA", 90.0),
        ("Software Engineer II", "Redmond, WA", 90.0),
        ("Senior Software Engineer", "Remote - US", 60.0),
        ("Senior Backend Engineer", "New York, New York, USA", 60.0),
        ("Software Engineer II", "Remote - US", 25.0),
        ("Product Manager", "Seattle, WA", 0.0),
        ("Senior Software Engineer", "London, United Kingdom", 0.0),
    ],
)
def test_location_level_tiers(title: str, location: str, expected: float) -> None:
    assert role_location_priority_bonus(job(title, location)) == expected


def test_washington_dc_is_not_washington_state() -> None:
    """D.C. is the opposite side of the country and must not take the top tier."""
    dc = job("Senior Software Engineer", "Washington, District of Columbia")
    wa = job("Senior Software Engineer", "Seattle, WA")
    assert role_location_priority_bonus(dc) == 60.0
    assert role_location_priority_bonus(wa) == 120.0
    for location in ("Washington, D.C.", "Washington DC", "Washington, dc"):
        assert role_location_priority_bonus(job("Senior Software Engineer", location)) == 60.0


def test_requested_queue_ordering() -> None:
    """WA Senior + high match > WA related + high match > US Senior + high match."""
    wa_senior = job("Senior Software Engineer", "Seattle, WA", 80)
    wa_related = job("Staff Platform Engineer", "Bellevue, WA", 95)
    us_senior = job("Senior Software Engineer", "Remote - US", 99)
    ordered = sorted([us_senior, wa_related, wa_senior], key=queue_priority_score, reverse=True)
    assert ordered == [wa_senior, wa_related, us_senior]


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
