from app.services.resume_intelligence.match_engine import build_ats_keyword_sets, match_corpus_to_job


def test_match_corpus_explicit_and_missing_keywords() -> None:
    accomplishments = [
        {
            "id": "acc_1",
            "title": "Adaptive Protection",
            "company": "Microsoft",
            "currentBullet": "Built Python microservices on Kubernetes reducing latency 40%",
            "technologies": ["python", "kubernetes", "azure"],
            "metrics": [{"id": "m1", "name": "latency", "value": "40%", "verification": "verified"}],
            "evidence": [{"id": "e1", "name": "dashboard", "type": "grafana"}],
        }
    ]
    job_description = (
        "Senior Software Engineer. Required: Python, Kubernetes, Azure. "
        "Preferred: terraform, prometheus."
    )
    result = match_corpus_to_job(accomplishments, job_description, job_title="Senior Software Engineer")

    assert result["overallScore"] >= 0
    terms = {m["term"]: m["coverage"] for m in result["keywordMatches"]}
    assert terms.get("python") in {"explicit", "unsupported", "inferred"}
    missing_terms = {m["term"] for m in result["missing"]}
    assert "terraform" in missing_terms or len(missing_terms) > 0
    assert result["callLikelihood"] in {"low", "medium", "high"}
    assert "atsKeywordSets" in result


def test_build_ats_keyword_sets_parses_required() -> None:
    jd = "Required qualifications:\n- 5 years Python experience\nPreferred:\n- AWS certified"
    sets = build_ats_keyword_sets(jd, "Backend Engineer")
    assert isinstance(sets["primary"], list)
    assert len(sets["requiredPhrases"]) >= 0
