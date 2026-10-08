"""Orchestrates the compiler stages.

career.json owns facts, jd.json owns job requirements, the golden DOCX owns format, DeepSeek owns reasoning and
wording, this module owns retrieval, traceability, validation and page fit, and Word (via docx_render) owns layout.
The client holds the plan and bullets; the server re-checks everything against the canonical files.
"""
from __future__ import annotations

import base64
import logging
import time
from contextlib import contextmanager
from dataclasses import dataclass
from typing import Any, Iterator

from pydantic import BaseModel, Field

from app.services.career_compiler import critic, feedback, prompts, scoring, style, trace, versions
from app.services.career_compiler.deepseek import DeepSeekClient, DeepSeekError
from app.services.career_compiler.docx_render import (
    Measurement, Rendered, WordMeasurer, formatting_drift, match_blocks, pdf_rows, preview_png, render_docx,
)
from app.services.career_compiler.docx_template import load_golden, load_spec, template_digest
from app.services.career_compiler.jobs import analysis_from_jd, ingest_job_description, load_jd, structure_job_description
from app.services.career_compiler.lexicon import mentions_tech, technologies
from app.services.career_compiler.metrics import Run, lead_runs, line_count, project_runs, skill_runs, summary_runs
from app.services.career_compiler.models import (
    Bullet, CoverageItem, JobDescription, PlannedProject, Ranking, ResumeDocument, ResumePlan, Retrieval, Section,
    SectionBudget, ValidationIssue,
)
from app.services.career_compiler.query import QUERY_VERSION, apply_query, build_evidence_query, load_query
from app.services.career_compiler.career_signal import career_signal
from app.services.career_compiler.retrieval import (
    RETRIEVAL_VERSION, STRENGTH_ORDER, STRENGTH_VALUE, coverage_reason, rank_evidence, retrieve_evidence,
)
from app.services.career_compiler.store import EXISTENCE_ONLY, PERSONAL_EMPLOYMENT_ID, CareerStore, load_store, mentions
from app.services.career_compiler.validator import numbers, validate_bullet
from app.services.career_compiler.weights import requirement_weight
from app.services.career_compiler.word import ConverterUnavailable

logger = logging.getLogger("careeros.career_compiler")
MICROSOFT, AMAZON = "employment.microsoft", "employment.amazon"
#: (minimum, maximum) bullets per section. Earlier roles are 0..EARLIER_MAX each.
LIMITS = {MICROSOFT: (2, 7), AMAZON: (3, 10), PERSONAL_EMPLOYMENT_ID: (0, 2)}
EARLIER_MAX = 2
BULLET_LINES, RICH_LINES, SPARSE_LINES, PROJECT_LINES = 2, 3, 1, 2
RICH_BULLETS = 3
#: Coverage loss (importance weight x strength) at or below which content is removed before anything is compressed.
LOW_VALUE = 1.0
SUMMARY_FLOOR = 1.5
REINFORCE = .15
#: Filling space once the JD is covered: each new capability adds DIVERSITY_BONUS; evidence that shows nothing new
#: keeps only REDUNDANT_SHARE of its signal; every evidence record already on the page costs REUSE_PENALTY.
#: At or above STRONG_SIGNAL a pick is career signal, below it diversity.
DIVERSITY_BONUS, REDUNDANT_SHARE, REUSE_PENALTY, STRONG_SIGNAL = .6, .4, 1.0, 2.5
REPAIR_ROUNDS = 2
COMPRESS_ROUNDS = 4
FIT_ROUNDS = 30
BODY_SIZE = 8.0
SKILL_GROUPS = ("languages", "architecture_systems", "cloud_platform", "ai_ml_security")
SLOT_EVIDENCE = 5
EXEMPLARS = 6


class _Written(BaseModel):
    slot_id: str
    text: str
    evidence_ids: list[str] = Field(default_factory=list)


class _Summary(BaseModel):
    text: str
    evidence_ids: list[str] = Field(default_factory=list)


class _WriteResponse(BaseModel):
    summary: _Summary | None = None
    bullets: list[_Written] = Field(default_factory=list)


class _Bullets(BaseModel):
    bullets: list[_Written] = Field(default_factory=list)


class CompilerUnavailable(RuntimeError):
    pass


class Stages:
    """Per-stage observability: latency, DeepSeek calls, tokens, retries and stage-specific counters."""

    def __init__(self) -> None:
        self.items: list[dict[str, Any]] = []

    @contextmanager
    def stage(self, name: str) -> Iterator[dict[str, Any]]:
        record: dict[str, Any] = {"stage": name, "calls": []}
        started = time.perf_counter()
        try:
            yield record
        finally:
            calls = [c for c in record.pop("calls") if c]
            record.update({"latency_ms": round((time.perf_counter() - started) * 1000), "deepseek_calls": len(calls),
                           "tokens": sum(c.get("tokens") or 0 for c in calls) or None,
                           "retries": sum(max(0, (c.get("attempts") or 1) - 1) for c in calls), "cost_usd": None})
            self.items.append(record)


def _limits(employment_id: str) -> tuple[int, int]:
    return LIMITS.get(employment_id, (0, EARLIER_MAX))


def _section_name(employment_id: str) -> str:
    return {MICROSOFT: "microsoft", AMAZON: "amazon", PERSONAL_EMPLOYMENT_ID: "projects"}.get(employment_id, "earlier")


def _template_lines(spec: dict[str, Any]) -> dict[str, Any]:
    """Line costs of the template's fixed parts, from Word's measurement of the golden."""
    lines, slots = spec["rendered"]["paragraph_lines"], spec["slots"]
    at = lambda index: lines.get(f"p{index}", 1)
    return {"capacity": spec["rendered"]["capacity_lines"], "summary": at(slots["summary"]),
            "skills": {l["group"]: at(l["paragraph"]) for l in slots["skills"]["lines"]},
            "education": sum(at(i) for i in slots["education"])}


def generate_resume_plan(jd: JobDescription, ranking: Ranking, retrieval: Retrieval, store: CareerStore,
                         spec: dict[str, Any] | None = None) -> ResumePlan:
    """Decide section budgets before writing: greedy requirement coverage per template line, within one page.

    Every candidate costs its bullet lines plus any role header, separator or heading it brings onto the page.
    Section minimums are filled first; then the best marginal coverage per line wins until the page is full.
    DeepSeek's ranking only breaks ties."""
    spec = spec or load_spec()
    cost_of = _template_lines(spec)
    roles = {r["employment_id"] for r in spec["slots"]["roles"] if r["employment_id"]}
    weight = {r.id: requirement_weight(r) for r in jd.requirements}
    order = {r.project_id: i for i, r in enumerate(ranking.projects)}
    ranked = {r.project_id: r for r in ranking.projects}
    # Experience heading, Microsoft and Amazon headers with the rule between them, education, skills, summary.
    used = 1 + 3 + 1 + cost_of["education"] + 1 + sum(cost_of["skills"].values()) + 1 + cost_of["summary"]
    capacity = cost_of["capacity"]
    pool = [p for p in retrieval.projects if p.employment_id in roles or p.employment_id == PERSONAL_EMPLOYMENT_ID]
    covered: dict[str, float] = {}
    taken: dict[str, int] = {}
    selected: list[PlannedProject] = []
    gains: dict[str, float] = {}

    def lines_for(candidate) -> int:
        if candidate.existence_only:
            return SPARSE_LINES
        return PROJECT_LINES if candidate.employment_id == PERSONAL_EMPLOYMENT_ID else BULLET_LINES

    def cost(candidate) -> int:
        extra = 0
        if not taken.get(candidate.employment_id):
            if candidate.employment_id == PERSONAL_EMPLOYMENT_ID:
                extra = 1
            elif candidate.employment_id not in LIMITS:
                extra = 2
        return lines_for(candidate) + extra

    def gain(candidate) -> float:
        """New coverage, plus a small credit for reinforcing a requirement another bullet already covers."""
        return sum(weight[r] * (max(0.0, STRENGTH_VALUE[s] - covered.get(r, 0)) + REINFORCE * min(STRENGTH_VALUE[s], covered.get(r, 0)))
                   for r, s in candidate.coverage.items())

    def bonus(candidate) -> float:
        """DeepSeek's order, then evidence of ownership and measured impact. Never enough to beat real coverage."""
        types = {c.type for c in candidate.evidence if c.status == "supported"}
        signal = .15 * bool(types & {"metric", "scale"}) + .1 * bool(types & {"ownership", "decision", "architecture"})
        return .5 * (1 - order.get(candidate.project_id, len(order)) / max(len(order), 1)) + signal + .001 * candidate.score

    def take(candidate, selection: str | None = None, why: str = "", evidence_ids: list[str] | None = None,
             score: float | None = None) -> None:
        nonlocal used
        used += cost(candidate)
        gains[candidate.project_id] = gain(candidate)
        taken[candidate.employment_id] = taken.get(candidate.employment_id, 0) + 1
        for r, s in candidate.coverage.items():
            covered[r] = max(covered.get(r, 0), STRENGTH_VALUE[s])
        llm_reason = ranked[candidate.project_id].reason if candidate.project_id in ranked else ""
        reason = why or coverage_reason(candidate) + (f". {llm_reason}" if llm_reason and ranking.source == "deepseek" else "")
        ids = evidence_ids or (ranked[candidate.project_id].evidence_ids if candidate.project_id in ranked
                               else [c.evidence_id for c in candidate.evidence[:3]])
        selected.append(PlannedProject(project_id=candidate.project_id, employment_id=candidate.employment_id,
                                       reason=reason[:400], evidence_ids=ids, requirement_ids=list(candidate.coverage),
                                       score=round(gains[candidate.project_id] + bonus(candidate), 3) if score is None else score,
                                       lines=lines_for(candidate),
                                       selection=selection or ("jd_match" if gains[candidate.project_id] > 0 else "career_signal")))

    def open_candidates(only: str | None = None) -> list:
        chosen = {s.project_id for s in selected}
        return [c for c in pool if c.project_id not in chosen and (only is None or c.employment_id == only)
                and taken.get(c.employment_id, 0) < _limits(c.employment_id)[1]]

    for employment_id, (minimum, _) in LIMITS.items():
        while taken.get(employment_id, 0) < minimum:
            options = open_candidates(employment_id)
            if not options:
                break
            take(max(options, key=lambda c: (gain(c) + bonus(c), c.project_id)))
    while True:
        # Beyond section minimums, content that answers the JD earns space first.
        options = [c for c in open_candidates() if c.coverage and used + cost(c) <= capacity]
        if not options:
            break
        take(max(options, key=lambda c: ((gain(c) + .1 * bonus(c)) / cost(c), c.project_id)))
    for item in sorted((s for s in selected if s.lines == BULLET_LINES and s.employment_id != PERSONAL_EMPLOYMENT_ID),
                       key=lambda s: -gains[s.project_id])[:RICH_BULLETS]:
        if used < capacity and gains[item.project_id] > 0:
            item.lines, used = RICH_LINES, used + 1
    # The JD is covered as far as career.json allows. Spend the page that is left on the strongest unused supported
    # evidence rather than whitespace. Such bullets carry no JD coverage, so page fitting removes them first.
    signals = {c.project_id: career_signal(store, c.project_id, [e.evidence_id for e in c.evidence])
               for c in pool if not c.existence_only}
    shown: set[str] = set().union(*(signals[s.project_id].capabilities for s in selected if s.project_id in signals))
    used_evidence = {i for s in selected for i in s.evidence_ids}

    def career_value(candidate) -> float:
        signal = signals[candidate.project_id]
        new = signal.capabilities - shown
        repeated = len(set(signal.evidence_ids) & used_evidence)
        return signal.score * (1 if new else REDUNDANT_SHARE) + DIVERSITY_BONUS * len(new) - REUSE_PENALTY * repeated

    while True:
        options = [c for c in open_candidates() if c.project_id in signals and signals[c.project_id].supported
                   and used + cost(c) <= capacity and career_value(c) > 0]
        if not options:
            break
        best = max(options, key=lambda c: (career_value(c) / cost(c), c.project_id))
        signal = signals[best.project_id]
        new = sorted(signal.capabilities - shown)
        kind = "diversity" if new and signal.score < STRONG_SIGNAL else "career_signal"
        why = (f"Adds {', '.join(n.replace('_', ' ') for n in new)} to the page" if kind == "diversity"
               else f"Strong career evidence beyond this posting: {'; '.join(signal.reasons) or 'supported work'}")
        take(best, kind, why, list(signal.evidence_ids[:3]), round(.01 * career_value(best), 3))
        shown |= signal.capabilities
        used_evidence |= set(signal.evidence_ids)
    counts = {name: sum(1 for s in selected if _section_name(s.employment_id) == name)
              for name in ("microsoft", "amazon", "earlier", "projects")}
    budget = SectionBudget(summary=1, capacity_lines=capacity, planned_lines=used, **counts)
    themes = analysis_from_jd(jd).themes
    return ResumePlan(target_role=ranking.target_role or jd.title, jd_themes=themes,
                      primary_themes=ranking.primary_themes or jd.repeated_themes[:5] or themes[:5],
                      selected_projects=selected, section_budget=budget,
                      coverage_plan=coverage_plan(jd, retrieval, selected))


def coverage_plan(jd: JobDescription, retrieval: Retrieval, selected: list[PlannedProject]) -> list[CoverageItem]:
    """Which planned project is meant to answer each requirement, and why the rest stay uncovered."""
    by_project = {p.project_id: p for p in retrieval.projects}
    out = []
    for req in jd.requirements:
        covering = [(by_project[s.project_id].coverage[req.id], s.project_id) for s in selected
                    if s.project_id in by_project and req.id in by_project[s.project_id].coverage]
        covering.sort(key=lambda c: (STRENGTH_ORDER[c[0]], c[1]))
        available = [m.strength for m in retrieval.matches.get(req.id, [])]
        if covering:
            out.append(CoverageItem(requirement_id=req.id, project_ids=[p for _, p in covering], strength=covering[0][0]))
        elif any(s in ("strong", "moderate") for s in available):
            best = min(available, key=STRENGTH_ORDER.__getitem__)
            out.append(CoverageItem(requirement_id=req.id, strength=best, status="supported_not_planned"))
        else:
            out.append(CoverageItem(requirement_id=req.id, strength="weak" if available else None,
                                    status="no_supported_evidence"))
    return out


def _compact_candidates(retrieval: Retrieval, ranking: Ranking) -> list[dict[str, Any]]:
    reasons = {r.project_id: r.reason for r in ranking.projects}
    return [{"project_id": p.project_id, "name": p.name, "company": p.company or "Personal project",
             "employment_id": p.employment_id, "score": p.score, "coverage": p.coverage, "existence_only": p.existence_only,
             "reason": reasons.get(p.project_id) or coverage_reason(p),
             "evidence": [c.model_dump(include={"evidence_id", "type", "status", "claim", "requirement_ids"}) for c in p.evidence],
             "blocked": [{"evidence_id": c.evidence_id, "claim": c.claim, "status": c.status} for c in p.blocked]}
            for p in retrieval.projects]


def analyze(*, text: str = "", url: str = "", title: str = "", company: str = "", refresh: bool = False,
            store: CareerStore | None = None, llm: DeepSeekClient | None = None) -> dict[str, Any]:
    store = store or load_store()
    llm = llm or DeepSeekClient()
    stages = Stages()
    with stages.stage("ingestJobDescription"):
        job = ingest_job_description(text, url, title, company)
    with stages.stage("analyzeJobDescription") as record:
        jd, warnings, structure_meta = structure_job_description(job, store, llm, refresh=refresh)
        record["calls"].append(structure_meta)
        record["requirements"] = len(jd.requirements)
    with stages.stage("buildEvidenceQuery") as record:
        query, query_warnings, query_meta = build_evidence_query(jd, store, llm, refresh=refresh)
        record["calls"].append(query_meta)
        record["terms"] = sum(len(q.terms) + len(q.adjacent) for q in query.requirements)
        jd = apply_query(jd, query)
    excluded = feedback.excluded_evidence(jd.id)
    with stages.stage("retrieveEvidence") as record:
        retrieval = retrieve_evidence(jd, store, excluded=excluded)
        record["candidates"] = len(retrieval.projects)
    with stages.stage("rankEvidence") as record:
        ranking, rank_warnings, rank_meta = rank_evidence(jd, retrieval, llm)
        record["calls"].append(rank_meta)
    with stages.stage("generateResumePlan"):
        plan = generate_resume_plan(jd, ranking, retrieval, store)
    if excluded:
        warnings.append(f"{len(excluded)} evidence record(s) you excluded or rejected for this job are held back.")
    return {"jd": jd.model_dump(), "analysis": analysis_from_jd(jd).model_dump(), "plan": plan.model_dump(),
            "trace": trace.report(jd, retrieval, store, plan=plan), "query": query.model_dump(),
            "candidates": _compact_candidates(retrieval, ranking), "guardrails": retrieval.guardrails,
            "conflicts": retrieval.conflicts, "warnings": warnings + query_warnings + rank_warnings,
            "store_digest": store.digest, "ranking_source": ranking.source, "excluded_evidence": sorted(excluded),
            "versions": {"retrieval": RETRIEVAL_VERSION, "query": QUERY_VERSION, "prompts": prompts.PROMPT_VERSIONS,
                         "model": llm.model},
            "stages": stages.items, "deepseek": [m for m in (structure_meta, query_meta, rank_meta) if m]}


def _allowed(store: CareerStore, project_id: str, excluded: set[str] | frozenset[str] = frozenset()) -> set[str]:
    return {e.id for e in store.project_evidence(project_id) if (e.usable or e.status in EXISTENCE_ONLY) and e.id not in excluded}


def _check_plan(plan: ResumePlan, store: CareerStore, excluded: set[str] | frozenset[str] = frozenset(),
                warnings: list[str] | None = None) -> list[PlannedProject]:
    """Re-check the client's plan against career.json. Evidence the user excluded for this job is withheld unless
    they pinned it again; a project left with nothing usable is dropped with a warning."""
    checked, seen = [], set()
    for item in plan.selected_projects:
        project = store.projects.get(item.project_id)
        if project is None or project.employment_id != item.employment_id or item.project_id in seen:
            raise ValueError(f"Plan entry {item.project_id} does not match career.json.")
        seen.add(item.project_id)
        allowed = _allowed(store, item.project_id, frozenset() if item.pinned or item.locked else excluded)
        if not allowed:
            if _allowed(store, item.project_id):
                (warnings if warnings is not None else []).append(
                    f"Left out {project.name}: you excluded all of its evidence for this job.")
                continue
            raise ValueError(f"{item.project_id} has no usable evidence.")
        ids = [i for i in item.evidence_ids if i in allowed]
        if item.pinned and not ids:
            raise ValueError(f"Pinned evidence for {item.project_id} is not usable.")
        checked.append(item.model_copy(update={"evidence_ids": ids}))
    return checked


def _slot_allowed(store: CareerStore, item: PlannedProject, excluded: set[str] | frozenset[str] = frozenset()) -> set[str]:
    return set(item.evidence_ids) if item.pinned else _allowed(store, item.project_id, frozenset() if item.locked else excluded)


class Writer:
    """Slot line budgets and the character budgets DeepSeek is told, from the template's text widths."""

    def __init__(self, spec: dict[str, Any], budgets: dict[str, int]):
        from reportlab.pdfbase.pdfmetrics import stringWidth
        geometry = spec["rendered"]
        self.lead = spec["runs"]["lead"]
        self.width = {"bullet": geometry["text_width_bullet"], "body": geometry["text_width_body"]}
        self.summary_lines = _template_lines(spec)["summary"]
        self.budgets = budgets
        sample = "Built shared deployment tooling that cut service setup from two weeks to under one hour across teams."
        self.char_width = stringWidth(sample, "Helvetica", BODY_SIZE) / len(sample)

    def runs(self, bullet: Bullet) -> list[Run]:
        if bullet.id == "summary":
            return summary_runs(bullet.text)
        if bullet.employment_id == PERSONAL_EMPLOYMENT_ID:
            return project_runs(bullet.name, bullet.text)
        return lead_runs(bullet.text, self.lead)

    def lines(self, bullet: Bullet) -> int:
        width = self.width["body" if bullet.id == "summary" else "bullet"]
        return line_count(self.runs(bullet), width, BODY_SIZE)[0]

    def budget(self, bullet: Bullet) -> int:
        return self.summary_lines if bullet.id == "summary" else self.budgets.get(bullet.id, BULLET_LINES)

    def slot_chars(self, bullet_id: str, lines: int | None = None) -> int:
        width = self.width["body" if bullet_id == "summary" else "bullet"]
        lines = lines or (self.summary_lines if bullet_id == "summary" else self.budgets.get(bullet_id, BULLET_LINES))
        # Headroom for the bold lead-in and word-wrap waste: DeepSeek's character counts run long.
        return int(lines * width / self.char_width * .86)


def _slot(store: CareerStore, item: PlannedProject, jd: JobDescription, writer: Writer, allowed: set[str]) -> dict[str, Any]:
    project = store.projects[item.project_id]
    records = [e for e in store.project_evidence(item.project_id) if e.id in allowed]
    targets = [r for r in jd.requirements if r.id in item.requirement_ids]
    terms = [s for r in targets for s in r.skills]
    records.sort(key=lambda e: (e.id not in item.evidence_ids, -sum(mentions(e.claim, t) for t in terms), e.id))
    existence_only = all(e.status in EXISTENCE_ONLY for e in records)
    job = store.employment.get(item.employment_id) or {}
    name_chars = len(project.name) + 2 if project.personal else 0
    slot = {"slot_id": item.project_id, "company": job.get("company", "Personal project"), "role": job.get("role", ""),
            "project": project.name, "existence_only": existence_only, "why_selected": item.reason,
            "max_chars": writer.slot_chars(item.project_id) - name_chars,
            "targets": [{"id": r.id, "requirement": r.normalized_requirement} for r in targets[:5]],
            "evidence": [{"id": e.id, "type": e.type, "status": e.status, "claim": e.claim}
                         for e in records[:len(item.evidence_ids) if item.pinned else SLOT_EVIDENCE]]}
    if not existence_only:
        slot["project_context"] = {"summary": project.summary, "technologies": list(project.technologies),
                                   "ownership": list(project.ownership)}
    return slot


def _summary_slot(store: CareerStore, plan: list[PlannedProject], writer: Writer) -> dict[str, Any]:
    positioning = (store.data.get("person") or {}).get("positioning") or {}
    evidence = [store.evidence[i] for i in ("person.positioning.experience", "person.positioning.primary") if i in store.evidence]
    for item in plan:
        evidence += [store.evidence[i] for i in item.evidence_ids[:1] if store.evidence[i].usable]
    return {"slot_id": "summary", "max_chars": writer.slot_chars("summary"), "positioning": positioning.get("primary") or [],
            "evidence": [{"id": e.id, "type": e.type, "claim": e.claim} for e in evidence]}


def _exemplars(spec: dict[str, Any]) -> list[str]:
    """The user's own template bullets, one per opening verb. Voice only: their facts are never evidence."""
    picked, openers = [], set()
    for item in spec.get("style_exemplars") or []:
        opener = item["text"].split(" ", 1)[0].casefold()
        if opener not in openers:
            openers.add(opener)
            picked.append(item["text"])
        if len(picked) == EXEMPLARS:
            break
    return picked


def fit_skill_items(label: str, items: list[str], lines: int, spec: dict[str, Any]) -> list[str]:
    """Largest ordered prefix of `items` that fits `lines` lines of the template's skills paragraph."""
    width, separator = spec["rendered"]["text_width_bullet"], spec["slots"]["skills"]["separator"]
    kept = list(items)
    while kept and line_count(skill_runs(label, kept, separator), width, BODY_SIZE)[0] > lines:
        kept.pop()
    return kept


def _skills(store: CareerStore, plan: list[PlannedProject], jd: JobDescription, spec: dict[str, Any]) -> dict[str, list[str]]:
    skills = store.data.get("skills") or {}
    support = " ".join(" ".join((p.name, p.summary, *p.technologies, *p.details,
                                 *(e.claim for e in store.project_evidence(p.id) if e.usable)))
                       for p in store.projects.values() if not store.project_is_sparse(p.id))
    selected = " ".join(" ".join(store.projects[p.project_id].technologies) for p in plan)
    wanted = " ".join([jd.text] + [s for r in jd.requirements for s in r.skills])
    budgets = _template_lines(spec)["skills"]
    output: dict[str, list[str]] = {}
    for line in spec["slots"]["skills"]["lines"]:
        group = line["group"]
        terms = [t for t in skills.get(group) or [] if isinstance(t, str) and mentions(support, t)]
        terms.sort(key=lambda t: (not mentions(wanted, t), not mentions(selected, t), (skills.get(group) or []).index(t)))
        kept = fit_skill_items(line["label"], terms, budgets.get(group, 1), spec)
        if kept:
            output[group] = kept
    return output


def build_document(store: CareerStore, spec: dict[str, Any], jd: JobDescription, plan: list[PlannedProject],
                   bullets: dict[str, Bullet], summary: Bullet | None, skills: dict[str, list[str]]) -> ResumeDocument:
    order = {p.project_id: i for i, p in enumerate(plan)}
    sections = []
    for employment_id, job in store.employment.items():
        chosen = sorted((b for b in bullets.values() if b.employment_id == employment_id), key=lambda b: order.get(b.project_id, 99))
        sections.append(Section(employment_id=employment_id, company=job["company"], role=job["role"],
                                location=job.get("location", ""), start=job.get("start", ""), end=job.get("end", ""), bullets=chosen))
    featured = sorted((b.model_copy(update={"name": store.projects[b.project_id].name}) for b in bullets.values()
                       if b.employment_id == PERSONAL_EMPLOYMENT_ID), key=lambda b: order.get(b.project_id, 99))
    return ResumeDocument(store_digest=store.digest, jd_id=jd.id, template_digest=template_digest(spec),
                          target_role=jd.title, summary=summary, sections=sections, featured=featured, skills=skills,
                          education=[{k: e.get(k) for k in ("institution", "degree", "start", "end", "location")}
                                     for e in store.data.get("education") or []])


def _no_new_facts(old: Bullet, new: Bullet, store: CareerStore) -> bool:
    if not set(new.evidence_ids) <= set(old.evidence_ids) or not numbers(new.text) <= numbers(old.text):
        return False
    known = technologies(store.technologies)
    return {t for t in known if mentions_tech(new.text, t)} <= {t for t in known if mentions_tech(old.text, t)}


class Session:
    """One generate request: holds the DeepSeek client, call log and per-slot evidence permissions."""

    def __init__(self, store: CareerStore, llm: DeepSeekClient, spec: dict[str, Any], allowed: dict[str, set[str]],
                 budgets: dict[str, int]):
        self.store, self.llm, self.spec, self.allowed = store, llm, spec, allowed
        self.writer = Writer(spec, budgets)
        self.exemplars = _exemplars(spec)
        self.calls: list[dict] = []
        self.warnings: list[str] = []
        self.counters = {"validation_failures": 0, "rewrites": 0, "page_fit_iterations": 0}

    def validate(self, bullet: Bullet) -> list[ValidationIssue]:
        if bullet.id == "summary":
            return validate_bullet(bullet, self.store, summary=True)
        return validate_bullet(bullet, self.store, allowed=self.allowed.get(bullet.project_id, set()))

    def over_budget(self, bullet: Bullet) -> list[ValidationIssue]:
        used, budget = self.writer.lines(bullet), self.writer.budget(bullet)
        if used <= budget:
            return []
        chars = self.writer.slot_chars(bullet.id)
        return [ValidationIssue(bullet_id=bullet.id, code="over_budget",
                                message=f"Renders on {used} lines; the slot is {budget} lines (about {chars} characters). "
                                        "Drop a clause or a secondary detail; keep the facts you keep exact.")]

    def _ask(self, task: str, system: str, items: list[Bullet], max_lines: dict[str, int], notes: dict[str, list[str]]) -> dict[str, _Written]:
        payload = {"items": [{"slot_id": b.id, "text": b.text, "max_chars": self.writer.slot_chars(b.id, max_lines[b.id])
                              - (len(b.name) + 2 if b.employment_id == PERSONAL_EMPLOYMENT_ID else 0),
                              "evidence": [{"id": i, "claim": self.store.evidence[i].claim} for i in b.evidence_ids if i in self.store.evidence],
                              **({"problems": notes[b.id]} if notes.get(b.id) else {})} for b in items],
                   "style_exemplars": self.exemplars}
        try:
            result, meta = self.llm.complete_json(task=task, system=system, user=payload, schema=_Bullets, max_tokens=1800, temperature=.2)
        except DeepSeekError as exc:
            self.warnings.append(f"{task} skipped: {exc}")
            return {}
        self.calls.append(meta)
        self.counters["rewrites"] += len(items)
        return {w.slot_id: w for w in result.bullets}

    def compress(self, items: list[Bullet], target: dict[str, int]) -> dict[str, Bullet]:
        """Shorter versions that validate, add no facts, and are estimated to fit `target` lines."""
        if not items or not self.llm.configured:
            return {}
        out: dict[str, Bullet] = {}
        notes: dict[str, list[str]] = {}
        rejected: dict[str, str] = {}
        for attempt in range(2):
            todo = [b for b in items if b.id not in out and (attempt == 0 or b.id in notes)]
            if not todo:
                break
            for slot_id, written in self._ask("compress_bullets", prompts.COMPRESS_SYSTEM, todo, target, notes).items():
                old = next((b for b in todo if b.id == slot_id), None)
                if old is None:
                    continue
                new = old.model_copy(update={"text": written.text.strip(), "evidence_ids": written.evidence_ids or old.evidence_ids})
                issues, used = self.validate(new), self.writer.lines(new)
                if issues:
                    rejected[slot_id] = f"{issues[0].code}: {issues[0].message}"
                elif not _no_new_facts(old, new, self.store):
                    rejected[slot_id] = "it introduced a number, technology or evidence ID the original did not have"
                elif used > target[slot_id] or len(new.text) >= len(old.text):
                    rejected[slot_id] = f"it still needs {used} lines"
                    limit = self.writer.slot_chars(old.id, target[slot_id])
                    notes[slot_id] = [f"Your last draft was {len(new.text)} characters and still took {used} lines. "
                                      f"It must be at most {limit} characters. Keeping every fact will not fit: drop "
                                      "the least relevant clause or number entirely."]
                else:
                    out[slot_id] = new
            notes = {k: v for k, v in notes.items() if k not in out and "lines" in rejected.get(k, "")}
            if not notes:
                break
        for slot_id, reason in rejected.items():
            if slot_id not in out:
                self.warnings.append(f"Kept the longer {slot_id}: the compressed draft was rejected because {reason}.")
        return out

    def restyle(self, items: list[Bullet], findings: dict[str, list[dict]]) -> dict[str, Bullet]:
        if not items or not self.llm.configured:
            return {}
        notes = {b.id: [f["message"] for f in findings[b.id]] for b in items}
        lines = {b.id: max(self.writer.lines(b), 1) for b in items}
        out = {}
        for slot_id, written in self._ask("restyle_bullets", prompts.RESTYLE_SYSTEM, items, lines, notes).items():
            old = next((b for b in items if b.id == slot_id), None)
            if old is None:
                continue
            new = old.model_copy(update={"text": written.text.strip(), "evidence_ids": written.evidence_ids or old.evidence_ids})
            if (not self.validate(new) and style.same_facts(old, new, technologies(self.store.technologies))
                    and self.writer.lines(new) <= lines[slot_id]):
                out[slot_id] = new
        return out


@dataclass
class _Removal:
    kind: str  # bullet | summary | skills
    key: str
    lines: int
    loss: float
    rank: float

    @property
    def per_line(self) -> float:
        return self.loss / max(self.lines, 1)


def _coverage_loss(key: str, covers: dict[str, dict[str, float]], weight: dict[str, int]) -> float:
    """Weighted JD coverage that disappears if `key` leaves the page."""
    loss = 0.0
    for req, value in covers.get(key, {}).items():
        rest = max((c.get(req, 0) for k, c in covers.items() if k != key), default=0)
        loss += weight.get(req, 0) * max(0.0, value - rest)
    return loss


def _removals(bullets: dict[str, Bullet], summary: Bullet | None, skills: dict[str, list[str]], m: Measurement,
              covers: dict[str, dict[str, float]], weight: dict[str, int], scores: dict[str, float],
              jd: JobDescription, spec: dict[str, Any]) -> list[_Removal]:
    counts: dict[str, int] = {}
    for b in bullets.values():
        counts[b.employment_id] = counts.get(b.employment_id, 0) + 1
    out = []
    for b in bullets.values():
        if b.locked or counts[b.employment_id] <= _limits(b.employment_id)[0]:
            continue
        lines = m.lines.get(b.id, BULLET_LINES)
        if counts[b.employment_id] == 1:
            lines += 1 if b.employment_id == PERSONAL_EMPLOYMENT_ID else 2
        out.append(_Removal("bullet", b.id, lines, _coverage_loss(b.id, covers, weight), scores.get(b.project_id, 0)))
    if summary is not None and not summary.locked:
        loss = max(_coverage_loss("summary", covers, weight), SUMMARY_FLOOR)
        out.append(_Removal("summary", "summary", m.lines.get("summary", 3) + 1, loss, 0))
    wanted = " ".join([jd.text] + [s for r in jd.requirements for s in r.skills])
    labels = {l["group"]: l["label"] for l in spec["slots"]["skills"]["lines"]}
    for group, items in skills.items():
        lines = m.lines.get(f"skills:{group}", 1)
        if lines < 2 or group not in labels:
            continue
        kept = fit_skill_items(labels[group], items, lines - 1, spec)
        dropped = items[len(kept):]
        if kept and dropped:
            out.append(_Removal("skills", group, 1, .2 + .25 * sum(mentions(wanted, t) for t in dropped), 0))
    return out


def fit_to_page(session: Session, jd: JobDescription, plan: list[PlannedProject], bullets: dict[str, Bullet],
                summary: Bullet | None, skills: dict[str, list[str]], retrieval: Retrieval, measurer, golden: bytes,
                fresh: set[str] | None = None) -> tuple[ResumeDocument, Rendered, Measurement, list[str]]:
    """Fit one page without touching the template: generate -> render -> measure in Word -> if over, remove the
    lowest-value unlocked content (or, when everything left carries real JD coverage, compress the overflowing
    bullets) -> re-render. Locked content is never removed or rewritten."""
    store, writer, spec = session.store, session.writer, session.spec
    log: list[str] = []
    bullets, skills = dict(bullets), {g: list(v) for g, v in skills.items()}
    scores = {p.project_id: p.score for p in plan}
    weight = {r.id: requirement_weight(r) for r in jd.requirements}
    coverage = {p.project_id: p.coverage for p in retrieval.projects}
    seen_evidence: set[str] = set()
    for key in sorted(bullets, key=lambda k: -scores.get(k, 0)):
        ids = set(bullets[key].evidence_ids)
        if ids and ids <= seen_evidence and not bullets[key].locked:
            log.append(f"Merged {key} away: its evidence is already used by a higher-ranked bullet.")
            bullets.pop(key)
        seen_evidence |= ids
    rounds = 0

    def apply(changed: dict[str, Bullet], why: str) -> None:
        nonlocal summary
        for slot_id, new in changed.items():
            log.append(why.format(slot=slot_id))
            if slot_id == "summary":
                summary = new
            else:
                bullets[slot_id] = new

    for _ in range(FIT_ROUNDS):
        session.counters["page_fit_iterations"] += 1
        document = build_document(store, spec, jd, plan, bullets, summary, skills)
        rendered = render_docx(document, spec, golden, trace=False)
        m = measurer.measure(rendered)
        everything = list(bullets.values()) + ([summary] if summary else [])
        over_slot = [b for b in everything if not b.locked and (fresh is None or b.id in fresh)
                     and m.lines.get(b.id, 0) > writer.budget(b)]
        if over_slot and rounds < COMPRESS_ROUNDS:
            rounds += 1
            changed = session.compress(over_slot, {b.id: writer.budget(b) for b in over_slot})
            apply(changed, "Compressed {slot} to its planned line budget.")
            if changed:
                continue
        if m.fits:
            return document, rendered, m, log
        covers = {b.id: {r: STRENGTH_VALUE[s] for r, s in coverage.get(b.project_id, {}).items()} for b in bullets.values()}
        if summary is not None:
            covers["summary"] = {r["id"]: STRENGTH_VALUE[r["strength"]] for r in trace.bullet_requirements(summary, jd, store, retrieval)}
        options = _removals(bullets, summary, skills, m, covers, weight, scores, jd, spec)
        cheapest = min(options, key=lambda o: (o.per_line, o.loss, o.rank, o.key)) if options else None
        if cheapest is None or cheapest.loss > LOW_VALUE:
            if rounds < COMPRESS_ROUNDS and session.llm.configured:
                rounds += 1
                candidates = sorted((b for b in everything if not b.locked and m.lines.get(b.id, 0) > 1),
                                    key=lambda b: (m.last_fill.get(b.id, 1), b.id))
                picks = candidates[:max(m.overflow_lines, 1) + 1]
                changed = session.compress(picks, {b.id: m.lines[b.id] - 1 for b in picks})
                apply(changed, "Compressed {slot} by one line: everything left on the page carries JD coverage.")
                if changed:
                    continue
        if cheapest is None:
            log.append("Could not fit one page without removing locked content. Unlock or exclude something.")
            return document, rendered, m, log
        over = f"{m.overflow_lines} line(s) over, coverage loss {cheapest.loss:.2f}"
        if cheapest.kind == "summary":
            summary = None
            log.append(f"Removed the summary to fit one page ({over}).")
        elif cheapest.kind == "skills":
            labels = {l["group"]: l["label"] for l in spec["slots"]["skills"]["lines"]}
            kept = fit_skill_items(labels[cheapest.key], skills[cheapest.key], m.lines[f"skills:{cheapest.key}"] - 1, spec)
            log.append(f"Trimmed {cheapest.key} skills to {len(kept)} items, dropping the least JD-relevant ({over}).")
            skills[cheapest.key] = kept
        else:
            dropped = bullets.pop(cheapest.key)
            log.append(f"Removed {_section_name(dropped.employment_id)} bullet {cheapest.key}, the lowest JD value per "
                       f"line ({over}).")
    return document, rendered, m, log


def _measurer(spec: dict[str, Any]):
    try:
        return WordMeasurer(spec)
    except ConverterUnavailable as exc:
        raise CompilerUnavailable(str(exc)) from exc


def _bullet_regions(pdf: bytes, rendered: Rendered) -> dict[str, Any]:
    """Where each paragraph sits on page one of the PDF, in PDF points, so the UI can draw over the preview."""
    try:
        rows, _, (width, height) = pdf_rows(pdf)
        owned = match_blocks(rendered.blocks, rows)
    except Exception:  # noqa: BLE001 - overlays are decoration; the resume itself is unaffected
        return {"page": [], "bullets": {}}
    bullets = {}
    for key, lines in owned.items():
        first = [r for r in lines if r.page == 1 and r.x0 < 1e9]
        if first:
            bullets[key] = [round(min(r.x0 for r in first), 1), round(min(r.y0 for r in first), 1),
                            round(max(r.x1 for r in first), 1), round(max(r.y1 for r in first), 1)]
    return {"page": [0, 0, round(width, 1), round(height, 1)], "bullets": bullets}


def generate(*, jd: JobDescription | None = None, jd_id: str = "", plan: ResumePlan, bullets: list[Bullet] | None = None,
             regenerate: list[str] | None = None, store: CareerStore | None = None, llm: DeepSeekClient | None = None,
             spec: dict[str, Any] | None = None, golden: bytes | None = None, measurer=None,
             save_version: bool = True) -> dict[str, Any]:
    """`regenerate=None` rewrites every unlocked bullet; a list rewrites only those slot ids and keeps the rest."""
    store = store or load_store()
    llm = llm or DeepSeekClient()
    spec = spec or load_spec()
    golden = golden or load_golden()
    stages = Stages()
    jd = jd or load_jd(jd_id)
    if not any(r.query_terms or r.adjacent_terms for r in jd.requirements):
        jd = apply_query(jd, load_query(jd))
    # Evidence a locked bullet cites stays usable: locks outrank earlier exclusions.
    excluded = feedback.excluded_evidence(jd.id) - {i for b in bullets or [] if b.locked for i in b.evidence_ids}
    plan_warnings: list[str] = []
    selected = _check_plan(plan, store, excluded, plan_warnings)
    planned = {p.project_id: p for p in selected}
    with stages.stage("retrieveEvidence") as record:
        retrieval = retrieve_evidence(jd, store, excluded=excluded)
        record["candidates"] = len(retrieval.projects)
    session = Session(store, llm, spec, {p.project_id: _slot_allowed(store, p, excluded) for p in selected},
                      {p.project_id: p.lines for p in selected})
    session.warnings += plan_warnings
    rewrite = None if regenerate is None else set(regenerate)
    debug: dict[str, dict[str, Any]] = {}

    kept: dict[str, Bullet] = {}
    summary: Bullet | None = None
    for bullet in bullets or []:
        if bullet.id != "summary" and bullet.project_id not in planned:
            continue
        keep = bullet.locked or (rewrite is not None and bullet.id not in rewrite)
        if not keep:
            continue
        issues = session.validate(bullet)
        if issues:
            session.warnings.append(f"Kept bullet {bullet.id} no longer validates ({issues[0].code}) and was rewritten.")
            continue
        clean = bullet.model_copy(update={"requirements": [], "lint": []})
        if bullet.id == "summary":
            summary = clean
        else:
            kept[bullet.project_id] = clean
        debug[bullet.id] = {"source": "locked" if bullet.locked else "kept", "issues": []}

    todo = [p for p in selected if p.project_id not in kept]
    want_summary = plan.section_budget.summary > 0 and summary is None and (rewrite is None or "summary" in rewrite)
    fresh: set[str] = set()
    preferences: list[dict] = []
    write_stage = stages.stage("generateResumeContent")
    write_record = write_stage.__enter__()
    if todo or want_summary:
        if not llm.configured:
            raise CompilerUnavailable("DEEPSEEK_API_KEY is not set on the API server, so new bullets cannot be written.")
        slots = {p.project_id: _slot(store, p, jd, session.writer, session.allowed[p.project_id]) for p in todo}
        summary_slot = _summary_slot(store, selected, session.writer) if want_summary else None
        preferences = feedback.preference_examples(jd, [p.project_id for p in todo])
        errors: dict[str, list[ValidationIssue]] = {}
        pending, summary_pending = set(slots), want_summary
        drafts: dict[str, str] = {}
        for round_no in range(REPAIR_ROUNDS + 1):
            payload = prompts.write_user([slots[k] for k in sorted(pending)], style=store.writing_style, exemplars=session.exemplars,
                                         guardrails=retrieval.guardrails, conflicts=retrieval.conflicts,
                                         locked=[b.text for b in kept.values()], summary=summary_slot if summary_pending else None,
                                         target_role=plan.target_role or jd.title, preferences=preferences,
                                         themes=plan.primary_themes)
            if errors:
                payload["validation_errors"] = {k: [e.model_dump(include={"code", "message", "claim", "allowed_evidence"})
                                                    for e in v] for k, v in errors.items()}
                payload["rejected_drafts"] = {k: v for k, v in drafts.items() if k in errors}
            try:
                written, meta = llm.complete_json(task="repair_bullets" if errors else "write_bullets",
                                                  system=prompts.REPAIR_SYSTEM if errors else prompts.WRITE_SYSTEM,
                                                  user=payload, schema=_WriteResponse, max_tokens=3000, temperature=.3)
            except DeepSeekError as exc:
                if round_no == 0:
                    raise CompilerUnavailable(f"DeepSeek could not write the resume: {exc}") from exc
                session.warnings.append(f"Repair round {round_no} failed: {exc}")
                break
            session.calls.append(meta)
            write_record["calls"].append(meta)
            errors = {}
            returned = {w.slot_id: w for w in written.bullets if w.slot_id in pending}
            for slot_id in sorted(pending):
                item = returned.get(slot_id)
                project = store.projects[slot_id]
                bullet = Bullet(id=slot_id, employment_id=project.employment_id, project_id=slot_id,
                                name=project.name if project.personal else "",
                                text=(item.text if item else "").strip(), evidence_ids=item.evidence_ids if item else [])
                issues = session.validate(bullet) or (session.over_budget(bullet) if round_no < REPAIR_ROUNDS else [])
                entry = debug.setdefault(slot_id, {"rejected": []})
                entry.update({"source": "write" if round_no == 0 else f"repair {round_no}", "issues": [i.model_dump() for i in issues]})
                if issues:
                    errors[slot_id] = issues
                    drafts[slot_id] = bullet.text
                    entry["rejected"].append({"text": bullet.text, "issues": [i.code for i in issues]})
                else:
                    kept[slot_id] = bullet
                    fresh.add(slot_id)
            if summary_pending:
                candidate = Bullet(id="summary", employment_id="", project_id="",
                                   text=written.summary.text.strip() if written.summary else "",
                                   evidence_ids=written.summary.evidence_ids if written.summary else [])
                issues = session.validate(candidate) or (session.over_budget(candidate) if round_no < REPAIR_ROUNDS else [])
                debug["summary"] = {"source": "write" if round_no == 0 else f"repair {round_no}", "issues": [i.model_dump() for i in issues]}
                if issues:
                    errors["summary"] = issues
                    drafts["summary"] = candidate.text
                else:
                    summary, summary_pending = candidate, False
                    fresh.add("summary")
            session.counters["validation_failures"] += sum(len(v) for v in errors.values())
            pending = set(errors) - {"summary"}
            if not errors:
                break
        for slot_id, issues in errors.items():
            session.warnings.append(f"Dropped {slot_id}: still invalid after {REPAIR_ROUNDS} repairs "
                                    f"({'; '.join(f'{i.code}: {i.message}' for i in issues[:2])}).")
    write_record.update({"written": len(fresh), "validation_failures": session.counters["validation_failures"],
                         "preference_examples": len(preferences)})
    write_stage.__exit__(None, None, None)

    def requirements_of(b: Bullet) -> Bullet:
        return b.model_copy(update={"requirements": trace.bullet_requirements(b, jd, store, retrieval)})

    with stages.stage("critiqueResumeStyle") as record:
        everything = list(kept.values()) + ([summary] if summary else [])
        critiques, critic_meta, critic_warnings = critic.critique_resume_style(
            [requirements_of(b) for b in everything], jd, llm, session.exemplars)
        record["calls"].append(critic_meta)
        session.calls += [critic_meta] if critic_meta else []
        session.warnings += critic_warnings
        combined = critic.combine(style.lint(everything), critiques)
        restyle = [b for b in everything if b.id in fresh and not b.locked and combined[b.id]["rewrite"]]
        before = len(session.calls)
        restyled = session.restyle(restyle, {b.id: combined[b.id]["issues"] for b in restyle})
        record["calls"] += session.calls[before:]
        record.update({"flagged": len(restyle), "restyled": len(restyled)})
        for slot_id, new in restyled.items():
            debug.setdefault(slot_id, {"issues": []})["restyled_from"] = (summary if slot_id == "summary" else kept[slot_id]).text
            if slot_id == "summary":
                summary = new
            else:
                kept[slot_id] = new
    critiqued = {b.id: b.text for b in everything}

    skills = _skills(store, selected, jd, spec)
    measurer = measurer or _measurer(spec)
    with stages.stage("fitResumeToPageBudget") as record:
        before = len(session.calls)
        document, rendered, measured, fit_log = fit_to_page(session, jd, selected, kept, summary, skills, retrieval,
                                                            measurer, golden, fresh)
        record["calls"] += session.calls[before:]
        record.update({"iterations": session.counters["page_fit_iterations"], "pages": measured.pages,
                       "lines_used": measured.total_lines})
    final = ([document.summary] if document.summary else []) + document.bullets()
    changed = [requirements_of(b) for b in final if critiqued.get(b.id) != b.text and not b.locked]
    if changed and critiques:
        with stages.stage("critiqueResumeStyle:final") as record:
            again, meta, _ = critic.critique_resume_style(changed, jd, llm, session.exemplars)
            record["calls"].append(meta)
            session.calls += [meta] if meta else []
            critiques = {**critiques, **again}
    # A critique only describes the text it read: drop it for bullets compressed afterwards and not re-read.
    final_text = {b.id: b.text for b in final}
    recritiqued = {c.id for c in changed}
    current = {k: v for k, v in critiques.items() if k in final_text and (critiqued.get(k) == final_text[k] or k in recritiqued)}
    style_report = critic.combine(style.lint(final), current)
    annotate = lambda b: b.model_copy(update={"requirements": trace.bullet_requirements(b, jd, store, retrieval),
                                              "lint": style_report.get(b.id, {}).get("issues", [])})
    document = document.model_copy(update={
        "summary": annotate(document.summary) if document.summary else None,
        "sections": [s.model_copy(update={"bullets": [annotate(b) for b in s.bullets]}) for s in document.sections],
        "featured": [annotate(b) for b in document.featured]})
    with stages.stage("validateResumeClaims") as record:
        final_issues = [i for b in ([document.summary] if document.summary else []) + document.bullets() for i in session.validate(b)]
        record["validation_failures"] = len(final_issues)
    with stages.stage("renderResume"):
        drift = formatting_drift(render_docx(document, spec, golden).docx, golden)
    report = trace.report(jd, retrieval, store, plan=plan, document=document)
    evaluation = scoring.evaluate(document=document, jd=jd, retrieval=retrieval, store=store, trace_rows=report["requirements"],
                                  allowed=session.allowed, pages=measured.pages, drift=drift,
                                  style_scores={k: v["style_score"] for k, v in style_report.items()},
                                  feedback=feedback.stats(jd.id))
    model = llm.model if llm.configured else ""
    version_info = None
    if save_version:
        with stages.stage("exportResume") as record:
            try:
                version = versions.create_version(document, jd, store, measurer=measurer, spec=spec, golden=golden, meta={
                    "model": model, "prompt_versions": prompts.PROMPT_VERSIONS, "retrieval_version": RETRIEVAL_VERSION,
                    "query_version": QUERY_VERSION,
                    "eval_scores": {k: v for k, v in evaluation.items() if not isinstance(v, (list, dict))}})
                version_info = {**version.model_dump(), "blocking": versions.blocking_reasons(version)}
                record.update({"resume_id": version.resume_id, "pdf_checks": version.pdf_checks.get("passed")})
            except (ConverterUnavailable, OSError, RuntimeError) as exc:
                session.warnings.append(f"Could not store this resume version: {exc}")
    for item in stages.items:
        if item["stage"] == "generateResumeContent":
            item["rewrites"] = session.counters["rewrites"]
    rows = []
    for bullet in ([document.summary] if document.summary else []) + document.bullets():
        project = store.projects.get(bullet.project_id)
        rows.append({"bullet_id": bullet.id, "text": bullet.text, "evidence_ids": bullet.evidence_ids,
                     "project": project.name if project else "Summary",
                     "company": (project.company or "Personal project") if project else "",
                     "locked": bullet.locked, "requirements": bullet.requirements, "lint": bullet.lint,
                     "lines": measured.lines.get(bullet.id), "line_budget": session.writer.budget(bullet),
                     "evidence": [store.evidence[i].brief() for i in bullet.evidence_ids if i in store.evidence],
                     "style_score": style_report.get(bullet.id, {}).get("style_score"),
                     "style_source": style_report.get(bullet.id, {}).get("source"),
                     **{"source": "kept", "issues": [], **debug.get(bullet.id, {})}})
    # The preview is the stored version's own PDF when there is one, so what you see is what downloads.
    pdf = measured.pdf
    if version_info and version_info.get("pdf_sha256"):
        pdf = (versions.root() / version_info["resume_id"] / "resume.pdf").read_bytes()
    page_count = measured.pages
    pages = [preview_png(pdf, page) for page in range(page_count)] if pdf else []
    regions = _bullet_regions(pdf, rendered) if pdf else {"page": [], "bullets": {}}
    section_lines: dict[str, int] = {}
    for block in rendered.blocks:
        section_lines[block.kind] = section_lines.get(block.kind, 0) + measured.lines.get(block.key, 1)
    pdf_ok = not version_info or not version_info.get("pdf_sha256") or version_info["pdf_checks"].get("passed", False)
    return {"document": document.model_dump(), "jd_id": jd.id, "trace": report,
            "valid": not final_issues and measured.fits and not drift and pdf_ok,
            "issues": [i.model_dump() for i in final_issues],
            "layout": {**measured.summary(), "template_drift": drift, "section_lines": section_lines,
                       "section_budget": plan.section_budget.model_dump(),
                       "template": {"file": spec["golden"]["file"], "sha256": spec["golden"]["sha256"]},
                       "regions": regions},
            "pages": measured.pages,
            "preview": ("data:image/png;base64," + base64.b64encode(pages[0]).decode()) if pages else "",
            "previews": ["data:image/png;base64," + base64.b64encode(p).decode() for p in pages],
            "evaluation": evaluation, "resume_version": version_info, "stages": stages.items,
            "versions": {"retrieval": RETRIEVAL_VERSION, "query": QUERY_VERSION, "prompts": prompts.PROMPT_VERSIONS,
                         "model": model, "template": template_digest(spec)},
            "warnings": session.warnings, "fit_log": fit_log, "debug": rows, "deepseek": session.calls}
