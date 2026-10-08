"""JD requirement -> career evidence -> selected project -> resume bullet, and the scores derived from it.

Scores are importance-weighted requirement coverage times evidence strength. No LLM is involved.
"""
from __future__ import annotations

import re
from typing import Any

from app.services.career_compiler.models import Bullet, JobDescription, Requirement, ResumeDocument, ResumePlan, Retrieval
from app.services.career_compiler.retrieval import STRENGTH_ORDER, STRENGTH_VALUE, WEIGHT, evidence_strength
from app.services.career_compiler.store import CareerStore, mentions

QUALIFICATIONS = {"required_qualifications", "preferred_qualifications", "technologies"}
DEGREE = re.compile(r"\b(degree|bachelor'?s?|master'?s?|b\.?s\.?|m\.?s\.?|ph\.?d)\b", re.I)


def _best(strengths: list[str | None]) -> str | None:
    found = [s for s in strengths if s]
    return min(found, key=STRENGTH_ORDER.__getitem__) if found else None


def section_support(req: Requirement, skills: dict[str, list[str]], education: list[dict]) -> dict[str, str]:
    """Coverage from the deterministic Skills and Education sections. A listed skill answers a qualification
    ("C#, Java or Python") but only weakly supports a responsibility; it is never strong."""
    out = {}
    listed = [t for terms in skills.values() for t in terms]
    if any(mentions(" ; ".join(listed), s) for s in req.skills):
        out["skills"] = "moderate" if req.section in QUALIFICATIONS else "weak"
    if DEGREE.search(req.original_text):
        degrees = " ".join(str(e.get("degree") or "") for e in education)
        fields = [f for f in ("computer science", "engineering", "software") if f in req.original_text.casefold()]
        if degrees and (not fields or any(f in degrees.casefold() for f in fields)):
            out["education"] = "moderate"
    return out


def bullet_requirements(bullet: Bullet, jd: JobDescription, store: CareerStore,
                        retrieval: Retrieval | None = None) -> list[dict[str, str]]:
    """Requirements a bullet covers: through the evidence it cites, or a requirement skill it names that its
    project's evidence supports."""
    out = []
    coverage = {}
    if retrieval:
        coverage = next((p.coverage for p in retrieval.projects if p.project_id == bullet.project_id), {})
    for req in jd.requirements:
        cited = [evidence_strength(req, store.evidence[i], store)[0] for i in bullet.evidence_ids if i in store.evidence
                 and store.evidence[i].status != "needs_reconciliation"]
        strength = _best(cited)
        if not strength and req.id in coverage and any(mentions(bullet.text, s) for s in req.skills):
            strength = "moderate" if coverage[req.id] != "weak" else "weak"
        if strength:
            out.append({"id": req.id, "strength": strength})
    return out


def score(values: dict[str, str | None], jd: JobDescription) -> int:
    total = sum(WEIGHT[r.importance] for r in jd.requirements)
    if not total:
        return 0
    got = sum(WEIGHT[r.importance] * STRENGTH_VALUE.get(values.get(r.id) or "", 0) for r in jd.requirements)
    return round(100 * got / total)


def report(jd: JobDescription, retrieval: Retrieval, store: CareerStore, *, plan: ResumePlan | None = None,
           document: ResumeDocument | None = None) -> dict[str, Any]:
    by_project = {p.project_id: p for p in retrieval.projects}
    store_skills = {g: [t for t in terms if isinstance(t, str)] for g, terms in (store.data.get("skills") or {}).items()
                    if isinstance(terms, list)}
    sections = {r.id: section_support(r, store_skills, store.data.get("education") or []) for r in jd.requirements}
    available = {r.id: _best([m.strength for m in retrieval.matches.get(r.id, [])] + list(sections[r.id].values()))
                 for r in jd.requirements}
    planned = {r.id: _best([by_project[p.project_id].coverage.get(r.id) for p in (plan.selected_projects if plan else [])
                            if p.project_id in by_project] + list(sections[r.id].values())) for r in jd.requirements}
    covering: dict[str, list[dict[str, str]]] = {r.id: [] for r in jd.requirements}
    if document:
        bullets = ([document.summary] if document.summary else []) + document.bullets()
        for bullet in bullets:
            for item in bullet.requirements:
                if item["id"] in covering:
                    covering[item["id"]].append({"bullet_id": bullet.id, "strength": item["strength"]})
        for req in jd.requirements:
            for name, strength in section_support(req, document.skills, document.education).items():
                covering[req.id].append({"bullet_id": name, "strength": strength})
    resume = {rid: _best([c["strength"] for c in items]) for rid, items in covering.items()}
    rows = []
    for req in jd.requirements:
        on_resume = resume.get(req.id)
        if not available[req.id]:
            status = "missing"
        elif document is None:
            status = "planned" if planned[req.id] else "uncovered"
        elif on_resume in ("strong", "moderate"):
            status = "covered"
        elif on_resume == "weak":
            status = "partial"
        else:
            status = "uncovered"
        rows.append({**req.model_dump(), "evidence": [m.model_dump() for m in retrieval.matches.get(req.id, [])],
                     "best_available": available[req.id], "planned": planned[req.id], "resume_strength": on_resume,
                     "bullets": covering[req.id], "status": status})
    required = [r for r in jd.requirements if r.section == "required_qualifications"]
    target = resume if document else planned
    return {"requirements": rows, "scores": {
        "evidence": score(available, jd), "planned": score(planned, jd),
        "resume": score(resume, jd) if document else None,
        "required_covered": sum(1 for r in required if target.get(r.id) in ("strong", "moderate")),
        "required_total": len(required),
        "method": "sum(importance weight x evidence strength) / sum(importance weight); "
                  "weights high=3 medium=2 low=1; strength strong=1.0 moderate=0.6 weak=0.25"}}
