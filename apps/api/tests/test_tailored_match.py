"""Tests for scoring the resume that actually gets submitted.

The behaviour that matters here is not "does it score" but "can the score be
gamed". The whole reason re-scoring is safe to act on is that the evidence set
stays anchored to the candidate's real documents, so a tailored bullet cannot
match against its own invention.
"""

from __future__ import annotations

import pytest

from app.services.application_assistant.tailored_match import (
    build_submitted_resume_text,
    describe_gaps,
    score_tailored_resume,
    strip_markup,
)

ORIGINAL = """Akshay Borse
PROFESSIONAL SUMMARY
Senior Software Engineer with 8+ years building distributed systems.
EXPERIENCE
Senior Software Engineer | Microsoft | Redmond, WA | Sep 2025 to Present
- Built risk detection for AI agents.
- Reconstructed 90 days of audit history.
Software Engineer 2 | Amazon | Seattle, WA | Aug 2019 - Aug 2025
- Built a developer platform.
Software Engineering Intern | Liquiron | San Jose, CA | Dec 2018 to Jan 2019
- Re-architected authentication using OAuth 2.0.
EDUCATION
Santa Clara University, MS Computer Science
FEATURED PROJECTS
LeetDesign: system design simulator.
"""

TAILORED = [
    "<b>Led Kubernetes platform work</b> for 60+ services.",
    "<b>Owned the ingestion redesign</b> across 28 deployments.",
]


def test_strip_markup_removes_bold_tags():
    assert strip_markup("<b>Led</b> the work") == "Led the work"


# --------------------------------------------------------------------------
# Building the submitted document
# --------------------------------------------------------------------------

def test_submitted_text_replaces_only_the_overlaid_experience_section():
    out = build_submitted_resume_text(ORIGINAL, TAILORED)
    # The bullets the overlay replaces are gone...
    assert "Reconstructed 90 days of audit history" not in out
    assert "Built a developer platform" not in out
    # ...and the tailored ones are there.
    assert "Led Kubernetes platform work" in out
    # Everything the overlay does not touch survives, which is the difference
    # between scoring the real document and scoring 17 bullets in isolation.
    assert "Liquiron" in out
    assert "OAuth 2.0" in out
    assert "Santa Clara University" in out
    assert "LeetDesign" in out
    assert "PROFESSIONAL SUMMARY" in out


def test_submitted_text_keeps_full_resume_when_markers_are_missing():
    """A resume whose headings changed must not silently score as bullets only."""
    odd = "Some resume with different headings.\nEDUCATION\nSCU"
    out = build_submitted_resume_text(odd, TAILORED)
    assert "Some resume with different headings." in out
    assert "SCU" in out
    assert "Led Kubernetes platform work" in out


def test_submitted_text_handles_empty_inputs():
    assert build_submitted_resume_text("", TAILORED).strip() != ""
    assert "Liquiron" in build_submitted_resume_text(ORIGINAL, [])
    assert build_submitted_resume_text("", []) == ""


def test_markup_is_stripped_from_the_scored_text():
    out = build_submitted_resume_text(ORIGINAL, TAILORED)
    assert "<b>" not in out


# --------------------------------------------------------------------------
# Gap feedback
# --------------------------------------------------------------------------

def test_describe_gaps_deduplicates_and_caps():
    payload = {"missingSkills": ["Go", "go", "Kubernetes", "Rust"] + [f"s{i}" for i in range(20)]}
    gaps = describe_gaps(payload, limit=5)
    assert gaps[:3] == ["Go", "Kubernetes", "Rust"]
    assert len(gaps) == 5


def test_describe_gaps_tolerates_missing_or_malformed_payloads():
    assert describe_gaps(None) == []
    assert describe_gaps({}) == []
    assert describe_gaps({"missingSkills": "not a list"}) == []


# --------------------------------------------------------------------------
# The anti-gaming property
# --------------------------------------------------------------------------

@pytest.mark.anyio
async def test_evidence_terms_come_from_the_original_not_the_tailored_text(monkeypatch):
    """A skill that exists only in the tailored bullet must not count as a match.

    This is the property that makes acting on a re-scored number safe. If the
    evidence set were built from the tailored text, the model could write
    "Kubernetes" into a bullet and then match against its own output.
    """
    seen: dict[str, object] = {}

    class FakeClient:
        enabled = True

    async def fake_score(client, job, *, candidate_summary, evidence_text, evidence_terms):
        seen["summary"] = candidate_summary
        seen["evidence_text"] = evidence_text
        seen["evidence_terms"] = evidence_terms
        return {"matchScore": 88.0, "missingSkills": ["Rust"]}

    import app.services.application_assistant.mistral_resume_match as mrm

    monkeypatch.setattr(mrm, "build_mistral_match_client", lambda timeout=None: FakeClient())
    monkeypatch.setattr(mrm, "score_job_against_resume", fake_score)
    monkeypatch.setattr(
        mrm,
        "build_candidate_evidence",
        lambda profile, documents=None, accomplishments=None: (
            "summary", "python java aws", {"python", "java", "aws"}
        ),
    )

    result = await score_tailored_resume(
        {"id": "j1", "title": "Platform Engineer", "description": "Kubernetes"},
        ["<b>Led Kubernetes work</b> at scale."],
        profile={"firstName": "A"},
        documents={},
        accomplishments=[],
    )

    assert result["matchScore"] == 88.0
    # The tailored bullet mentions Kubernetes...
    assert "Kubernetes" in seen["summary"]
    # ...but the evidence the scorer checks claims against does not.
    assert "kubernetes" not in seen["evidence_text"]
    assert "kubernetes" not in seen["evidence_terms"]


@pytest.mark.anyio
async def test_no_bullets_returns_none_not_zero():
    """None means 'could not score'. Zero would read as a failed match and
    reject a resume the model simply never looked at."""
    assert await score_tailored_resume({"id": "j"}, [], profile={}) is None
    assert await score_tailored_resume({"id": "j"}, ["   "], profile={}) is None


@pytest.mark.anyio
async def test_disabled_model_returns_none(monkeypatch):
    import app.services.application_assistant.mistral_resume_match as mrm

    class Disabled:
        enabled = False

    monkeypatch.setattr(mrm, "build_mistral_match_client", lambda timeout=None: Disabled())
    monkeypatch.setattr(
        mrm,
        "build_candidate_evidence",
        lambda profile, documents=None, accomplishments=None: ("s", "t", set()),
    )
    assert await score_tailored_resume({"id": "j"}, ["<b>x</b> y"], profile={}) is None
