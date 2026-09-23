"""Deterministic role-shape scoring for the Autopilot queue (#50).

The benchmark numbers themselves come from `scripts/matchlab/run.py` against a
real database; these tests pin the properties the queue relies on: one
implementation, deterministic scores, the benchmark's safety orderings, and a
bounded, memoised scorer that only orders the queue.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

from app.services.application_assistant import role_shape_match as rs

API_ROOT = Path(__file__).resolve().parents[1]

# A candidate shaped like the benchmark's: backend and distributed systems in
# professional work, Kubernetes only in a side project.
CORPUS = [
    {"id": "s1", "evidence": "professional", "company": "Acme", "title": "Distributed backend services",
     "headline": "Built and operated high-throughput distributed backend microservices",
     "technologies": ["Java", "Kafka", "gRPC", "AWS"],
     "concepts": ["distributed systems", "on-call", "incident response", "API design", "event-driven"]},
    {"id": "s2", "evidence": "professional", "company": "Acme", "title": "Service reliability",
     "headline": "Owned production reliability, on-call rotation and postmortems",
     "technologies": ["Datadog", "PostgreSQL"],
     "concepts": ["observability", "data modelling", "backend systems", "cloud infrastructure"]},
    {"id": "s3", "evidence": "personal-project", "company": "", "title": "Kubernetes lab",
     "headline": "Ran a Kubernetes cluster with Terraform for a side project",
     "technologies": ["Kubernetes", "Terraform"], "concepts": ["infrastructure as code"]},
]
PROFILE = {"headline": "Senior Backend Engineer"}

BACKEND_JD = """Responsibilities
- Design and operate distributed backend services at high throughput
- Own service reliability, on-call rotation and incident response
Requirements
- 7+ years building backend systems in production
- Deep experience with distributed systems and cloud infrastructure
- Strong grounding in API design and data modelling
"""
FRONTEND_JD = """Responsibilities
- Build responsive user interfaces and design systems in React and TypeScript
Requirements
- Strong React and TypeScript
- Familiarity with CI/CD and automated testing
"""
K8S_JD = """Requirements
- Years of production Kubernetes ownership, running clusters at scale
- Terraform and infrastructure as code
- Platform engineering for internal developer teams
"""
SHORT_JD = "We are hiring an engineer.\nRequirements\n- Programming experience\n"

JOBS = [
    {"id": "backend", "title": "Senior Backend Engineer", "company": "X", "description": BACKEND_JD},
    {"id": "frontend", "title": "Software Engineer, Frontend", "company": "X", "description": FRONTEND_JD},
    {"id": "k8s", "title": "Senior Platform Engineer", "company": "X", "description": K8S_JD},
    {"id": "short", "title": "Software Engineer", "company": "X", "description": SHORT_JD},
]


@pytest.fixture
def ctx():
    return rs.build_context(PROFILE, {}, CORPUS, [j["description"] for j in JOBS])


def test_the_benchmark_scores_with_the_promoted_module():
    """One implementation: matchlab must not carry its own copy of the scorer."""
    sys.path.insert(0, str(API_ROOT / "scripts"))
    try:
        from matchlab import approaches, structure
    finally:
        sys.path.remove(str(API_ROOT / "scripts"))

    assert approaches.score_role_shape is rs.score_role_shape
    assert approaches.role_shape_components is rs.role_shape_components
    assert approaches.ROLE_SHAPE_WEIGHTS is rs.ROLE_SHAPE_WEIGHTS
    assert structure.parse_job is rs.parse_job


def test_the_benchmark_safety_orderings_hold(ctx):
    scores = {job["id"]: rs.match_for(job, ctx)["matchScore"] for job in JOBS}

    assert scores["backend"] > scores["frontend"], "boilerplate frontend must not outrank backend"
    assert scores["backend"] > scores["short"], "a vague posting must not score high by asking little"
    assert scores["backend"] > scores["k8s"], "side-project Kubernetes must not read as production"


def test_a_match_has_the_shape_the_queue_stores(ctx):
    match = rs.match_for(JOBS[0], ctx)

    assert match["matchMethod"] == "role-shape"
    assert 0.0 <= match["matchScore"] <= 100.0
    assert match["matchReason"].startswith("Role-shape match: Role family backend")
    # Role shape does not produce a skill list, so none is invented.
    assert match["keyMatchingSkills"] == [] and match["missingSkills"] == []


def test_a_posting_without_text_is_scored_on_its_title_not_zeroed(ctx):
    described = rs.match_for(JOBS[0], ctx)
    bare = rs.match_for({"id": "bare", "title": "Senior Backend Engineer", "company": "X"}, ctx)

    # Family and seniority both match exactly, renormalised over those two signals.
    assert bare["matchScore"] == 100.0
    assert "title alone" in bare["matchReason"]
    assert described["matchReason"].count("coverage") == 1


def test_scores_are_identical_across_processes():
    """String hashing differs per process; the score must not."""
    script = (
        "import json,sys;sys.path.insert(0,'.');"
        "from tests.test_role_shape_match import CORPUS,PROFILE,JOBS;"
        "from app.services.application_assistant import role_shape_match as rs;"
        "ctx=rs.build_context(PROFILE,{},CORPUS,[j['description'] for j in JOBS]);"
        "print(json.dumps([repr(rs.score_role_shape(type('P',(),j)(),ctx)) for j in JOBS]))"
    )
    outputs = set()
    for seed in ("1", "2", "3"):
        env = {**os.environ, "PYTHONHASHSEED": seed}
        result = subprocess.run(
            [sys.executable, "-c", script], cwd=API_ROOT, env=env,
            capture_output=True, text=True, check=True,
        )
        outputs.add(result.stdout.strip().splitlines()[-1])
    assert len(outputs) == 1, outputs


# ── the queue's scorer ───────────────────────────────────────────────────────

@pytest.fixture
def scorer(monkeypatch):
    monkeypatch.setattr("app.services.story_index.load_corpus", lambda path=None: CORPUS)
    return rs.QueueScorer(max_new_per_call=2)


def _descriptions():
    return [j["description"] for j in JOBS]


def test_the_scorer_bounds_new_work_per_call_and_remembers_it(scorer, monkeypatch):
    calls = []
    real = rs.match_for
    monkeypatch.setattr(rs, "match_for", lambda job, ctx: calls.append(job["id"]) or real(job, ctx))

    first = scorer.matches(JOBS, PROFILE, {}, _descriptions())
    second = scorer.matches(JOBS, PROFILE, {}, _descriptions())
    third = scorer.matches(JOBS, PROFILE, {}, _descriptions())

    assert len(first) == 2 and len(second) == 4 and len(third) == 4
    assert calls == ["backend", "frontend", "k8s", "short"], "each posting is scored exactly once"


def test_an_edited_posting_is_rescored(scorer):
    before = scorer.matches(JOBS[:1], PROFILE, {}, _descriptions())["backend"]
    edited = [{**JOBS[0], "description": FRONTEND_JD}]
    after = scorer.matches(edited, PROFILE, {}, _descriptions())["backend"]

    assert after["matchScore"] != before["matchScore"]


def test_a_resume_change_rebuilds_the_context(scorer):
    before = scorer.matches(JOBS[:1], PROFILE, {}, _descriptions())["backend"]
    after = scorer.matches(JOBS[:1], {"headline": "Senior Frontend Engineer", "skills": ["React"]}, {},
                           _descriptions())["backend"]

    assert after["matchScore"] != before["matchScore"]


def test_a_scoring_failure_leaves_jobs_unscored_instead_of_raising(monkeypatch):
    def boom(*args, **kwargs):
        raise RuntimeError("scorer broke")

    monkeypatch.setattr(rs.queue_scorer, "matches", boom)
    assert rs.role_shape_matches(JOBS, PROFILE, {}, JOBS) == {}


# ── wired into the queue ─────────────────────────────────────────────────────

@pytest.fixture
def llm_off(monkeypatch):
    from app.services.application_assistant import queue_preprocessor

    monkeypatch.setattr(queue_preprocessor, "LOCAL_LLM_ENABLED", False)
    monkeypatch.setattr("app.services.story_index.load_corpus", lambda path=None: CORPUS)
    monkeypatch.setattr(rs, "queue_scorer", rs.QueueScorer())
    return queue_preprocessor


def _save_rows(rows):
    from app.db.store import session_scope
    from app.services.application_assistant.persistence import save_autopilot_job

    with session_scope() as db:
        for row in rows:
            save_autopilot_job(db, dict(row))


def _rows(ids):
    from app.db.store import session_scope
    from app.services.application_assistant.persistence import list_autopilot_jobs

    with session_scope() as db:
        return {j["id"]: j for j in list_autopilot_jobs(db) if j["id"] in ids}


def test_waiting_jobs_without_a_real_score_get_a_role_shape_one(llm_off):
    from app.db.store import session_scope
    from app.services.application_assistant.persistence import upsert_discovered_job

    with session_scope() as db:
        upsert_discovered_job(db, {"id": "rs_disc_backend", "title": "Senior Backend Engineer",
                                   "company": "Rsco", "description": BACKEND_JD,
                                   "applicationUrl": "https://rsco.example/jobs/1"})
    base = {"company": "Rsco", "title": "Senior Backend Engineer", "jobId": "rs_disc_backend",
            "applicationUrl": "https://rsco.example/jobs/1", "matchScore": 0.0}
    _save_rows([
        {**base, "id": "apjob_rs_unscored", "status": "QUEUED", "matchMethod": "unscored"},
        {**base, "id": "apjob_rs_nomethod", "status": "QUEUED"},
        {**base, "id": "apjob_rs_heuristic", "status": "QUEUED", "matchMethod": "heuristic", "matchScore": 85.0},
        {**base, "id": "apjob_rs_model", "status": "QUEUED", "matchMethod": "ollama-local", "matchScore": 42.0},
        {**base, "id": "apjob_rs_review", "status": "NEEDS_REVIEW", "matchMethod": "unscored"},
    ])

    llm_off.QueuePreprocessor.get_instance()._role_shape_rescore_queue()
    rows = _rows({"apjob_rs_unscored", "apjob_rs_nomethod", "apjob_rs_heuristic",
                  "apjob_rs_model", "apjob_rs_review"})

    for job_id in ("apjob_rs_unscored", "apjob_rs_nomethod", "apjob_rs_heuristic"):
        assert rows[job_id]["matchMethod"] == "role-shape", job_id
        assert rows[job_id]["matchScore"] > 0
    assert rows["apjob_rs_model"]["matchMethod"] == "ollama-local"
    assert rows["apjob_rs_model"]["matchScore"] == 42.0
    # Only waiting jobs are rescored; a job already past the queue keeps its score.
    assert rows["apjob_rs_review"]["matchMethod"] == "unscored"


def test_the_rescore_leaves_the_queue_alone_while_the_model_is_on(llm_off, monkeypatch):
    monkeypatch.setattr(llm_off, "LOCAL_LLM_ENABLED", True)
    assert llm_off.QueuePreprocessor.get_instance()._role_shape_rescore_queue() == 0
