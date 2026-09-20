import asyncio
from copy import deepcopy
from io import BytesIO

import pytest
from pypdf import PdfReader

from app.services.resume_intelligence.local_composer import compose, requirements, validate_sources
from app.services.resume_intelligence.local_document import render


def evidence(**updates):
    # `resumeApproved` is explicit because approval is now one shared policy
    # (see story_index.resume_approval_state) rather than "anything not marked
    # false". These tests are about exact sourcing and rendering, so they state
    # that their evidence was approved instead of relying on a default; the
    # tests that are about approval set it, or the metrics behind it, themselves.
    return {"id": "platform", "company": "Example", "project": "Reliable platform", "evidenceTier": "professional",
            "resumeApproved": True,
            "currentBullet": "Built Kubernetes infrastructure with automated deployments and reliable recovery.", **updates}


def test_local_composition_uses_exact_sources_and_distinguishes_projects():
    records = [evidence(), evidence(id="personal", company="Home", evidenceTier="personal-project",
        currentBullet="Built Python data pipelines with repeatable analysis and regression testing.")]
    result = compose(records, "Required: Kubernetes infrastructure.\nPreferred: Python data pipelines.", "Platform Engineer")
    assert len(result["resumeBullets"]) == 2
    assert result["atsMatchScore"] is None
    assert validate_sources(result, records) == []
    for bullet in result["resumeBullets"]:
        assert bullet["optimizedBullet"] == bullet["source"]["text"]
    pdf = PdfReader(BytesIO(render(result, {"firstName": "Test", "lastName": "Candidate"})))
    assert len(pdf.pages) == 1
    assert "Personal projects" in pdf.pages[0].extract_text()


def test_unverified_metrics_never_become_exportable():
    result = compose([evidence(metrics=[{"value": "99.99%", "verification": "needs-evidence"}])], "Kubernetes infrastructure")
    assert not result["exportReady"]
    with pytest.raises(ValueError):
        render(result, {})
    assert "DRAFT" in PdfReader(BytesIO(render(result, {}, draft=True))).pages[0].extract_text()


def test_edits_and_tampered_bullets_invalidate_export():
    records = [evidence()]
    result = compose(records, "Kubernetes infrastructure")
    changed = deepcopy(records)
    changed[0]["currentBullet"] += " Updated."
    assert validate_sources(result, changed)
    result["resumeBullets"][0]["optimizedBullet"] += " With 100% uptime."
    assert validate_sources(result, records)


def test_unwritten_stories_and_unknown_requirements_are_not_hidden():
    result = compose([evidence(strength="unwritten")], "Required: Kubernetes infrastructure and quantum networking")
    assert not result["resumeBullets"]
    assert result["uncoveredRequirements"]


def test_requirement_categories():
    reqs = requirements("Required:\nKubernetes operations\nPreferred:\nPython automation\nResponsibilities:\nMentor junior engineers")
    assert [r["category"] for r in reqs] == ["required", "preferred", "responsibility"]


def test_both_entrypoints_make_no_model_calls(monkeypatch):
    from app.services import llm
    from app.services.application_assistant import resume_diff_service as service
    async def forbidden(*args, **kwargs):
        pytest.fail("Local resume composition must not call a model")
    monkeypatch.setattr(llm, "call_openrouter_json", forbidden)
    result = asyncio.run(llm.generate_resume_bullets_for_job([evidence()], "Example", "Engineer", "Kubernetes infrastructure", "Senior", "aggressive", 1, 99))
    diff = asyncio.run(service.generate_role_tailoring_diff({"description": "Kubernetes infrastructure", "title": "Engineer"}, {}, accomplishments=[evidence()]))
    assert result["resumeBullets"] == diff["resumeDocument"]["resumeBullets"]
    assert diff["tailoringModel"] == "none (local evidence selection)"


def test_import_refresh_preserves_local_edits_and_history():
    from app.db.story_corpus_sync import _apply
    story = {"id": "story", "body": "Original body"}
    record = _apply({}, story)
    refreshed = _apply(record, {**story, "body": "Corrected body"})
    assert refreshed["interviewStories"][0]["body"] == "Corrected body"
    assert refreshed["interviewStories"][0]["history"] == [{"body": "Original body"}]
    record["interviewStories"][0]["body"] = "Local edit"
    assert _apply(record, {**story, "body": "New import"})["interviewStories"][0]["body"] == "Local edit"


def test_legacy_ui_edits_and_metric_reviews_are_authoritative():
    record = evidence(resumeEvolution={"current": "Built Python automation for repeatable deployments and production recovery."},
                      metricMetadata={"metric-1": {"verification": "needs-evidence"}})
    result = compose([record], "Python automation")
    assert result["resumeBullets"][0]["source"]["field"] == "resumeEvolution.current"
    assert result["resumeBullets"][0]["optimizedBullet"] == record["resumeEvolution"]["current"]
    assert not result["exportReady"]


def test_cannot_move_claims_to_another_company_or_add_skills():
    records = [evidence()]
    result = compose(records, "Kubernetes infrastructure")
    result["resumeBullets"][0]["company"] = "Invented Employer"
    assert validate_sources(result, records)
    result = compose(records, "Kubernetes infrastructure")
    result["skillsList"].append("Quantum teleportation")
    assert validate_sources(result, records)


def test_compound_requirement_reports_partial_support():
    result = compose([evidence()], "Required: Kubernetes infrastructure plus quantum networking and optical routing")
    assert result["uncoveredRequirements"]
    assert result["requirementCoverage"] < 100
