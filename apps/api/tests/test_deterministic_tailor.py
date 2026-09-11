"""Tests for model-free resume tailoring.

Most of these exist to pin down what it must *refuse* to do. The feature is only
worth having if it cannot fabricate, and the tempting implementation - reusing
the retrieval alias table - fabricates immediately.
"""

from __future__ import annotations

import re

from app.services.application_assistant.deterministic_tailor import (
    SAFE_SYNONYMS,
    align_to_posting,
    tailor,
)

BULLETS = [
    "<b>Built a developer platform</b> using IaC and CI/CD across 60+ services.",
    "<b>Led ML work</b> on SageMaker, contributing to a 7% increase in sales.",
    "<b>Ran Kubernetes</b> in production with HA across three regions.",
]


def plain(text: str) -> str:
    return re.sub(r"<[^>]+>", "", text)


# --------------------------------------------------------------------------
# It aligns wording
# --------------------------------------------------------------------------

def test_expands_an_abbreviation_the_posting_spells_out():
    out = align_to_posting(BULLETS, "We want infrastructure as code experience.", length_budget=60)
    assert "infrastructure as code" in out.bullets[0]
    assert "IaC" not in out.bullets[0]


def test_abbreviates_when_the_posting_abbreviates():
    out = align_to_posting(BULLETS, "Strong K8s background required.")
    assert "K8s" in out.bullets[2]


def test_leaves_bullets_alone_when_the_posting_says_neither_form():
    out = align_to_posting(BULLETS, "We are a fast-moving team that values ownership.")
    assert out.bullets == BULLETS
    assert out.changed == 0


def test_leaves_bullets_alone_when_the_posting_uses_both_forms():
    """No preference to align to, so changing the wording gains nothing."""
    out = align_to_posting(BULLETS, "Kubernetes (K8s) experience required.")
    assert out.bullets[2] == BULLETS[2]


# --------------------------------------------------------------------------
# It does not fabricate
# --------------------------------------------------------------------------

def test_never_substitutes_a_specific_product_for_a_general_one():
    """The retrieval alias table treats EKS, AKS and GKE as Kubernetes. They are
    not interchangeable claims: writing EKS when the work was AKS is false."""
    out = align_to_posting(BULLETS, "Deep EKS and GKE experience required.")
    for word in ("EKS", "GKE", "AKS"):
        assert word not in plain(out.bullets[2])


def test_never_introduces_a_vector_database_claim():
    """The candidate's notes say verbatim: do not claim you had a vector
    database unless you actually did. RAG and 'vector search' share a retrieval
    tag, so a naive implementation would swap them."""
    bullets = ["<b>Built a RAG system</b> for out-of-stock recommendations."]
    out = align_to_posting(bullets, "Experience with vector search and embeddings required.")
    assert "vector" not in plain(out.bullets[0]).lower()
    assert "embedding" not in plain(out.bullets[0]).lower()


def test_never_swaps_a_managed_service_for_the_thing_it_manages():
    bullets = ["<b>Streamed events through Kafka</b> at 200K+ events/day."]
    out = align_to_posting(bullets, "We run MSK in production.")
    assert "MSK" not in plain(out.bullets[0])


def figures(text: str) -> set[str]:
    """Metrics only. A digit inside a word - K8s, Log4j, S3 - is part of a name,
    not a claim about scale."""
    return set(re.findall(r"(?<![A-Za-z0-9])\d[\d,.]*\+?%?(?![A-Za-z])", plain(text)))


def test_numbers_and_employers_are_never_touched():
    posting = "infrastructure as code, machine learning, K8s, high availability"
    out = align_to_posting(BULLETS, posting, length_budget=80)
    for before, after in zip(BULLETS, out.bullets):
        assert figures(before) == figures(after)
    assert "SageMaker" in out.bullets[1]


# --------------------------------------------------------------------------
# It respects the slot
# --------------------------------------------------------------------------

def test_drops_a_substitution_that_would_overflow_the_slot():
    """The PDF overlays each bullet into a fixed-height slot. Gaining a keyword
    at the cost of a broken layout is a bad trade."""
    out = align_to_posting(BULLETS, "infrastructure as code required", length_budget=0)
    assert out.bullets[0] == BULLETS[0]
    assert out.skipped_for_length >= 1


def test_output_stays_within_budget_when_it_does_substitute():
    out = align_to_posting(BULLETS, "infrastructure as code required", length_budget=60)
    assert len(plain(out.bullets[0])) <= len(plain(BULLETS[0])) + 60


def test_bold_lead_survives():
    out = align_to_posting(BULLETS, "machine learning required", length_budget=60)
    for bullet in out.bullets:
        assert bullet.startswith("<b>")
        assert bullet.count("<b>") == bullet.count("</b>") == 1


# --------------------------------------------------------------------------
# Shape of the whole thing
# --------------------------------------------------------------------------

def test_tailor_returns_every_bullet_in_order():
    result = tailor(BULLETS, "Platform Engineer", "infrastructure as code and K8s")
    assert len(result["bullets"]) == len(BULLETS)
    assert result["method"] == "deterministic"
    assert "Kubernetes" in result["requirements"]


def test_safe_synonym_table_contains_only_spelling_variants():
    """A guard on the table itself. Every pair must be an abbreviation and its
    expansion - if someone adds two merely *related* technologies here, the
    no-fabrication tests above stop protecting anything."""
    for canonical, alternate in SAFE_SYNONYMS:
        # Short, and starting from the same word as the thing it stands for.
        # Deliberately structural rather than clever: numeronyms (K8s) and
        # slashed forms (CI/CD) are legitimate abbreviations that an
        # initials-only check rejects, while any pair of genuinely different
        # technologies fails one of these two conditions.
        assert len(alternate) <= 6, f"{alternate!r} is too long to be an abbreviation"
        assert alternate[0].lower() == canonical[0].lower(), (
            f"{alternate!r} does not start from {canonical!r} - if these are two "
            "different technologies rather than two spellings of one, they must "
            "not be in this table"
        )
        assert len(alternate) < len(canonical)
