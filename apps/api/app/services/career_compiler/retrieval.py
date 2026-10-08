"""Stages 3-5: match structured JD requirements to career evidence, deterministically; let DeepSeek rank."""
from __future__ import annotations

import logging
from functools import lru_cache

from app.services.career_compiler import prompts
from app.services.career_compiler.deepseek import DeepSeekClient, DeepSeekError
from app.services.career_compiler.lexicon import mentions_tech, technologies
from app.services.career_compiler.models import (
    Candidate, EvidenceMatch, JobDescription, ProjectCandidate, RankedProject, Ranking, Requirement, Retrieval,
)
from app.services.career_compiler.career_signal import career_signal
from app.services.career_compiler.store import EXISTENCE_ONLY, CareerStore, Evidence, Project, mentions, tokens
from app.services.career_compiler.weights import requirement_weight

logger = logging.getLogger("careeros.career_compiler")
#: Bump when matching or ordering changes: same JD + query + career.json + version gives the same candidate set.
RETRIEVAL_VERSION = "retrieval-v4"
STRENGTH_VALUE = {"strong": 1.0, "moderate": .6, "weak": .25}
STRENGTH_ORDER = {"strong": 0, "moderate": 1, "weak": 2}
WEIGHT = {"high": 3, "medium": 2, "low": 1}
TYPE_BONUS = {"metric": .3, "scale": .3, "ownership": .2, "decision": .2, "architecture": .2}
PER_EMPLOYER = {"employment.microsoft": 6, "employment.amazon": 9, "personal": 2}
EVIDENCE_PER_PROJECT = 5
MATCHES_PER_REQUIREMENT = 6
STOP = set("""a an and are as at be by for from in into is it of on or our the to we with you your will who what
experience experiences years year ability able strong excellent good great knowledge understanding familiarity
proficiency work working team teams using use build building develop developing role including such other across
plus preferred required requirement requirements must including etc new well within highly skills skill""".split())


def keywords(req: Requirement) -> set[str]:
    return {w for w in tokens(req.normalized_requirement + " " + req.original_text) if w not in STOP and len(w) > 2}


def _project_text(project: Project) -> str:
    return " ".join((project.name, project.summary, *project.technologies, *project.details, *project.ownership))


def _hits(terms: list[str], text: str, words: set[str]) -> list[str]:
    return [s for s in terms if mentions(text, s) or (tokens(s) and tokens(s) <= words)]


@lru_cache(maxsize=4096)
def named_in(text: str) -> tuple[str, ...]:
    return tuple(t for t in technologies() if mentions_tech(text, t))


def evidence_strength(req: Requirement, ev: Evidence, store: CareerStore) -> tuple[str | None, float, list[str]]:
    """How well one evidence record supports one requirement. Pure function of the two records and the
    requirement's query terms: equivalent terms count like the requirement's own skills, adjacent terms only
    ever give a weak match."""
    skills = list(dict.fromkeys([*req.skills, *req.query_terms]))
    claim_text = ev.claim + " " + " ".join(ev.tags)
    claim_words = tokens(claim_text)
    claim_hits = _hits(skills, ev.claim, claim_words)
    context_hits: list[str] = []
    project_text, project_words = "", set()
    if ev.project_id and ev.status not in EXISTENCE_ONLY:
        project_text = _project_text(store.projects[ev.project_id])
        project_words = tokens(project_text)
        context_hits = [s for s in _hits(skills, project_text, project_words) if s not in claim_hits]
    words = keywords(req)
    shared = sorted(words & claim_words)
    ratio = len(shared) / len(words) if words else 0
    score = round(3 * len(claim_hits) + 1.5 * len(context_hits) + 4 * ratio + (TYPE_BONUS.get(ev.type, 0) if shared or claim_hits else 0), 3)
    matched = claim_hits + context_hits + [w for w in shared if w not in {c.casefold() for c in claim_hits}]
    if ev.status in EXISTENCE_ONLY:
        return ("weak" if claim_hits or len(shared) >= 2 else None), score, matched
    # A requirement naming a technology the evidence never mentions ("Kafka") is not met by query expansion alone
    # ("Event-Driven Architecture" on a Kinesis project): that is at most adjacent.
    named = named_in(req.original_text)
    if (named and (claim_hits or context_hits) and not set(req.skills) & {*claim_hits, *context_hits}
            and not any(mentions_tech(claim_text + " " + project_text, t) for t in named)):
        return "weak", score, [f"~{m}" for m in matched]
    # A requirement that names skills needs one of them; shared ordinary words ("data", "loss") are only weak.
    direct = bool(claim_hits) if skills else (len(shared) >= 3 and ratio >= .3)
    if direct:
        return ("strong" if ev.status == "supported" else "moderate"), score, matched
    if context_hits:
        return ("moderate" if len(context_hits) * 2 >= len(skills) else "weak"), score, matched
    if len(shared) >= (3 if skills else 2) and ratio >= .2:
        return ("moderate" if not skills and ratio >= .25 else "weak"), score, matched
    adjacent = _hits(req.adjacent_terms, claim_text, claim_words) or _hits(req.adjacent_terms, project_text, project_words)
    if adjacent:
        return "weak", round(score + .5 * len(adjacent), 3), matched + [f"~{a}" for a in adjacent]
    return None, score, matched


def retrieve_evidence(jd: JobDescription, store: CareerStore, *, excluded: set[str] | frozenset[str] = frozenset()
                      ) -> Retrieval:
    """Bounded, deterministic candidate set. `excluded` evidence (user exclusions and rejections) is never offered."""
    matches: dict[str, list[EvidenceMatch]] = {r.id: [] for r in jd.requirements}
    candidates: list[ProjectCandidate] = []
    weight = {r.id: requirement_weight(r) for r in jd.requirements}
    for project in sorted(store.projects.values(), key=lambda p: p.id):
        coverage: dict[str, str] = {}
        usable, blocked = [], []
        for ev in store.project_evidence(project.id):
            if ev.status == "guardrail" or ev.id in excluded:
                continue
            hits, total = [], 0.0
            for req in jd.requirements:
                strength, score, matched = evidence_strength(req, ev, store)
                if not strength:
                    continue
                hits.append(req.id)
                total += weight[req.id] * STRENGTH_VALUE[strength]
                if ev.status == "needs_reconciliation":
                    continue
                if req.id not in coverage or STRENGTH_ORDER[strength] < STRENGTH_ORDER[coverage[req.id]]:
                    coverage[req.id] = strength
                matches[req.id].append(EvidenceMatch(
                    requirement_id=req.id, evidence_id=ev.id, project_id=project.id, company=project.company or "Personal project",
                    status=ev.status, claim=ev.claim, strength=strength, score=score, matched=matched[:6]))
            candidate = Candidate(evidence_id=ev.id, type=ev.type, status=ev.status, claim=ev.claim,
                                  score=round(total + TYPE_BONUS.get(ev.type, 0), 3), requirement_ids=hits)
            if ev.status == "needs_reconciliation":
                blocked.append(candidate)
            elif ev.usable or ev.status in EXISTENCE_ONLY:
                usable.append(candidate)
        if not usable:
            continue
        usable.sort(key=lambda c: (-c.score, c.evidence_id))
        existence_only = all(c.status in EXISTENCE_ONLY for c in usable)
        score = sum(weight[r] * STRENGTH_VALUE[s] for r, s in coverage.items()) + .01 * min(len(usable), 5)
        candidates.append(ProjectCandidate(
            project_id=project.id, name=project.name, company=project.company, employment_id=project.employment_id,
            score=round(score * (.3 if existence_only else 1), 3), coverage=dict(sorted(coverage.items(), key=lambda kv: int(kv[0][1:]))),
            existence_only=existence_only, evidence=usable[:EVIDENCE_PER_PROJECT], blocked=blocked))
    # JD coverage orders the bounded set; projects with no coverage compete on career signal for what is left, so
    # the planner can fill spare page space with the strongest of them.
    candidates.sort(key=lambda p: (-p.score if p.coverage else 0.0,
                                   0.0 if p.coverage else -career_signal(store, p.project_id).score, p.project_id))
    kept, per_employer = [], {}
    for candidate in candidates:
        count = per_employer.get(candidate.employment_id, 0)
        if count < PER_EMPLOYER.get(candidate.employment_id, 2):
            per_employer[candidate.employment_id] = count + 1
            kept.append(candidate)
    for req_id, found in matches.items():
        found.sort(key=lambda m: (STRENGTH_ORDER[m.strength], -m.score, m.evidence_id))
        per_project: dict[str, int] = {}
        trimmed = []
        for match in found:
            if per_project.get(match.project_id, 0) < 2:
                per_project[match.project_id] = per_project.get(match.project_id, 0) + 1
                trimmed.append(match)
        matches[req_id] = trimmed[:MATCHES_PER_REQUIREMENT]
    companies = {store.employment[c.employment_id]["company"].casefold().split()[0]
                 for c in kept if c.employment_id in store.employment}
    conflicts = [c for c in store.conflicts if str(c.get("id", "")).split(".")[1:2] and
                 str(c["id"]).split(".")[1] in companies]
    guardrails = [e.claim for e in store.evidence.values() if e.status == "guardrail"]
    return Retrieval(projects=kept, matches=matches, guardrails=guardrails, conflicts=conflicts, store_digest=store.digest,
                     version=RETRIEVAL_VERSION, excluded=sorted(excluded))


def coverage_reason(candidate: ProjectCandidate) -> str:
    if not candidate.coverage:
        return "No direct requirement match; strongest available evidence for this role."
    parts = [f"{r} ({s})" for r, s in sorted(candidate.coverage.items(), key=lambda kv: (STRENGTH_ORDER[kv[1]], int(kv[0][1:])))]
    return "Covers " + ", ".join(parts[:5]) + ("…" if len(parts) > 5 else "")


def _deterministic_ranking(retrieval: Retrieval) -> Ranking:
    return Ranking(source="deterministic", projects=[
        RankedProject(project_id=p.project_id, score=p.score, reason=coverage_reason(p),
                      evidence_ids=[c.evidence_id for c in p.evidence[:3]]) for p in retrieval.projects])


def rank_evidence(jd: JobDescription, retrieval: Retrieval, llm: DeepSeekClient) -> tuple[Ranking, list[str], dict]:
    """DeepSeek reasons over the retrieved set only; IDs it returns are re-checked."""
    fallback = _deterministic_ranking(retrieval)
    if not llm.configured or not retrieval.projects:
        return fallback, [], {}
    try:
        ranking, meta = llm.complete_json(task="rank_evidence", system=prompts.RANK_SYSTEM,
                                          user=prompts.rank_user(jd, retrieval), schema=Ranking, max_tokens=2500)
    except DeepSeekError as exc:
        logger.warning("Ranking fell back to deterministic: %s", exc.code)
        return fallback, [f"DeepSeek ranking unavailable ({exc}). Used coverage order."], {}
    by_id = {p.project_id: p for p in retrieval.projects}
    kept: list[RankedProject] = []
    for item in ranking.projects:
        candidate = by_id.get(item.project_id)
        if not candidate or any(k.project_id == item.project_id for k in kept):
            continue
        allowed = {c.evidence_id for c in candidate.evidence}
        ids = [i for i in item.evidence_ids if i in allowed] or [c.evidence_id for c in candidate.evidence[:3]]
        kept.append(RankedProject(project_id=item.project_id, score=item.score, reason=item.reason[:300], evidence_ids=ids))
    for item in fallback.projects:
        if not any(k.project_id == item.project_id for k in kept):
            kept.append(item.model_copy(update={"score": 0}))
    themes = [t.strip()[:60] for t in ranking.primary_themes if t.strip()][:5]
    return Ranking(projects=kept, source="deepseek", target_role=ranking.target_role.strip()[:120],
                   primary_themes=themes), [], meta
