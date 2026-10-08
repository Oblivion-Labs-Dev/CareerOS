"""Spare page space goes to the strongest unused supported evidence, after direct JD coverage."""
import pytest

from app.services.career_compiler import pipeline
from app.services.career_compiler.career_signal import career_signal
from app.services.career_compiler.docx_template import load_spec
from app.services.career_compiler.models import (
    Candidate, JobDescription, ProjectCandidate, Ranking, Requirement, Retrieval,
)
from app.services.career_compiler.store import CareerStore, Evidence, Project

MS, AMZ = "employment.microsoft", "employment.amazon"
EMPLOYMENT = {MS: {"company": "Microsoft", "role": "Engineer", "start": "2025-09", "end": "2026-08"},
              AMZ: {"company": "Amazon", "role": "Engineer", "start": "2019-08", "end": "2025-08"},
              "employment.persistent": {"company": "Persistent", "role": "Intern", "start": "2016-06", "end": "2017-01"}}

#: project id -> (employment, technologies, [(type, status, claim, tags)])
PROJECTS = {
    "jd_match": (MS, ("Go",), [("metric", "supported", "Built the billing ledger in Go serving 2 regions.", ("billing",))]),
    "modern": (MS, ("LLM", "Azure"), [("metric", "supported", "Shipped agentic LLM risk triage that cut review time 40% across 13K organizations.", ("agentic-ai", "scale"))]),
    "rag": (AMZ, ("Python",), [("metric", "supported", "Built RAG retrieval for product answers, improving answer quality by 12%.", ("rag",))]),
    "queue_a": (AMZ, ("SQS", "Java"), [("metric", "supported", "Rebuilt the order queue on microservices, handling 2 million events a day with 30% lower latency.", ("distributed-systems", "scale"))]),
    "queue_b": (AMZ, ("SQS", "Java"), [("metric", "supported", "Moved the returns queue to microservices, handling 3 million events a day with 25% lower latency.", ("distributed-systems", "scale"))]),
    "cost": (AMZ, ("EC2",), [("decision", "supported", "Chose reserved capacity over on-demand hosts for the seller console to cut cost.", ("cost",))]),
    "plain": (AMZ, (), [("project", "supported", "Maintained an internal admin page.", ())]),
    "sparse": (AMZ, (), [("project_reference", "sparse_evidence", "Worked on a cancellation integration.", ())]),
    "old": ("employment.persistent", (), [("metric", "supported", "Fixed 12 report bugs.", ())]),
}


def make_store() -> CareerStore:
    evidence, projects = {}, {}
    for pid, (emp, tech, records) in PROJECTS.items():
        ids = []
        for n, (kind, status, claim, tags) in enumerate(records):
            eid = f"{pid}.e{n}"
            ids.append(eid)
            evidence[eid] = Evidence(id=eid, type=kind, claim=claim, status=status, tags=tuple(tags), project_id=pid,
                                     employment_id=emp, company=EMPLOYMENT[emp]["company"])
        projects[pid] = Project(id=pid, name=pid.replace("_", " ").title(), employment_id=emp, company=EMPLOYMENT[emp]["company"],
                                summary="", technologies=tech, details=(), ownership=(), domains=(), evidence_ids=tuple(ids))
    return CareerStore(data={"person": {"name": "Test Person"}}, digest="test", path="", evidence=evidence,
                       projects=projects, employment=EMPLOYMENT)


def retrieval_for(store: CareerStore) -> Retrieval:
    out = []
    for pid, project in store.projects.items():
        records = store.project_evidence(pid)
        out.append(ProjectCandidate(
            project_id=pid, name=project.name, company=project.company, employment_id=project.employment_id,
            score=3.0 if pid == "jd_match" else .01, coverage={"R1": "strong"} if pid == "jd_match" else {},
            existence_only=all(e.status == "sparse_evidence" for e in records),
            evidence=[Candidate(evidence_id=e.id, type=e.type, status=e.status, claim=e.claim, score=1) for e in records]))
    return Retrieval(projects=out, matches={"R1": []}, store_digest="test")


JD = JobDescription(id="0" * 16, title="Billing Engineer", text="Build billing systems in Go.", requirements=[
    Requirement(id="R1", section="required_qualifications", original_text="Build billing systems in Go.",
                normalized_requirement="billing systems in Go", skills=["Go"])])


@pytest.fixture()
def store():
    return make_store()


@pytest.fixture(autouse=True)
def no_section_minimums(monkeypatch):
    """Isolate the planner's phases: no section is forced to a minimum, so every pick is JD coverage or career signal."""
    monkeypatch.setattr(pipeline, "LIMITS", {MS: (0, 7), AMZ: (0, 10), pipeline.PERSONAL_EMPLOYMENT_ID: (0, 2)})


def plan(store, capacity: int | None = None):
    spec = load_spec()
    if capacity is not None:
        spec = {**spec, "rendered": {**spec["rendered"], "capacity_lines": capacity}}
    return pipeline.generate_resume_plan(JD, Ranking(projects=[]), retrieval_for(store), store, spec)


def fixed_lines(spec) -> int:
    cost = pipeline._template_lines(spec)
    return 1 + 3 + 1 + cost["education"] + 1 + sum(cost["skills"].values()) + 1 + cost["summary"]


def test_modern_high_impact_large_scale_evidence_ranks_well(store):
    scores = {pid: career_signal(store, pid).score for pid in store.projects}
    assert scores["modern"] == max(scores.values())
    assert scores["modern"] > scores["rag"] > scores["plain"]
    assert scores["queue_a"] > scores["cost"] > scores["plain"]
    assert scores["rag"] > scores["old"], "older, non-modern work ranks below recent modern work"
    assert career_signal(store, "sparse").score == 0 and not career_signal(store, "sparse").supported


def test_direct_jd_evidence_wins_first_and_remaining_space_gets_strong_career_evidence(store):
    result = plan(store)
    picks = result.selected_projects
    assert picks[0].project_id == "jd_match" and picks[0].selection == "jd_match" and picks[0].requirement_ids == ["R1"]
    assert all(p.selection in ("career_signal", "diversity") for p in picks[1:])
    assert all(p.score < picks[0].score for p in picks[1:]), "filler must rank below JD content when fitting removes"
    assert picks[1].project_id == "modern" and picks[1].selection == "career_signal" and "agentic ai" in picks[1].reason


def test_variety_beats_repetitive_evidence(store):
    order = [p.project_id for p in plan(store).selected_projects]
    first, second = sorted((order.index("queue_a"), order.index("queue_b")))
    assert career_signal(store, "queue_a").score > career_signal(store, "cost").score
    assert first < order.index("cost") < second, "a second queue migration adds nothing new, so a new capability goes first"
    assert plan(store).selected_projects[order.index("cost")].selection == "diversity"


def test_unsupported_evidence_never_fills_space(store):
    chosen = {p.project_id for p in plan(store).selected_projects}
    assert "sparse" not in chosen
    assert all(store.evidence[i].usable for p in plan(store).selected_projects for i in p.evidence_ids)


def test_no_unnecessary_whitespace_while_supported_evidence_remains(store):
    spec = load_spec()
    capacity = fixed_lines(spec) + 2 + 3 * pipeline.BULLET_LINES
    result = plan(store, capacity)
    left = capacity - result.section_budget.planned_lines
    chosen = {p.project_id for p in result.selected_projects}
    assert result.selected_projects[0].project_id == "jd_match"
    assert left < pipeline.BULLET_LINES, "space for another bullet stayed empty"
    assert "plain" not in chosen and "modern" in chosen, "the strongest evidence takes the limited space"


def test_without_spare_space_only_jd_content_is_planned(store):
    spec = load_spec()
    result = plan(store, fixed_lines(spec) + pipeline.BULLET_LINES)
    assert [p.project_id for p in result.selected_projects] == ["jd_match"]
