import base64
from io import BytesIO

import pytest
from pypdf import PdfReader

from app.services.resume_intelligence import semantic
from app.services.resume_intelligence.bm25 import BM25Index
from app.services.resume_intelligence.fusion import reciprocal_rank_fusion
from app.services.resume_intelligence.local_composer import compose, requirements, validate_sources


def evidence(**updates):
    return {"id": "platform", "company": "Example", "project": "Reliable platform", "evidenceTier": "professional",
            "currentBullet": "Built Kubernetes infrastructure with automated deployments and reliable recovery.", **updates}


# --- BM25 -------------------------------------------------------------------

def test_bm25_ranks_by_term_frequency_and_length_normalization():
    docs = [
        ("built", "kubernetes", "infrastructure", "with", "automated", "deployments"),
        ("wrote", "unrelated", "documentation", "for", "onboarding"),
        ("designed", "kubernetes", "kubernetes", "operator", "for", "multi", "cluster", "rollout"),
    ]
    index = BM25Index.build(docs)
    ranked = index.rank(("kubernetes",))
    assert ranked[0] == 2  # higher kubernetes term frequency
    assert ranked[-1] == 1  # no occurrence at all


def test_bm25_favors_specific_technical_match_over_generic_bullet():
    records = [
        evidence(id="k8s", currentBullet="Built Kubernetes infrastructure with automated deployments and reliable recovery."),
        evidence(id="generic", company="Other", currentBullet="Worked on various backend improvements across several teams."),
    ]
    result = compose(records, "Required: Kubernetes infrastructure.", "Platform Engineer")
    assert [b["id"] for b in result["resumeBullets"]] == ["k8s"]


# --- RRF ----------------------------------------------------------------

def test_reciprocal_rank_fusion_rewards_agreement_across_lists():
    list_a = [0, 1, 2, 3]
    list_b = [2, 0, 1, 3]
    scores = reciprocal_rank_fusion([list_a, list_b], k=60)
    ranked = sorted(scores, key=lambda i: -scores[i])
    assert ranked[0] == 0  # best in A, second in B
    assert ranked[-1] == 3  # worst in both


# --- Semantic embeddings (paraphrase-aware) ---------------------------------

def test_semantic_embeddings_score_paraphrase_higher_than_unrelated():
    if not semantic.is_available():
        pytest.skip("local sentence-embedding model is not available in this environment")
    vectors = semantic.embed_many([
        ("req", "Experience scaling systems to handle a large volume of concurrent user requests."),
        ("a", "Redesigned the backend to support significantly higher traffic and concurrent load."),
        ("b", "Coordinated the quarterly holiday party and ordered catering for the team."),
    ])
    req = vectors[semantic.cache_key("req", "Experience scaling systems to handle a large volume of concurrent user requests.")]
    close = vectors[semantic.cache_key("a", "Redesigned the backend to support significantly higher traffic and concurrent load.")]
    far = vectors[semantic.cache_key("b", "Coordinated the quarterly holiday party and ordered catering for the team.")]
    assert semantic.cosine(req, close) > semantic.cosine(req, far)


def test_semantic_embeddings_are_cached_by_revision_and_text():
    if not semantic.is_available():
        pytest.skip("local sentence-embedding model is not available in this environment")
    first = semantic.embed_many([("rev-1", "Built Kubernetes infrastructure.")])
    key = semantic.cache_key("rev-1", "Built Kubernetes infrastructure.")
    assert key in semantic._cache  # noqa: SLF001 - verifying the cache population directly
    second = semantic.embed_many([("rev-1", "Built Kubernetes infrastructure.")])
    assert first[key] == second[key]


def test_compose_exposes_ranking_explainability():
    records = [evidence(), evidence(id="b", company="Other",
        currentBullet="Reduced production outages by forty percent through improved on-call runbooks and monitoring.")]
    result = compose(records, "Required: Kubernetes infrastructure.\nPreferred: reduce production outages.", "Platform Engineer")
    assert result["rankingDebug"]["semanticAvailable"] == semantic.is_available()
    for bullet in result["resumeBullets"]:
        debug = bullet["debug"]
        assert debug["bm25Rank"] is not None
        assert {"matchedRequirementIds", "matchedTags", "rrfScore", "qualityScore",
                "diversityPenalty", "finalRelevance", "lineCostEstimate"} <= set(debug)


# --- Fallback (embeddings unavailable) --------------------------------------

def test_semantic_unavailable_falls_back_to_bm25_and_taxonomy(monkeypatch):
    monkeypatch.setattr("app.services.resume_intelligence.local_composer.semantic.embed_many", lambda items: None)
    result = compose([evidence()], "Required: Kubernetes infrastructure.", "Platform Engineer")
    assert result["resumeBullets"]
    assert result["rankingDebug"]["semanticAvailable"] is False
    assert result["resumeBullets"][0]["debug"]["semanticRank"] is None


# --- MMR diversity ------------------------------------------------------

def test_mmr_prefers_a_diverse_bullet_over_a_near_duplicate():
    records = [
        evidence(id="a", currentBullet="Built Kubernetes infrastructure with automated deployments and reliable recovery workflows."),
        evidence(id="b", currentBullet="Built Kubernetes infrastructure with automated rollout and reliable recovery pipelines."),
        evidence(id="c", company="Other", currentBullet="Designed Python automation tooling that reduced manual deployment errors significantly."),
    ]
    jd = "Required: Kubernetes infrastructure and automated deployments.\nPreferred: Python automation tooling."
    result = compose(records, jd, "Platform Engineer", max_bullets=2, use_semantic=False)
    ids = [b["id"] for b in result["resumeBullets"]]
    assert ids == ["a", "c"]


# --- Requirement parsing: dedup ------------------------------------------

def test_requirements_deduplicate_near_identical_and_reordered_clauses():
    reqs = requirements(
        "Required: Kubernetes infrastructure and automated deployments.\n"
        "Required: automated deployments and Kubernetes infrastructure!\n"
        "Required: Python data pipelines."
    )
    required_texts = [r["text"] for r in reqs if r["category"] == "required"]
    assert len(required_texts) == 2


def test_requirement_categories_unaffected_by_dedup():
    reqs = requirements("Required:\nKubernetes operations\nPreferred:\nPython automation\nResponsibilities:\nMentor junior engineers")
    assert [r["category"] for r in reqs] == ["required", "preferred", "responsibility"]


# --- Determinism ----------------------------------------------------------

def test_composition_is_deterministic():
    records = [evidence(), evidence(id="b", company="Other",
        currentBullet="Reduced infrastructure costs by twenty percent through automated Kubernetes scaling.")]
    jd = "Required: Kubernetes infrastructure and cost optimization.\nPreferred: automated scaling."
    first = compose(records, jd, "Platform Engineer")
    second = compose(records, jd, "Platform Engineer")
    assert [b["id"] for b in first["resumeBullets"]] == [b["id"] for b in second["resumeBullets"]]
    assert [b["debug"]["finalRelevance"] for b in first["resumeBullets"]] == [b["debug"]["finalRelevance"] for b in second["resumeBullets"]]


# --- Provenance validation still holds under the new ranking ------------

def test_validate_sources_ignores_new_debug_fields():
    records = [evidence()]
    result = compose(records, "Kubernetes infrastructure")
    assert validate_sources(result, records) == []
    assert "debug" in result["resumeBullets"][0]


# --- One-page fitting (resume_studio, real ReportLab render) ---------------

def test_resume_studio_generates_a_single_page_pdf():
    from app.services.resume_intelligence.resume_studio import generate_studio
    records = [evidence(id=f"acc-{i}", company="Example",
        currentBullet=f"Delivered feature {i} that improved Kubernetes deployment reliability and reduced production outages by automating rollout checks.")
        for i in range(10)]
    profile = {"firstName": "Test", "lastName": "Candidate",
               "workExperience": [{"company": "Example", "jobTitle": "Engineer", "startDate": "2020", "endDate": "Present"}]}
    jd = "Required: Kubernetes infrastructure, automated deployments, and reducing production outages. " * 5
    out = generate_studio(records, profile, jd, "Senior Engineer", "Example Co")
    pdf_bytes = base64.b64decode(out["pdfBase64"])
    assert len(PdfReader(BytesIO(pdf_bytes)).pages) == 1
    assert out["pageCount"] == 1
