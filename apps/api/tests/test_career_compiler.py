import hashlib
import json

import httpx
import pytest

from app.services.career_compiler import pipeline, style, trace
from app.services.career_compiler.deepseek import DeepSeekClient, DeepSeekError
from app.services.career_compiler.docx_render import EstimateMeasurer, formatting_drift, read_trace, render_docx
from app.services.career_compiler.docx_template import load_golden, load_spec
from app.services.career_compiler.export import export, export_pdf
from app.services.career_compiler.jobs import ingest_job_description, structure_job_description
from app.services.career_compiler.models import Bullet, ResumeDocument, ResumePlan
from app.services.career_compiler.pipeline import CompilerUnavailable, analyze, generate
from app.services.career_compiler.retrieval import retrieve_evidence
from app.services.career_compiler.store import default_path, load_store
from app.services.career_compiler.validator import validate_bullet

AWS_JD = """Senior Software Engineer, Distributed Systems
Responsibilities:
- Build high-throughput distributed systems and microservices on AWS.
- Own CI/CD and infrastructure as code with AWS CDK for many services.
Required qualifications:
- Experience with TypeScript or Java, DynamoDB, SQS and ECS.
Preferred qualifications:
- Observability with CloudWatch; experience with developer platforms."""
AI_SECURITY_JD = """Senior AI Engineer, AI Security
Responsibilities:
- Build agentic AI systems that evaluate risk for AI agents at enterprise scale.
Required qualifications:
- C#, .NET and Azure.
- Microsoft Graph, Entra, data loss prevention (DLP) and Microsoft Purview.
Preferred qualifications:
- Conditional Access and AI governance."""
CDK = "amazon.fxm_cdk_commons"


@pytest.fixture(autouse=True)
def jd_cache(tmp_path, monkeypatch):
    monkeypatch.setenv("CAREEROS_JD_CACHE", str(tmp_path / "jd"))
    monkeypatch.setenv("CAREEROS_COMPILER_DATA", str(tmp_path / "compiler"))


@pytest.fixture(autouse=True)
def estimated_layout(monkeypatch):
    """Unit tests measure with the calibrated metric estimate; test_resume_template.py exercises Word itself."""
    monkeypatch.setattr(pipeline, "_measurer", EstimateMeasurer)


@pytest.fixture()
def store():
    return load_store()


def offline() -> DeepSeekClient:
    return DeepSeekClient(api_key="")


def fake_llm(handler, calls: list | None = None) -> DeepSeekClient:
    def respond(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        payload = json.loads(body["messages"][-1]["content"]) if body["messages"][-1]["content"].startswith("{") else {}
        if calls is not None:
            calls.append((body["messages"][0]["content"][:40], payload))
        content = handler(body, payload)
        return httpx.Response(200, json={"choices": [{"message": {"content": content}}], "usage": {"total_tokens": 10}})
    return DeepSeekClient(api_key="test-key", transport=httpx.MockTransport(respond))


def honest_writer(_body, payload) -> str:
    """Copies the strongest claim, which keeps every number and term traceable."""
    if "items" in payload:
        return json.dumps({"bullets": [{"slot_id": i["slot_id"], "text": i["text"], "evidence_ids": [e["id"] for e in i["evidence"]]}
                                       for i in payload["items"]]})
    bullets = [{"slot_id": s["slot_id"], "text": s["evidence"][0]["claim"], "evidence_ids": [s["evidence"][0]["id"]]}
               for s in payload.get("slots") or []]
    summary = None
    if payload.get("summary_slot"):
        summary = {"text": "Software engineer with 8+ years of experience building backend systems.",
                   "evidence_ids": ["person.positioning.experience"]}
    return json.dumps({"summary": summary, "bullets": bullets})


def bullet(text: str, ids: list[str], employment_id: str = "employment.amazon", project_id: str = CDK) -> Bullet:
    return Bullet(id=project_id, employment_id=employment_id, project_id=project_id, text=text, evidence_ids=ids)


def jd_for(text: str, store, llm=None):
    return structure_job_description(ingest_job_description(text), store, llm or offline())[0]


def analyzed(text: str = AWS_JD):
    result = analyze(text=text, llm=offline())
    return result, ResumePlan.model_validate(result["plan"])


# 1
def test_career_json_loads_stably_and_is_never_written(store):
    before = hashlib.sha256(default_path().read_bytes()).hexdigest()
    assert load_store() is store and store.digest == before
    copy = store.snapshot()
    copy["employment"].clear()
    assert store.data["employment"], "snapshots must not alias the canonical data"
    result, plan = analyzed()
    generate(jd_id=result["jd"]["id"], plan=plan, llm=fake_llm(honest_writer))
    assert hashlib.sha256(default_path().read_bytes()).hexdigest() == before


# 2
def test_aws_distributed_jd_retrieves_amazon_evidence(store):
    projects = retrieve_evidence(jd_for(AWS_JD, store), store).projects
    amazon = [p.project_id for p in projects if p.employment_id == "employment.amazon"]
    assert CDK in amazon[:3]
    cdk = next(p for p in projects if p.project_id == CDK)
    iac = next(r.id for r in jd_for(AWS_JD, store).requirements if "AWS CDK" in r.skills)
    assert cdk.coverage[iac] in ("strong", "moderate")
    assert cdk.coverage[iac] == max(cdk.coverage.values(), key=["weak", "moderate", "strong"].index)


# 3
def test_ai_security_jd_retrieves_microsoft_evidence(store):
    projects = retrieve_evidence(jd_for(AI_SECURITY_JD, store), store).projects
    assert projects[0].employment_id == "employment.microsoft"
    assert "microsoft.adaptive_protection_agents" in [p.project_id for p in projects if p.employment_id == "employment.microsoft"][:3]


# 4
def test_needs_reconciliation_metric_is_never_selected(store):
    disputed = "amazon.multi_service_deployment.metric.pipeline_15_to_2"
    jd = jd_for(AWS_JD + "\n- Consolidate deployment pipelines across services.", store)
    retrieval = retrieve_evidence(jd, store)
    usable = {c.evidence_id for p in retrieval.projects for c in p.evidence}
    blocked = {c.evidence_id for p in retrieval.projects for c in p.blocked}
    matched = {m.evidence_id for found in retrieval.matches.values() for m in found}
    assert disputed not in usable | matched and disputed in blocked
    result, _ = analyzed()
    assert all(disputed not in p["evidence_ids"] for p in result["plan"]["selected_projects"])
    issues = validate_bullet(bullet("Reduced deployment pipelines from 15 to 2.", [disputed],
                                    project_id="amazon.multi_service_deployment"), store)
    assert [i.code for i in issues] == ["unresolved_conflict"]


# 5
def test_sparse_evidence_cannot_carry_details(store):
    sparse, project = "amazon.editable_templates.existence", "amazon.editable_templates"
    assert validate_bullet(bullet("Worked on editable notification templates.", [sparse], project_id=project), store) == []
    bad = validate_bullet(bullet("Built editable templates on DynamoDB with Microservices, serving 40 teams.", [sparse],
                                 project_id=project), store)
    assert {"unsupported_metric", "unsupported_technology", "sparse_detail"} <= {i.code for i in bad}


# 6
def test_metric_not_in_evidence_fails(store):
    issues = validate_bullet(bullet("Cut service setup from 2 weeks to 10 minutes with AWS CDK.", [f"{CDK}.metric.setup_time"]), store)
    assert [(i.code, "10" in i.message) for i in issues] == [("unsupported_metric", True)]


# 7
def test_unsupported_technology_fails(store):
    issues = validate_bullet(bullet("Cut service setup from 2 weeks to under 1 hour using Kubernetes.", [f"{CDK}.metric.setup_time"]), store)
    assert [i.code for i in issues] == ["unsupported_technology"]


# 8
def test_wrong_company_attribution_fails(store):
    moved = validate_bullet(bullet("Cut service setup from 2 weeks to under 1 hour.", [f"{CDK}.metric.setup_time"],
                                   employment_id="employment.microsoft"), store)
    named = validate_bullet(bullet("Brought Microsoft deployment practices to cut setup from 2 weeks to under 1 hour.",
                                   [f"{CDK}.metric.setup_time"]), store)
    assert "wrong_company" in {i.code for i in moved} and "wrong_company" in {i.code for i in named}


# 9
def test_valid_bullet_with_multiple_evidence_ids_passes(store):
    text = ("Built shared AWS CDK constructs that cut service setup from 2 weeks to under 1 hour, saving an estimated "
            "40–50 engineering weeks across 3 teams.")
    assert validate_bullet(bullet(text, [f"{CDK}.metric.setup_time", f"{CDK}.metric.weeks_saved"]), store) == []


# 10
def test_malformed_deepseek_json_is_handled(store):
    calls = []
    llm = fake_llm(lambda _b, _p: "Sure! Here is the resume: {not json", calls)
    with pytest.raises(DeepSeekError) as raised:
        llm.complete_json(task="t", system="s", user={"q": 1}, schema=pipeline._WriteResponse)
    assert raised.value.code == "malformed" and len(calls) == 2
    jd, warnings, _ = structure_job_description(ingest_job_description(AWS_JD), store, llm)
    assert jd.source == "deterministic" and jd.requirements and warnings
    _, plan = analyzed()
    with pytest.raises(CompilerUnavailable):
        generate(jd=jd, plan=plan, llm=fake_llm(lambda _b, _p: json.dumps({"bullets": "nope"})))


# 11
def test_timeout_gives_useful_error_and_changes_nothing(store):
    def timeout(_request):
        raise httpx.ReadTimeout("slow")
    llm = DeepSeekClient(api_key="test-key", transport=httpx.MockTransport(timeout), timeout=1)
    before = json.dumps(store.data, sort_keys=True)
    result = analyze(text=AWS_JD, llm=llm)
    assert any("did not answer" in w for w in result["warnings"])
    plan = ResumePlan.model_validate(result["plan"])
    with pytest.raises(CompilerUnavailable, match="did not answer"):
        generate(jd_id=result["jd"]["id"], plan=plan, llm=llm)
    error = DeepSeekClient(api_key="test-key", transport=httpx.MockTransport(lambda _r: httpx.Response(500, json={})))
    with pytest.raises(CompilerUnavailable, match="HTTP 500"):
        generate(jd_id=result["jd"]["id"], plan=plan, llm=error)
    assert json.dumps(load_store().data, sort_keys=True) == before


# 12
def test_regeneration_preserves_locked_bullets_and_repairs_only_invalid(store):
    result, plan = analyzed()
    assert CDK in [p.project_id for p in plan.selected_projects]
    locked_text = "Built shared AWS CDK constructs that cut service setup from 2 weeks to under 1 hour."
    locked = bullet(locked_text, [f"{CDK}.metric.setup_time"]).model_copy(update={"locked": True})
    writes = []

    def writer(body, payload):
        if "slots" in payload:
            writes.append(payload)
            if len(writes) == 1:
                out = json.loads(honest_writer(body, payload))
                out["bullets"][0]["text"] += " Saved 999 hours."
                return json.dumps(out)
        return honest_writer(body, payload)

    output = generate(jd_id=result["jd"]["id"], plan=plan, bullets=[locked], llm=fake_llm(writer))
    sent = [s["slot_id"] for s in writes[0]["slots"]]
    assert CDK not in sent and locked_text in writes[0]["already_on_resume_do_not_repeat"]
    repaired = [s["slot_id"] for s in writes[1]["slots"]]
    assert sorted(sent)[0] in repaired and set(repaired) == set(writes[1]["validation_errors"]) - {"summary"}
    assert len(repaired) < len(sent), "valid bullets must not be rewritten during repair"
    document = ResumeDocument.model_validate(output["document"])
    kept = {b.id: b for b in document.bullets()}
    assert kept[CDK].text == locked_text and kept[CDK].locked
    assert output["valid"] and output["layout"]["fits"] and output["layout"]["template_drift"] == []
    rewrite_one = generate(jd_id=result["jd"]["id"], plan=plan, bullets=document.bullets() + [document.summary],
                           regenerate=[sent[0]], llm=fake_llm(honest_writer))
    again = {b.id: b.text for b in ResumeDocument.model_validate(rewrite_one["document"]).bullets()}
    assert all(again[k] == b.text for k, b in kept.items() if k != sent[0] and k in again)
    tampered = json.loads(json.dumps(output["document"]))
    tampered["sections"][1]["bullets"][0]["text"] += " Reduced cost by 87%."
    with pytest.raises(ValueError, match="87"):
        export_pdf(tampered)


# 13
def test_retrieval_order_is_deterministic(store):
    jd = jd_for(AWS_JD, store)
    first, second = retrieve_evidence(jd, store), retrieve_evidence(jd, store)
    assert [(p.project_id, [c.evidence_id for c in p.evidence]) for p in first.projects] == \
           [(p.project_id, [c.evidence_id for c in p.evidence]) for p in second.projects]
    assert first.model_dump() == second.model_dump()


def test_jd_structuring_keeps_verbatim_wording_and_stable_ids(store):
    calls = []

    def structurer(_body, _payload):
        return json.dumps({"title": "Senior SDE", "company": "", "requirements": [
            {"section": "preferred_qualifications", "original_text": "Observability with CloudWatch; experience with developer platforms.",
             "normalized_requirement": "CloudWatch observability", "skills": ["CloudWatch", "Rust"], "importance": "high"},
            {"section": "required_qualifications", "original_text": "10+ years of Rust and Haskell.",
             "normalized_requirement": "Rust", "skills": ["Rust"], "importance": "high"},
            {"section": "responsibilities", "original_text": "Build high-throughput   distributed systems and microservices on AWS.",
             "normalized_requirement": "Build distributed systems", "skills": ["AWS"], "importance": "medium"},
            {"section": "required_qualifications", "original_text": "Experience with TypeScript or Java, DynamoDB, SQS and ECS.",
             "normalized_requirement": "TypeScript or Java on AWS data services", "skills": ["TypeScript", "Java"], "importance": "low"},
        ]})
    llm = fake_llm(structurer, calls)
    jd, warnings, _ = structure_job_description(ingest_job_description(AWS_JD), store, llm)
    assert [r.id for r in jd.requirements] == ["R1", "R2", "R3"]
    assert [r.section for r in jd.requirements] == ["responsibilities", "required_qualifications", "preferred_qualifications"]
    assert all(r.original_text in AWS_JD for r in jd.requirements)
    assert jd.requirements[0].original_text == "Build high-throughput distributed systems and microservices on AWS."
    assert "10+ years of Rust and Haskell." in jd.dropped and any("Dropped 1" in w for w in warnings)
    assert all("Rust" not in r.skills for r in jd.requirements)
    assert jd.requirements[1].importance == "high" and jd.requirements[2].importance == "medium"
    again, _, _ = structure_job_description(ingest_job_description(AWS_JD), store, llm)
    assert again == jd and len(calls) == 1


def test_scores_come_from_requirement_coverage_not_the_llm(store):
    jd = jd_for(AWS_JD, store)
    weights = {"high": 3, "medium": 2, "low": 1}
    values = {r.id: "strong" for r in jd.requirements[:1]}
    expected = round(100 * weights[jd.requirements[0].importance] / sum(weights[r.importance] for r in jd.requirements))
    assert trace.score(values, jd) == expected
    assert trace.score({}, jd) == 0 and trace.score({r.id: "strong" for r in jd.requirements}, jd) == 100
    result, _ = analyzed()
    assert result["trace"]["scores"]["evidence"] == trace.report(jd, retrieve_evidence(jd, store), store)["scores"]["evidence"]


def test_spare_page_space_is_filled_with_supported_career_evidence_after_jd_matches(store):
    result, plan = analyzed()
    kinds = [p.selection for p in plan.selected_projects]
    filler = [p for p in plan.selected_projects if p.selection != "jd_match"]
    assert filler and kinds.index(filler[0].selection) == len(kinds) - len(filler), "JD matches are planned first"
    assert all(store.evidence[i].usable for p in filler for i in p.evidence_ids)
    assert len({p.project_id for p in plan.selected_projects}) == len(plan.selected_projects)
    output = generate(jd_id=result["jd"]["id"], plan=plan, llm=fake_llm(honest_writer))
    budget = output["layout"]["section_budget"]
    assert output["valid"] and output["layout"]["fits"]
    assert budget["capacity_lines"] - budget["planned_lines"] <= 4, "the plan stops only when the page is full"
    written = {b.project_id for b in ResumeDocument.model_validate(output["document"]).bullets()}
    assert {p.project_id for p in filler} <= written


def test_trace_chain_links_requirements_evidence_projects_and_bullets(store):
    result, plan = analyzed()
    output = generate(jd_id=result["jd"]["id"], plan=plan, llm=fake_llm(honest_writer))
    document = ResumeDocument.model_validate(output["document"])
    bullets = {b.id: b for b in document.bullets()}
    rows = {r["id"]: r for r in output["trace"]["requirements"]}
    assert any(r["status"] == "covered" for r in rows.values())
    for row in rows.values():
        for cover in row["bullets"]:
            if cover["bullet_id"] in ("skills", "education"):
                assert cover["strength"] != "strong"
                continue
            target = bullets.get(cover["bullet_id"]) or document.summary
            assert row["id"] in [x["id"] for x in target.requirements]
        if row["status"] == "missing":
            assert not row["evidence"]
        for match in row["evidence"]:
            assert store.evidence[match["evidence_id"]].status in ("supported", "supported_variant", "sparse_evidence")
    for b in bullets.values():
        assert set(x["id"] for x in b.requirements) <= set(rows)
        assert b.project_id in [p.project_id for p in plan.selected_projects]


def test_format_is_locked_and_overflow_is_fixed_by_content_not_font(store):
    result, plan = analyzed()
    compressions = []

    def verbose(body, payload):
        if "items" in payload:
            compressions.append(payload)
            return json.dumps({"bullets": [{"slot_id": i["slot_id"], "text": i["text"].split(" Additionally")[0],
                                            "evidence_ids": [e["id"] for e in i["evidence"]]} for i in payload["items"]]})
        out = json.loads(honest_writer(body, payload))
        for b in out["bullets"]:
            b["text"] += " Additionally" + " the same work was described again at much greater length" * 4 + "."
        return json.dumps(out)

    output = generate(jd_id=result["jd"]["id"], plan=plan, llm=fake_llm(verbose))
    assert compressions and any("Compressed" in line for line in output["fit_log"])
    assert output["layout"]["fits"] and output["valid"]
    assert all(row["lines"] is None or row["lines"] <= row["line_budget"] for row in output["debug"])
    docx = render_docx(ResumeDocument.model_validate(output["document"]), load_spec(), load_golden()).docx
    assert formatting_drift(docx, load_golden()) == []


def test_planner_sizes_sections_per_jd_within_one_page(store):
    spec = load_spec()
    budgets = {}
    for name, text in (("aws", AWS_JD), ("ai", AI_SECURITY_JD)):
        _, plan = analyzed(text)
        budget = plan.section_budget
        matched = [p for p in plan.selected_projects if p.selection == "jd_match"]
        budgets[name] = tuple(sum(p.employment_id == e for p in matched) for e in ("employment.microsoft", "employment.amazon"))
        assert budget.planned_lines <= budget.capacity_lines == spec["rendered"]["capacity_lines"]
        assert 2 <= budget.microsoft <= 7 and 3 <= budget.amazon <= 10 and budget.projects <= 2
        assert all(p.lines in (1, 2, 3) for p in plan.selected_projects)
    assert budgets["ai"][0] > budgets["aws"][0] and budgets["aws"][1] > budgets["ai"][1], \
        "JD-matched content should follow the JD, not a fixed split"


def test_overflow_removes_low_value_content_before_compressing_and_never_locked(store):
    result, plan = analyzed()
    item = next(p for p in plan.selected_projects if p.employment_id == "employment.amazon")
    locked = Bullet(id=item.project_id, employment_id=item.employment_id, project_id=item.project_id, locked=True,
                    text=store.evidence[item.evidence_ids[0]].claim, evidence_ids=item.evidence_ids[:1])
    tight = {**load_spec(), "rendered": {**load_spec()["rendered"], "capacity_lines": 20}}
    calls = []
    output = generate(jd_id=result["jd"]["id"], plan=plan, bullets=[locked], llm=fake_llm(honest_writer, calls),
                      measurer=EstimateMeasurer(tight))
    document = ResumeDocument.model_validate(output["document"])
    assert output["layout"]["fits"] and output["layout"]["lines_used"] <= 20
    assert document.bullets()[[b.id for b in document.bullets()].index(item.project_id)].text == locked.text
    removed = [line for line in output["fit_log"] if line.startswith(("Removed", "Trimmed"))]
    assert removed and not any(item.project_id in line for line in removed)
    losses = [float(line.rsplit("coverage loss ", 1)[1].rstrip(").")) for line in removed]
    compressed = any("items" in payload for _, payload in calls)
    assert all(loss <= pipeline.LOW_VALUE for loss in losses) or compressed, \
        "content with real JD coverage may only be removed after compression was tried"
    counts = {s.employment_id: len(s.bullets) for s in document.sections}
    assert counts["employment.microsoft"] >= 2 and counts["employment.amazon"] >= 3


def test_skills_and_education_sections_answer_qualifications_but_never_strongly(store):
    jd = jd_for("Software Engineer\nRequired qualifications:\n- Bachelor's degree in Computer Science and 5+ years coding in C# or Java.", store)
    rows = trace.report(jd, retrieve_evidence(jd, store), store)["requirements"]
    support = trace.section_support(jd.requirements[0], {"Languages": ["Java", "C#"]}, [{"degree": "Bachelor's in Computer Science"}])
    assert support == {"skills": "moderate", "education": "moderate"}
    assert rows[0]["best_available"] in ("strong", "moderate") and rows[0]["status"] != "missing"


def test_preview_and_export_come_from_the_same_resume_json(store):
    result, plan = analyzed()
    output = generate(jd_id=result["jd"]["id"], plan=plan, llm=fake_llm(honest_writer))
    document = ResumeDocument.model_validate(output["document"])
    spec, golden = load_spec(), load_golden()
    exported = export(output["document"], "docx", measurer=EstimateMeasurer(spec))
    assert exported == render_docx(document, spec, golden).docx == export(output["document"], "docx", measurer=EstimateMeasurer(spec))
    embedded = read_trace(exported)
    for b in document.bullets():
        assert embedded[b.id]["evidence"] == b.evidence_ids
        assert embedded[b.id]["requirements"] == [r["id"] for r in b.requirements]


def test_style_lint_flags_generic_phrasing_and_never_changes_facts(store):
    bullets = [Bullet(id=f"b{i}", employment_id="employment.amazon", project_id=CDK, text=t, evidence_ids=["x"]) for i, t in enumerate([
        "Leveraged AWS CDK to optimize setup, resulting in faster delivery.",
        "Built a deployment workflow for 3 teams.",
        "Built shared CDK constructs.",
        "Built a cutting-edge pipeline, showcasing innovation."])]
    findings = style.lint(bullets)
    assert {f["code"] for f in findings["b0"]} >= {"cliche", "formula", "trailing_result"}
    assert "repeated_opening" in {f["code"] for f in findings["b3"]} and style.needs_rewrite(findings["b3"])
    original = Bullet(id="b", employment_id="employment.amazon", project_id=CDK, evidence_ids=[f"{CDK}.metric.setup_time"],
                      text="Leveraged AWS CDK to cut service setup from 2 weeks to under 1 hour.")
    reworded = original.model_copy(update={"text": "Cut service setup from 2 weeks to under 1 hour with shared AWS CDK constructs."})
    new_number = original.model_copy(update={"text": "Cut service setup from 3 weeks to under 1 hour with AWS CDK."})
    new_tech = original.model_copy(update={"text": "Cut service setup from 2 weeks to under 1 hour with AWS CDK on Kubernetes."})
    assert style.same_facts(original, reworded, store.technologies)
    assert not style.same_facts(original, new_number, store.technologies)
    assert not style.same_facts(original, new_tech, store.technologies)


def test_style_exemplar_facts_cannot_leak_into_bullets(store):
    exemplar = next(e["text"] for e in load_spec()["style_exemplars"] if "$250K" in e["text"])
    assert "$250K" in exemplar
    leaked = validate_bullet(bullet("Cut service setup from 2 weeks to under 1 hour and CloudWatch spend by $250K+/month.",
                                    [f"{CDK}.metric.setup_time"]), store)
    assert "unsupported_metric" in {i.code for i in leaked}
