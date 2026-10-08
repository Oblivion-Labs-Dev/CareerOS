"""Production gates for the resume compiler: adversarial hallucination pressure, structured validation errors,
evidence query sanitising, feedback, immutable versions, PDF checks, apply-time freezing and deterministic metrics."""
import hashlib
import json
import re

import pytest

from app.services.career_compiler import critic, feedback, pipeline, versions
from app.services.career_compiler.docx_render import EstimateMeasurer, read_trace
from app.services.career_compiler.docx_template import golden_path, load_spec
from app.services.career_compiler.export import export
from app.services.career_compiler.models import (
    Bullet, JobDescription, Requirement, RequirementQuery, ResumeDocument, ResumePlan,
)
from app.services.career_compiler.pipeline import analyze, generate
from app.services.career_compiler.query import apply_query, sanitize
from app.services.career_compiler.retrieval import RETRIEVAL_VERSION, evidence_strength, retrieve_evidence
from app.services.career_compiler.scoring import evaluate
from app.services.career_compiler.store import default_path, load_store
from app.services.career_compiler.validator import numbers, validate_bullet, validate_document
from app.services.career_compiler.weights import requirement_weight
from tests.test_career_compiler import AWS_JD, CDK, bullet, fake_llm, honest_writer, jd_for

MONOLITH = "amazon.monolith_microservices"
PROMISE = "amazon.prediction_promise"
PRESSURE_JD = """Staff Software Engineer, Streaming Platform
Responsibilities:
- Build high-throughput distributed systems and microservices on AWS.
- Own CI/CD and infrastructure as code with AWS CDK for many services.
Required qualifications:
- 10+ years of experience with Go and Kafka.
- Experience with TypeScript or Java, DynamoDB, SQS and ECS.
Preferred qualifications:
- Kubernetes experience at million-TPS scale."""
FORBIDDEN = re.compile(r"\bGo\b|Kafka|\bStaff\b|10\+|\$100M|1M TPS", re.I)


@pytest.fixture(autouse=True)
def isolated(tmp_path, monkeypatch):
    monkeypatch.setenv("CAREEROS_JD_CACHE", str(tmp_path / "jd"))
    monkeypatch.setenv("CAREEROS_COMPILER_DATA", str(tmp_path / "compiler"))
    monkeypatch.setattr(pipeline, "_measurer", EstimateMeasurer)


@pytest.fixture()
def store():
    return load_store()


def sha(path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def offline():
    from app.services.career_compiler.deepseek import DeepSeekClient
    return DeepSeekClient(api_key="")


def analyzed(text=AWS_JD):
    result = analyze(text=text, llm=offline())
    return result, ResumePlan.model_validate(result["plan"])


# --------------------------------------------------------------------------- adversarial claims, one per rule


def codes(issues):
    return {i.code for i in issues}


def test_go_is_not_invented(store):
    issues = validate_bullet(bullet("Built shared CDK constructs in Go that cut service setup from 2 weeks to under 1 hour.",
                                    [f"{CDK}.metric.setup_time"]), store)
    assert [(i.code, i.claim) for i in issues] == [("unsupported_technology", "Go")]
    assert validate_bullet(bullet("Go-live setup fell from 2 weeks to under 1 hour.", [f"{CDK}.metric.setup_time"]), store) == []


def test_kafka_is_not_substituted_for_kinesis_or_sns(store):
    streaming = next(p for p in store.projects.values() if {"Kinesis", "SNS"} & set(p.technologies))
    claim = store.project_evidence(streaming.id)[0]
    text = claim.claim.rstrip(".") + ", streaming events through Kafka."
    issues = validate_bullet(Bullet(id=streaming.id, employment_id=streaming.employment_id, project_id=streaming.id,
                                    text=text, evidence_ids=[claim.id]), store)
    assert ("unsupported_technology", "Kafka") in {(i.code, i.claim) for i in issues}
    # Retrieval: Kinesis evidence is at best adjacent (weak) to a Kafka requirement, never strong or moderate.
    req = Requirement(id="R1", section="required_qualifications", original_text="Deep experience with Kafka.",
                      normalized_requirement="Kafka streaming", skills=["Kafka"])
    query = sanitize([RequirementQuery(requirement_id="R1", terms=["Kinesis", "SNS", "Event-Driven Architecture", "Flux"],
                                       adjacent=["SQS"])],
                     JobDescription(id="0" * 16, text="Deep experience with Kafka.", requirements=[req]), store)
    item = query.requirements[0]
    assert "Kinesis" not in item.terms and {"Kinesis", "SNS", "SQS"} <= set(item.adjacent) and "Flux" in query.dropped_terms
    expanded = req.model_copy(update={"query_terms": item.terms, "adjacent_terms": item.adjacent})
    strengths = {evidence_strength(expanded, e, store)[0] for e in store.evidence.values()
                 if e.project_id == streaming.id and e.usable}
    assert strengths <= {None, "weak"}


def test_one_million_tps_does_not_inflate_100k(store):
    tps = f"{MONOLITH}.scale.tps"
    base = dict(employment_id="employment.amazon", project_id=MONOLITH)
    inflated = validate_bullet(bullet("Moved the platform to microservices at 1M TPS.", [tps], **base), store)
    assert [(i.code, i.claim) for i in inflated] == [("unsupported_metric", "1M TPS")]
    assert any("100K+ TPS" in a for a in inflated[0].allowed_evidence)
    assert codes(validate_bullet(bullet("Moved the platform to microservices at 100M TPS.", [tps], **base), store)) == {"unsupported_metric"}
    assert validate_bullet(bullet("Moved the platform to microservices at 100,000+ TPS.", [tps], **base), store) == []
    assert numbers("100K+") == numbers("100,000") == {"100000"} and numbers("1M") == {"1000000"}


def test_kubernetes_appears_only_where_supported(store):
    assert "Kubernetes" in store.projects[MONOLITH].technologies
    assert codes(validate_bullet(bullet("Cut service setup from 2 weeks to under 1 hour on Kubernetes.",
                                        [f"{CDK}.metric.setup_time"]), store)) == {"unsupported_technology"}
    assert validate_bullet(bullet("Ran the migrated services on Kubernetes at 100K+ TPS.", [f"{MONOLITH}.scale.tps"],
                                  project_id=MONOLITH), store) == []


def test_staff_does_not_replace_senior_sde(store):
    as_staff = validate_bullet(bullet("As Staff Engineer, cut service setup from 2 weeks to under 1 hour.",
                                      [f"{CDK}.metric.setup_time"]), store)
    assert ("unsupported_title", "Staff") in {(i.code, i.claim) for i in as_staff}
    summary = Bullet(id="summary", employment_id="", project_id="", evidence_ids=["person.positioning.experience"],
                     text="Principal engineer with 8+ years of experience.")
    assert "unsupported_title" in codes(validate_bullet(summary, store, summary=True))


def test_ten_years_does_not_replace_eight(store):
    summary = Bullet(id="summary", employment_id="", project_id="", evidence_ids=["person.positioning.experience"],
                     text="Software engineer with 10+ years of experience in backend systems.")
    issues = validate_bullet(summary, store, summary=True)
    assert [(i.code, i.claim) for i in issues] == [("unsupported_experience", "10+ years")]
    assert issues[0].allowed_evidence == ["8+ years of experience"]
    assert validate_bullet(summary.model_copy(update={"text": "Software engineer with 8+ years of experience."}), store,
                           summary=True) == []


def test_100m_does_not_inflate_28m(store):
    impact = f"{PROMISE}.metric.annualized"
    base = dict(employment_id="employment.amazon", project_id=PROMISE)
    issues = validate_bullet(bullet("Built delivery-range prediction worth $100M in annualized impact.", [impact], **base), store)
    assert [(i.code, i.claim) for i in issues] == [("unsupported_metric", "$100M in")]
    assert validate_bullet(bullet("Built delivery-range prediction worth an estimated $28M in annualized impact.", [impact],
                                  **base), store) == []


def test_structured_errors_carry_claim_and_allowed_evidence(store):
    issue = validate_bullet(bullet("Cut setup from 2 weeks to 10 minutes.", [f"{CDK}.metric.setup_time"]), store)[0]
    dumped = issue.model_dump()
    assert {"bullet_id", "error", "claim", "allowed_evidence"} <= set(dumped)
    assert dumped["error"] == "unsupported_metric" and dumped["claim"] == "10 minutes"
    assert "2 weeks" in dumped["allowed_evidence"] and "1 hour" in dumped["allowed_evidence"]


def test_unsupported_scale_words_fail(store):
    issues = validate_bullet(bullet("Cut setup from 2 weeks to under 1 hour for millions of developers worldwide.",
                                    [f"{CDK}.metric.setup_time"]), store)
    assert codes(issues) == {"unsupported_scale"}


def test_relevance_pressure_never_overrides_precision(store):
    """The JD asks for Go, Kafka, Staff, 10+ years and million-TPS scale; the writer gives in on every one of them.
    Validation rejects each claim with a structured error, the repair keeps only evidence, and nothing ships."""
    result, plan = analyzed(PRESSURE_JD)
    repairs = []

    def pressured(body, payload):
        if "slots" not in payload:
            return honest_writer(body, payload)
        out = json.loads(honest_writer(body, payload))
        if payload.get("validation_errors"):
            repairs.append(payload["validation_errors"])
            return json.dumps(out)
        for item in out["bullets"]:
            item["text"] = item["text"].rstrip(".") + ", built in Go on Kafka at 1M TPS as Staff Engineer."
        if payload.get("summary_slot"):
            out["summary"] = {"text": "Staff engineer with 10+ years of experience and $100M impact with Kafka.",
                              "evidence_ids": ["person.positioning.experience"]}
        return json.dumps(out)

    output = generate(jd_id=result["jd"]["id"], plan=plan, llm=fake_llm(pressured))
    errors = [e for round_ in repairs for items in round_.values() for e in items]
    claims = {(e["code"], e["claim"]) for e in errors}
    assert {("unsupported_technology", "Go"), ("unsupported_technology", "Kafka"), ("unsupported_title", "Staff"),
            ("unsupported_experience", "10+ years")} <= claims
    assert any(e["code"] == "unsupported_metric" and e["claim"].startswith("1M") and e["allowed_evidence"] for e in errors)
    document = ResumeDocument.model_validate(output["document"])
    shipped = [b.text for b in ([document.summary] if document.summary else []) + document.bullets()]
    assert shipped and not any(FORBIDDEN.search(t) for t in shipped)
    assert output["valid"] and output["issues"] == []
    evaluation = output["evaluation"]
    assert evaluation["factual_precision"] == evaluation["technology_precision"] == 1.0
    assert evaluation["unsupported_claims"] == 0 and evaluation["conflict_leakage"] == 0
    gap_text = " ".join(r["text"] for r in evaluation["no_supported_evidence"])
    assert "Kafka" in gap_text, "the unsupported requirement is reported as a gap, not papered over"


# --------------------------------------------------------------------------- dates, conflicts, metrics


def test_employment_date_mutation_fails(store):
    result, plan = analyzed()
    output = generate(jd_id=result["jd"]["id"], plan=plan, llm=fake_llm(honest_writer))
    mutated = json.loads(json.dumps(output["document"]))
    amazon = next(s for s in mutated["sections"] if s["employment_id"] == "employment.amazon")
    amazon["start"] = "2017-01"
    issues = validate_document(ResumeDocument.model_validate(mutated), store)
    assert ("date_mismatch", "2017-01") in {(i.code, i.claim) for i in issues}
    with pytest.raises(ValueError, match="start must come from career.json"):
        export(mutated, "docx", measurer=EstimateMeasurer(load_spec()))
    dated = validate_bullet(bullet("In 2015 cut service setup from 2 weeks to under 1 hour.", [f"{CDK}.metric.setup_time"]), store)
    assert "date_mismatch" in codes(dated)


def test_metrics_are_deterministic_and_recall_ignores_unsupported_requirements(store):
    result, plan = analyzed(PRESSURE_JD)
    output = generate(jd_id=result["jd"]["id"], plan=plan, llm=fake_llm(honest_writer))
    jd = JobDescription.model_validate(result["jd"])
    document = ResumeDocument.model_validate(output["document"])
    retrieval = retrieve_evidence(jd, store)
    allowed = {p.project_id: {e.id for e in store.project_evidence(p.project_id)} for p in plan.selected_projects}
    args = dict(document=document, jd=jd, retrieval=retrieval, store=store, trace_rows=output["trace"]["requirements"],
                allowed=allowed, pages=1, drift=[])
    assert evaluate(**args) == evaluate(**args)
    gap = next(r for r in jd.requirements if "Kafka" in r.original_text)
    metrics = evaluate(**args)
    assert gap.id in [r["id"] for r in metrics["no_supported_evidence"]]
    assert gap.id not in [r["id"] for r in metrics["supported_but_not_used"]]
    assert requirement_weight(gap) == 3.0 and gap.required
    preferred = next(r for r in jd.requirements if r.section == "preferred_qualifications")
    assert requirement_weight(preferred) == 1.0 and not preferred.required
    assert 0 <= metrics["supported_jd_recall"] <= 1 and metrics["page_compliance"] == 1.0
    assert metrics["template_fidelity"] == 1.0 and metrics["conflict_leakage"] == 0


def test_a_bullet_only_claims_requirements_it_supports():
    b = Bullet(id="x", employment_id="e", project_id="x", text="t", evidence_ids=["e1"],
               requirements=[{"id": "R1", "strength": "strong"}, {"id": "R2", "strength": "moderate"}, {"id": "R9", "strength": "weak"}])
    assert b.jd_requirement_ids == ["R1", "R2"]


def test_jd_marks_required_and_repeated_themes(store):
    jd = jd_for(AWS_JD + "\n- Build AWS CDK pipelines for distributed services.", store)
    assert all(r.required == (r.section == "required_qualifications") for r in jd.requirements)
    assert "AWS CDK" in jd.repeated_themes or "AWS" in jd.repeated_themes
    assert any(r.repeated_themes for r in jd.requirements)


def test_retrieval_with_query_is_deterministic_and_versioned(store):
    jd = jd_for(AWS_JD, store)
    query = sanitize([RequirementQuery(requirement_id=r.id, terms=["Distributed Systems"], adjacent=["Kinesis"])
                      for r in jd.requirements], jd, store)
    expanded = apply_query(jd, query)
    first, second = retrieve_evidence(expanded, store), retrieve_evidence(expanded, store)
    assert first.model_dump() == second.model_dump() and first.version == RETRIEVAL_VERSION
    excluded = {first.projects[0].evidence[0].evidence_id}
    held = retrieve_evidence(expanded, store, excluded=excluded)
    assert excluded.isdisjoint({c.evidence_id for p in held.projects for c in p.evidence})
    assert excluded.isdisjoint({m.evidence_id for found in held.matches.values() for m in found})


# --------------------------------------------------------------------------- style critic


def test_critic_cannot_change_facts_and_only_flagged_unlocked_bullets_are_restyled(store):
    result, plan = analyzed()
    locked_item = next(p for p in plan.selected_projects if p.employment_id == "employment.amazon")
    locked = Bullet(id=locked_item.project_id, employment_id=locked_item.employment_id, project_id=locked_item.project_id,
                    locked=True, text=store.evidence[locked_item.evidence_ids[0]].claim, evidence_ids=locked_item.evidence_ids[:1])
    restyled = []

    def handler(body, payload):
        system = body["messages"][0]["content"]
        if system.startswith("You review the writing style"):
            return json.dumps({"bullets": [{"bullet_id": b["bullet_id"], "style_score": 40, "rewrite": True,
                                            "issues": [{"code": "generic_ai_language", "message": "Too generic."}]}
                                           for b in payload["bullets"]]})
        if system.startswith("You fix the writing style"):
            restyled.extend(i["slot_id"] for i in payload["items"])
            return json.dumps({"bullets": [{"slot_id": i["slot_id"], "text": i["text"].rstrip(".") + " on Kafka for 913% gains.",
                                            "evidence_ids": [e["id"] for e in i["evidence"]]} for i in payload["items"]]})
        return honest_writer(body, payload)

    output = generate(jd_id=result["jd"]["id"], plan=plan, bullets=[locked], llm=fake_llm(handler))
    assert restyled and locked.id not in restyled
    document = ResumeDocument.model_validate(output["document"])
    assert all("Kafka" not in b.text and "913%" not in b.text for b in document.bullets())
    assert next(b for b in document.bullets() if b.id == locked.id).text == locked.text
    rows = {r["bullet_id"]: r for r in output["debug"]}
    assert all(r["style_score"] is not None for r in rows.values())
    assert any(i["code"].startswith("critic:") for b in document.bullets() for i in b.lint)
    stage_names = [s["stage"] for s in output["stages"]]
    assert stage_names[:2] == ["retrieveEvidence", "generateResumeContent"] and "critiqueResumeStyle" in stage_names
    assert {"fitResumeToPageBudget", "validateResumeClaims", "renderResume", "exportResume"} <= set(stage_names)
    assert all({"latency_ms", "deepseek_calls", "tokens", "retries"} <= set(s) for s in output["stages"])


def test_critic_combines_with_lint_without_rewriting():
    findings = {"a": [{"code": "cliche", "severity": "rewrite", "message": "x"}], "b": [], "c": []}
    critiques = {"b": critic.BulletCritique(bullet_id="b", style_score=90, rewrite=True),
                 "c": critic.BulletCritique(bullet_id="c", style_score=50, rewrite=True,
                                            issues=[critic.CriticIssue(code="density", message="Too dense.")])}
    combined = critic.combine(findings, critiques)
    assert combined["a"]["rewrite"] and not combined["b"]["rewrite"] and combined["c"]["rewrite"]
    assert combined["a"]["source"] == "lint" and combined["c"]["style_score"] == 50


# --------------------------------------------------------------------------- feedback and preferences


def test_excluded_or_rejected_evidence_does_not_reappear_and_accept_restores_it(store):
    before = sha(default_path())
    result, plan = analyzed()
    jd_id = result["jd"]["id"]
    target = next(p for p in plan.selected_projects if p.employment_id == "employment.amazon")
    feedback.record(feedback.FeedbackRecord(action="exclude", jd_id=jd_id, project_id=target.project_id,
                                            evidence_ids=target.evidence_ids, bullet_id=target.project_id))
    feedback.record(feedback.FeedbackRecord(action="reject", reason="too_ai_sounding", jd_id=jd_id,
                                            evidence_ids=[f"{MONOLITH}.scale.tps"], bullet_text="Leveraged things."))
    held = set(target.evidence_ids)
    assert feedback.excluded_evidence(jd_id) == held, "a style rejection must not withhold evidence"
    again, replan = analyzed()
    offered = {e["evidence_id"] for c in again["candidates"] for e in c["evidence"]}
    assert held.isdisjoint(offered) and held.isdisjoint({i for p in replan.selected_projects for i in p.evidence_ids})
    output = generate(jd_id=jd_id, plan=plan, llm=fake_llm(honest_writer))
    cited = {i for b in ResumeDocument.model_validate(output["document"]).bullets() for i in b.evidence_ids}
    assert held.isdisjoint(cited)
    feedback.record(feedback.FeedbackRecord(action="accept", jd_id=jd_id, evidence_ids=target.evidence_ids))
    assert feedback.excluded_evidence(jd_id) == set()
    assert sha(default_path()) == before, "feedback never modifies career.json"


def test_preference_examples_teach_style_but_cannot_carry_facts(store):
    result, plan = analyzed()
    feedback.record(feedback.FeedbackRecord(
        action="rewrite", reason="too_ai_sounding", jd_id="f" * 16, project_id=CDK,
        bullet_text="Spearheaded cutting-edge CDK tooling, resulting in transformative velocity.",
        replacement_text="Built shared CDK constructs that saved $250K+/month on CloudWatch."))
    jd = JobDescription.model_validate(result["jd"])
    examples = feedback.preference_examples(jd, [CDK])
    assert examples[0] == {"rejected": "Spearheaded cutting-edge CDK tooling, resulting in transformative velocity.",
                           "reason": "too_ai_sounding", "preferred": "Built shared CDK constructs that saved $250K+/month on CloudWatch."}
    writes = []

    def copier(body, payload):
        if "slots" in payload:
            writes.append(payload)
            if len(writes) == 1:
                out = json.loads(honest_writer(body, payload))
                cdk = next(b for b in out["bullets"] if b["slot_id"] == CDK)
                cdk["text"] = payload["style_preferences"][0]["preferred"]
                return json.dumps(out)
        return honest_writer(body, payload)

    output = generate(jd_id=result["jd"]["id"], plan=plan, llm=fake_llm(copier))
    assert writes[0]["style_preferences"] == examples
    assert any(e["code"] == "unsupported_metric" for e in writes[1]["validation_errors"][CDK])
    assert all("$250K" not in b.text for b in ResumeDocument.model_validate(output["document"]).bullets())
    pairs = feedback.preference_pairs()
    assert pairs and {"prompt", "chosen", "rejected", "reason"} <= set(pairs[0])


# --------------------------------------------------------------------------- versions, approval, apply


def test_a_version_without_a_verified_pdf_cannot_be_downloaded_approved_or_applied(store):
    result, plan = analyzed()
    output = generate(jd_id=result["jd"]["id"], plan=plan, llm=fake_llm(honest_writer))
    version = output["resume_version"]
    assert version and version["pdf_sha256"] is None and version["blocking"]
    with pytest.raises(PermissionError):
        versions.artifact(version["resume_id"], "docx")
    with pytest.raises(PermissionError):
        versions.approve(version["resume_id"])
    with pytest.raises(PermissionError, match="not approved"):
        versions.frozen_resume_for_job({"careerResumeId": version["resume_id"]})
    assert versions.frozen_resume_for_job({"id": "job"}) is None


def _client():
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from app.routers.career_compiler import router
    app = FastAPI()
    app.include_router(router)
    return TestClient(app)


def test_feedback_and_blocked_version_routes(store):
    result, plan = analyzed()
    version = generate(jd_id=result["jd"]["id"], plan=plan, llm=fake_llm(honest_writer))["resume_version"]
    rid = version["resume_id"]
    with _client() as client:
        saved = client.post("/career/feedback", json={"action": "exclude", "jd_id": result["jd"]["id"], "evidence_ids": [f"{CDK}.metric.setup_time"]})
        assert saved.status_code == 200 and saved.json()["id"].startswith("fb_")
        assert client.post("/career/feedback", json={"action": "delete_career_json"}).status_code == 422
        listed = client.get("/career/feedback", params={"jd_id": result["jd"]["id"]}).json()
        assert listed["excluded_evidence"] == [f"{CDK}.metric.setup_time"] and listed["stats"]["counts"]["exclude"] == 1
        detail = client.get(f"/career/resumes/{rid}").json()
        assert detail["blocking"] and detail["outcome_confounders"]
        assert client.get(f"/career/resumes/{rid}/download", params={"format": "pdf"}).status_code == 409
        assert client.post(f"/career/resumes/{rid}/approve", json={}).status_code == 409
        assert client.post(f"/career/resumes/{rid}/apply", json={"applicationUrl": "https://jobs.example.com/1"}).status_code == 409
        assert client.post(f"/career/resumes/{rid}/outcomes", json={"outcome": "hired_as_ceo"}).status_code == 422
        assert client.post(f"/career/resumes/{rid}/outcomes", json={"outcome": "screen"}).json()["outcomes"][0]["outcome"] == "screen"
        assert client.get("/career/resumes/rv_0000000000000000").status_code == 404


def test_a_submitted_autopilot_job_records_applied_once_on_its_resume_version(store):
    from app.db.store import SessionLocal
    from app.services.application_assistant.persistence import save_autopilot_job
    result, plan = analyzed()
    rid = generate(jd_id=result["jd"]["id"], plan=plan, llm=fake_llm(honest_writer))["resume_version"]["resume_id"]
    job = {"id": "apjob_careeros_outcome", "company": "Example Corp", "title": "Senior Software Engineer",
           "applicationUrl": "https://jobs.example.com/outcome", "status": "QUEUED", "careerResumeId": rid}
    session = SessionLocal()
    try:
        save_autopilot_job(session, job)
        assert versions.outcomes(rid) == []
        save_autopilot_job(session, {**job, "status": "SUBMITTED"})
        save_autopilot_job(session, {**job, "status": "SUBMITTED"})
    finally:
        session.rollback()
        session.close()
    assert [(o["outcome"], o["note"]) for o in versions.outcomes(rid)] == [("applied", "autopilot job apjob_careeros_outcome")]


def _word():
    from app.services.career_compiler.word import ConverterUnavailable, get_converter
    try:
        return get_converter()
    except ConverterUnavailable:
        pytest.skip("No Word or LibreOffice on this machine")


def test_pdf_and_docx_belong_to_one_frozen_version_and_apply_uses_it_unchanged(store, monkeypatch):
    import pymupdf
    from app.services.career_compiler.docx_render import WordMeasurer
    _word()
    monkeypatch.setattr(pipeline, "_measurer", WordMeasurer)
    template_before, career_before = sha(golden_path()), sha(default_path())
    result, plan = analyzed()
    output = generate(jd_id=result["jd"]["id"], plan=plan, llm=fake_llm(honest_writer))
    version = output["resume_version"]
    resume_id = version["resume_id"]
    assert output["valid"] and not version["blocking"] and version["pdf_checks"]["passed"]
    docx, pdf = versions.artifact(resume_id, "docx"), versions.artifact(resume_id, "pdf")
    assert hashlib.sha256(docx).hexdigest() == version["docx_sha256"] and hashlib.sha256(pdf).hexdigest() == version["pdf_sha256"]
    assert resume_id == "rv_" + version["docx_sha256"][:16]
    document = ResumeDocument.model_validate(output["document"])
    embedded = read_trace(docx)
    with pymupdf.open(stream=pdf, filetype="pdf") as doc:
        assert doc.page_count == 1
        text = re.sub(r"[^a-z0-9]", "", "".join(p.get_text() for p in doc).casefold())
    for b in document.bullets():
        assert embedded[b.id]["evidence"] == b.evidence_ids
        assert re.sub(r"[^a-z0-9]", "", b.text.casefold()) in text, "the PDF carries exactly the DOCX content"
    assert version["prompt_versions"] and version["retrieval_version"] == RETRIEVAL_VERSION and version["career_json_hash"] == store.digest
    approved = versions.approve(resume_id, ["summary"])
    assert approved.status == "approved" and "summary" in approved.user_locks
    folder = versions.root() / resume_id
    frozen = {name: sha(folder / name) for name in ("resume.docx", "resume.pdf", "resume.json")}
    again = generate(jd_id=result["jd"]["id"], plan=plan, llm=fake_llm(honest_writer))
    assert again["resume_version"]["resume_id"] == resume_id and again["resume_version"]["status"] == "approved"
    assert {name: sha(folder / name) for name in frozen} == frozen, "an approved version is never rewritten"
    path = versions.frozen_resume_for_job({"careerResumeId": resume_id, "id": "apjob_1"})
    assert sha(path) == version["pdf_sha256"]
    versions.record_submission(resume_id, "apjob_1")
    versions.record_submission(resume_id, "apjob_1")
    versions.record_outcome(resume_id, "screen", "phone screen")
    assert [o["outcome"] for o in versions.outcomes(resume_id)] == ["applied", "screen"]
    from app.routers.application_assistant import autopilot
    monkeypatch.setattr(autopilot, "_resolve_job_fields", lambda payload: dict(payload))
    with _client() as client:
        downloaded = client.get(f"/career/resumes/{resume_id}/download", params={"format": "pdf"})
        assert downloaded.headers["x-content-sha256"] == version["pdf_sha256"] == hashlib.sha256(downloaded.content).hexdigest()
        applied = client.post(f"/career/resumes/{resume_id}/apply", json={
            "applicationUrl": "https://jobs.example.com/careeros-test-123", "company": "Example Corp", "title": "Senior Software Engineer"})
        assert applied.status_code == 200, applied.text
        job = applied.json()["job"]
        assert applied.json()["version"]["applications"][-1]["autopilot_job_id"] == job["id"]
        name = versions.recruiter_filename("pdf")
        assert name.endswith("_Resume.pdf") and resume_id not in name
        assert downloaded.headers["content-disposition"] == f'attachment; filename="{name}"'
        word = client.get(f"/career/resumes/{resume_id}/download", params={"format": "docx"})
        assert word.headers["content-disposition"].endswith('_Resume.docx"')
        import io, zipfile
        clean, original = zipfile.ZipFile(io.BytesIO(word.content)), zipfile.ZipFile(io.BytesIO(docx))
        assert "customXml/careeros-trace.xml" not in clean.namelist() and b"rIdCareerOSTrace" not in clean.read("word/_rels/document.xml.rels")
        assert all(clean.read(n) == original.read(n) for n in clean.namelist() if n.startswith("word/") and "_rels" not in n)
        assert client.get(f"/career/resumes/{resume_id}/download", params={"format": "docx"}).content == word.content
        for _ in range(2):
            manual = client.post(f"/career/resumes/{resume_id}/applied", json={
                "applicationUrl": "https://jobs.example.com/manual-1", "jobId": "dj_1", "answers": {"Why us?": "Platform scale."}})
            assert manual.status_code == 200, manual.text
        manual_apps = [a for a in manual.json()["applications"] if a.get("channel") == "manual"]
        assert len(manual_apps) == 1 and manual_apps[0]["pdf_sha256"] == version["pdf_sha256"]
        assert (folder / "jd.json").is_file(), "the JD the application was made against is snapshotted with it"
        prep = client.get(f"/career/resumes/{resume_id}/interview-prep").json()
        assert prep["resumeId"] == resume_id and prep["pdfSha256"] == version["pdf_sha256"] and prep["jdText"]
        sections = {s["id"]: s for s in prep["sections"]}
        assert len(sections["claims"]["items"]) == len(document.bullets()) + (1 if document.summary else 0)
        assert "requirements" in sections and sections["answers"]["items"][0]["detail"] == "Platform scale."
        assert [v for v in client.get("/career/resumes").json()["versions"] if v["resume_id"] == resume_id][0]["label"].endswith("-v1")
    queued = {**job, "careerResumeId": resume_id}
    uploaded = versions.frozen_resume_for_job(queued)
    assert sha(uploaded) == version["pdf_sha256"], "the agent submits the approved PDF, unchanged"
    assert uploaded.name == versions.recruiter_filename("pdf")
    (folder / "resume.pdf").write_bytes(pdf + b"%tampered")
    with pytest.raises(RuntimeError, match="does not match its recorded hash"):
        versions.frozen_resume_for_job({"careerResumeId": resume_id})
    assert sha(golden_path()) == template_before and sha(default_path()) == career_before
