"""Tests for the skill -> evidence index that feeds resume tailoring.

The behaviours pinned here are the ones that were actually wrong at some point
during the build, plus the two that matter for honesty: a personal project must
never lose its label, and a requirement with no evidence must be reported as
uncovered rather than quietly dropped.
"""

from __future__ import annotations

import json

import pytest

from app.services import story_index as si
from app.services.story_index import (
    Story,
    StoryIndex,
    build_evidence_brief,
    extract_tags,
    flat_tags,
    normalize_tag,
)


def make(sid: str, *, tech=(), concepts=(), primary=(), evidence="professional",
         body="body text", metrics=(), dnc=()) -> Story:
    return Story(
        id=sid, title=sid, company="ACME", kind="deep-story", headline="",
        body=body, technologies=set(tech), concepts=set(concepts),
        primary=set(primary), evidence=evidence, metrics=list(metrics),
        do_not_claim=list(dnc),
    )


# --------------------------------------------------------------------------
# Vocabulary
# --------------------------------------------------------------------------

def test_aliases_normalise_to_one_canonical_tag():
    for surface in ("Kubernetes", "k8s", "EKS", "container orchestration"):
        assert "Kubernetes" in extract_tags(f"We run on {surface} in production")["technologies"]


def test_punctuation_heavy_terms_match():
    tags = extract_tags("Stack is C#/.NET with CI/CD via Azure DevOps")["technologies"]
    assert {"C#", ".NET", "CI/CD"} <= tags


def test_ambiguous_words_do_not_match_case_insensitively():
    """The bug this guards: "go through the rest of the templates at the helm"
    tagged a team-culture story as Go, REST and Helm, putting it at the top of
    a Go backend search."""
    prose = "We go through the rest of the backlog together; she is at the helm of the team."
    tags = extract_tags(prose)["technologies"]
    assert "Go" not in tags
    assert "REST" not in tags
    assert "Helm" not in tags


def test_ambiguous_words_still_match_when_written_as_the_technology():
    assert "Go" in extract_tags("Go and Rust experience required")["technologies"]
    assert "Go" in extract_tags("golang microservices")["technologies"]
    assert "REST" in extract_tags("designing a REST API")["technologies"]
    assert "Helm" in extract_tags("author Helm charts")["technologies"]


def test_normalize_tag_maps_surface_forms():
    assert normalize_tag("k8s") == "Kubernetes"
    assert normalize_tag("Kubernetes") == "Kubernetes"
    assert normalize_tag("nonsense-tech") is None


# --------------------------------------------------------------------------
# Selection
# --------------------------------------------------------------------------

def test_select_prefers_coverage_over_repeating_the_same_strength():
    """Three stories about Kubernetes and one about streaming. Ranked by score
    the Kubernetes ones take every slot; chosen for coverage, the streaming
    story gets in because it is the only thing that covers Kafka."""
    index = StoryIndex([
        make("k8s-a", tech=["Kubernetes", "Terraform"], primary=["Kubernetes"]),
        make("k8s-b", tech=["Kubernetes", "Terraform"], primary=["Kubernetes"]),
        make("k8s-c", tech=["Kubernetes", "Helm"], primary=["Kubernetes"]),
        make("stream", tech=["Kafka"], primary=["Kafka"]),
    ])
    chosen = index.select("Kubernetes, Terraform, Helm and Kafka", limit=2)
    assert "stream" in {m.story.id for m in chosen}


def test_select_stops_when_nothing_new_is_covered():
    index = StoryIndex([
        make("a", tech=["Kubernetes"]),
        make("b", tech=["Kubernetes"]),
    ])
    assert len(index.select("Kubernetes please", limit=5)) == 1


def test_covers_excludes_what_an_earlier_story_already_covered():
    index = StoryIndex([
        make("broad", tech=["Kubernetes", "Terraform", "Kafka"]),
        make("narrow", tech=["Kubernetes", "Redis"]),
    ])
    chosen = index.select("Kubernetes Terraform Kafka Redis", limit=2)
    by_id = {m.story.id: m for m in chosen}
    assert by_id["narrow"].covers == ["Redis"]
    # matched still reports everything the story speaks to.
    assert "Kubernetes" in by_id["narrow"].matched


def test_professional_evidence_wins_a_tie_but_does_not_exclude_projects():
    index = StoryIndex([
        make("pro", tech=["Kubernetes"], evidence="professional"),
        make("side", tech=["Kubernetes"], evidence="personal-project"),
    ])
    assert index.select("Kubernetes", limit=1)[0].story.id == "pro"

    # When the personal project is the only evidence, it is still selected -
    # the alternative is claiming the skill with nothing behind it.
    only_side = StoryIndex([make("side", tech=["Kubernetes"], evidence="personal-project")])
    assert only_side.select("Kubernetes", limit=1)[0].story.id == "side"


def test_title_requirements_outweigh_body_mentions():
    index = StoryIndex([
        make("kafka-story", tech=["Kafka"], primary=["Kafka"]),
        make("k8s-story", tech=["Kubernetes"], primary=["Kubernetes"]),
    ])
    chosen = index.select("nice to have: Kubernetes exposure", title="Kafka Streaming Engineer")
    assert chosen[0].story.id == "kafka-story"


def test_no_requirements_returns_nothing_rather_than_everything():
    index = StoryIndex([make("a", tech=["Kubernetes"])])
    assert index.select("We are a fast paced team that values ownership") == []


# --------------------------------------------------------------------------
# Coverage reporting
# --------------------------------------------------------------------------

def test_coverage_reports_requirements_with_no_evidence():
    index = StoryIndex([make("a", tech=["Kubernetes"])])
    chosen = index.select("Kubernetes and Rust and Flink")
    report = index.coverage(chosen, "Kubernetes and Rust and Flink")
    assert "Flink" in report["uncovered"]
    assert "Kubernetes" in report["covered"]
    assert 0 < report["weightedCoverage"] < 1


def test_full_coverage_is_reported_as_one():
    index = StoryIndex([make("a", tech=["Kubernetes", "Terraform"])])
    chosen = index.select("Kubernetes and Terraform")
    assert index.coverage(chosen, "Kubernetes and Terraform")["weightedCoverage"] == 1.0


# --------------------------------------------------------------------------
# The brief that reaches the model
# --------------------------------------------------------------------------

def test_brief_labels_personal_projects_every_time():
    index = StoryIndex([make("side", tech=["Kubernetes"], evidence="personal-project")])
    brief = build_evidence_brief(index.select("Kubernetes"))
    assert "PERSONAL PROJECT" in brief


def test_brief_carries_do_not_claim_lines():
    index = StoryIndex([
        make("s", tech=["SageMaker"], dnc=["I built the model - another team did"])
    ])
    brief = build_evidence_brief(index.select("SageMaker"))
    assert "MUST NOT claim" in brief
    assert "another team did" in brief


def test_brief_respects_its_character_budget():
    index = StoryIndex([
        make("a", tech=["Kubernetes"], body="x" * 50_000),
        make("b", tech=["Kafka"], body="y" * 50_000),
    ])
    brief = build_evidence_brief(index.select("Kubernetes and Kafka"), char_budget=4000)
    # Budget governs the bodies; headers and labels are small and additive.
    assert len(brief) < 6000


def test_brief_is_empty_when_nothing_matched():
    assert build_evidence_brief([]) == ""


# --------------------------------------------------------------------------
# Skill map
# --------------------------------------------------------------------------

def test_skill_map_ranks_a_story_that_is_about_the_skill_first():
    index = StoryIndex([
        make("mentions", tech=["Kubernetes"], body="z" * 9000),
        make("about", tech=["Kubernetes"], primary=["Kubernetes"], body="z" * 100),
    ])
    assert index.skill_map()["Kubernetes"]["best"] == "about"


def test_skill_map_lists_a_secondary_story():
    index = StoryIndex([
        make("first", tech=["Kafka"], primary=["Kafka"]),
        make("second", tech=["Kafka"]),
    ])
    assert index.skill_map()["Kafka"]["secondary"] == ["second"]


# --------------------------------------------------------------------------
# The real corpus
# --------------------------------------------------------------------------

@pytest.fixture(scope="module")
def real_index() -> StoryIndex:
    si.reset_index_cache()
    index = si.get_index()
    if not index.stories:
        pytest.skip("interview-story-corpus.json not present in this checkout")
    return index


def test_corpus_records_are_well_formed(real_index):
    for story in real_index.stories:
        assert story.id and story.title, story.id
        assert story.body.strip(), story.id
        assert story.evidence in si.EVIDENCE_TIERS, (story.id, story.evidence)


def test_corpus_ids_are_unique():
    records = si.load_corpus()
    if not records:
        pytest.skip("corpus not present")
    ids = [r["id"] for r in records]
    assert len(ids) == len(set(ids))


def test_corpus_personal_projects_are_not_labelled_professional(real_index):
    for story in real_index.stories:
        if story.id.startswith("proj-"):
            assert story.evidence == "personal-project", story.id


@pytest.mark.parametrize(
    "title,jd,expected",
    [
        ("Security Software Engineer",
         "Insider risk detection, compliance and governance on Azure with C#/.NET, Cosmos DB "
         "and Event Hubs.",
         "ms-"),
        ("Machine Learning Engineer",
         "Productionize models on SageMaker. XGBoost, inference endpoints, shadow mode.",
         "amz-"),
        ("Platform Engineer",
         "Kubernetes, Terraform and Helm for an internal developer platform.",
         "proj-"),
    ],
)
def test_real_corpus_routes_postings_to_the_right_family(real_index, title, jd, expected):
    chosen = real_index.select(jd, title=title, limit=3)
    assert chosen, f"nothing retrieved for {title}"
    assert chosen[0].story.id.startswith(expected), chosen[0].story.id


def test_real_corpus_does_not_tag_ordinary_english_as_a_language(real_index):
    """Regression: 11 stories were tagged Go and 6 REST purely from prose."""
    go_stories = real_index.by_tag.get("Go", [])
    assert all(s.startswith("proj-") for s in go_stories), go_stories
