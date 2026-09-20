import asyncio
from copy import deepcopy

import pytest

from app.services.resume_intelligence import evidence_match as em
from app.services.resume_intelligence import minimal_tailoring as mt
from app.services.resume_intelligence.baseline_document import approved_path, render_baseline
from app.services.application_assistant import candidate_match_context as context
from app.services.application_assistant.mistral_resume_match import _is_evidenced, score_job_against_resume
from app.services.application_assistant.job_matching import match_job
from tests.resume_baseline_fixture import baseline


@pytest.fixture(autouse=True)
def clear_cache():
    em._match.cache_clear()
    yield
    em._match.cache_clear()


def test_direct_document_evidence_not_zero_and_partial_compound():
    full=em.match_text("Built Kubernetes Python services.","Required: Kubernetes Python services.",use_semantic=False)
    assert full["score"] == 100
    partial=em.match_text("Built Kubernetes services.","Required: Kubernetes Python services.",use_semantic=False)
    assert partial["requirements"][0]["status"]=="partial"
    assert partial["score"]==50
    assert partial["requirements"][0]["missingSkills"]==["Python"]


def test_short_names_boundaries_and_negation():
    assert not _is_evidenced("Go","built django services",set())
    assert not _is_evidenced("Java","built javascript services",set())
    assert {"go","c#","c++"} <= context.extract_keywords("Go C# C++")
    for text in ("I have no Kubernetes experience.", "I have no experience with Kubernetes.", "I never used Kubernetes."):
        assert em.match_text(text,"Required: Kubernetes experience.",use_semantic=False)["score"]==0


def test_boilerplate_duplicates_and_tail_requirements():
    jd="Requirements\nBuild Kubernetes Python services.\nBuild Kubernetes Python services.\nBenefits\nHealthcare and holidays."
    reqs=em.extract_requirements(jd)
    assert len(reqs)==1
    text="Built Kubernetes Python services."
    a=em.match_text(text,jd,use_semantic=False)
    b=em.match_text(text,jd+"\nCompensation\nSalary and benefits. "*100,use_semantic=False)
    assert a["score"]==b["score"]
    long="About us\n"+"Company introduction. "*500+"\nRequirements\nPython Kubernetes services."
    assert any("Python Kubernetes" in r["text"] for r in em.extract_requirements(long))


def test_unknown_not_failed_and_quantity_needs_review():
    assert em.match_text("Python engineer.","Benefits\nGreat holidays.",use_semantic=False)["score"] is None
    r=em.match_text("Built Python services.","Required: 5 years of Python services experience.",use_semantic=False)
    assert r["requirements"][0]["status"]=="partial"
    assert r["requirements"][0]["quantityNeedsReview"]
    assert em.match_text("5 years of Python services experience.","Required: 5 years of Python services experience.",use_semantic=False)["score"]==100


def test_or_alternatives_and_irrelevant_shared_word():
    assert em.match_text("Built Python services.","Required: Python or Go services.",use_semantic=False)["requirements"][0]["missingSkills"]==[]
    j={"title":"Engineer","description":"Requirements\nExperience developing Rust kernels for embedded avionics safety certification."}
    assert match_job(j,{"skills":["experience"]})["requiredCoverage"]==0


def test_resume_cache_uses_content_not_length(monkeypatch):
    monkeypatch.setattr(context,"extract_text_from_attachment",lambda r:r["base64"])
    context._resume_text_cache.clear()
    assert context._cached_resume_text({"id":"x","base64":"AAAA"})=="AAAA"
    assert context._cached_resume_text({"id":"x","base64":"BBBB"})=="BBBB"
    context._resume_text_cache.clear()


def test_cache_is_defensive_and_embeddings_fall_back(monkeypatch):
    def fail(_):raise MemoryError()
    monkeypatch.setattr(em.semantic,"embed_many",fail)
    result=em.match_text("Built Python services.","Required: Python services.")
    assert not result["semanticAvailable"]
    result["requirements"].clear()
    assert em.match_text("Built Python services.","Required: Python services.")["requirements"]
    assert em._match.cache_info().hits>=1


def test_strong_semantic_negation_does_not_certify_evidence(monkeypatch):
    # Both directions are stubbed: passages and queries are embedded by
    # separate calls now, because BGE wants its query instruction on one side
    # and not the other. Faking maximal similarity needs to cover both.
    identical=lambda items:{em.semantic.cache_key(*i):(1.,0.) for i in items}
    monkeypatch.setattr(em.semantic,"embed_many",identical)
    monkeypatch.setattr(em.semantic,"embed_queries",identical)
    r=em.match_text("I have no experience with Kubernetes.","Required: Kubernetes experience.")
    assert r["semanticAvailable"] and r["score"]==0


def test_off_exact_and_pdf_comparison_reorder_invariant(baseline):
    jd="Required: Kubernetes infrastructure and production recovery."
    off=mt.tailor([],jd,mode="off")
    data=render_baseline(off)
    assert data==approved_path().read_bytes()
    comparison=em.compare_pdfs(data,data,jd,use_semantic=False)
    assert comparison["delta"]==0 and not comparison["changed"]
    reorder=mt.tailor([],jd,config=mt.TailoringConfig(use_semantic=False))
    comparison=em.compare_pdfs(data,render_baseline(reorder),jd,use_semantic=False)
    assert comparison["delta"]==0


def test_modes_preserve_configuration_and_aggressive_changes_more(baseline,monkeypatch):
    assert mt.mode_config("aggressive",{"max_replacement_fraction":.2,"bm25_k1":1.8}).max_replacement_fraction==.2
    assert mt.mode_config("aggressive",{"bm25_k1":1.8}).bm25_k1==1.8
    records=[{"id":str(i),"company":"Example","role":"Engineer","project":"Recovery","resumeApproved":True,"evidenceTier":"professional","currentBullet":text} for i,text in enumerate([
        "Built Python production recovery automation, improving deployment reliability 45%.",
        "Designed Kubernetes incident recovery services, reducing production failures 60%."])]
    def ranks(candidates,reqs,config):
        return ([.1,.5,.85,.9,1.,.98][:len(candidates)],[["req-1"] for _ in candidates],None)
    monkeypatch.setattr(mt,"_rank",ranks)
    honest=mt.tailor(records,"Required: Python Kubernetes production recovery automation.",mode="honest",fit_check=lambda *_:True)
    aggressive=mt.tailor(records,"Required: Python Kubernetes production recovery automation.",mode="aggressive",fit_check=lambda *_:True)
    assert sum(b["decision"]=="REPLACE" for b in aggressive["resumeBullets"]) > sum(b["decision"]=="REPLACE" for b in honest["resumeBullets"])
    for result in (honest,aggressive):
        for b in result["resumeBullets"]:
            assert b["source"]["text"]==b["optimizedBullet"]
    with pytest.raises(ValueError):mt.mode_config("invent")


def test_local_model_prompt_keeps_late_requirements():
    seen=[]
    class Client:
        enabled=True
        async def complete(self,prompt,**kwargs):
            seen.append(prompt)
            return {"success":False}
    asyncio.run(score_job_against_resume(Client(),{"description":"About us\n"+"Company. "*1000+"\nRequirements\nCRITICAL_FINAL_REQUIREMENT Python services."},candidate_summary="Python engineer",evidence_text="python",evidence_terms={"python"}))
    assert "CRITICAL_FINAL_REQUIREMENT" in seen[0]
