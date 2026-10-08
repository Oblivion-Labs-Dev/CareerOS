"""Stage 3 (buildEvidenceQuery): DeepSeek describes the evidence each requirement needs; Career OS runs the query.

DeepSeek sees the requirements and career.json's vocabulary (technology, concept and tag names, never claims) and maps
each requirement onto that vocabulary. The result is sanitised here and cached next to jd.json, so the same JD,
career.json and query version always produce the same retrieval.
"""
from __future__ import annotations

import logging
from pathlib import Path

from pydantic import BaseModel, Field

from app.services.career_compiler import prompts
from app.services.career_compiler.deepseek import DeepSeekClient, DeepSeekError
from app.services.career_compiler.jobs import cache_dir
from app.services.career_compiler.lexicon import mentions_tech, named_technology
from app.services.career_compiler.models import EvidenceQuery, JobDescription, RequirementQuery
from app.services.career_compiler.store import CareerStore

logger = logging.getLogger("careeros.career_compiler")
QUERY_VERSION = "evidence-query-v1"
MAX_TERMS = 6


class _RawQuery(BaseModel):
    requirements: list[RequirementQuery] = Field(default_factory=list)


def vocabulary(store: CareerStore) -> dict[str, list[str]]:
    tags = sorted({t for e in store.evidence.values() for t in e.tags if t}, key=str.casefold)
    types = sorted({e.type for e in store.evidence.values() if e.type and e.status != "guardrail"})
    return {"technologies": sorted(store.technologies, key=str.casefold), "concepts": sorted(store.concepts, key=str.casefold),
            "tags": tags, "evidence_types": types}


def _path(jd_id: str) -> Path:
    return cache_dir() / f"{jd_id}.query.json"


def load_query(jd: JobDescription) -> EvidenceQuery | None:
    path = _path(jd.id)
    if not path.is_file():
        return None
    query = EvidenceQuery.model_validate_json(path.read_text(encoding="utf-8"))
    return query if query.version == QUERY_VERSION and query.jd_id == jd.id else None


def sanitize(raw: list[RequirementQuery], jd: JobDescription, store: CareerStore) -> EvidenceQuery:
    """Keep only career.json vocabulary. A named technology the requirement does not itself mention can never be
    an equivalent: Kinesis is adjacent to a Kafka requirement, not a substitute for it."""
    vocab = vocabulary(store)
    canonical = {t.casefold(): t for group in ("technologies", "concepts", "tags") for t in vocab[group]}
    types = set(vocab["evidence_types"])
    by_id = {q.requirement_id: q for q in raw}
    dropped: list[str] = []
    out = []
    for req in jd.requirements:
        item = by_id.get(req.id)
        if item is None:
            continue
        wording = f"{req.original_text} {req.normalized_requirement}"
        terms: list[str] = []
        adjacent: list[str] = []
        for value in item.terms:
            term = canonical.get(value.strip().casefold())
            if term is None:
                dropped.append(value)
            elif named_technology(term) and not mentions_tech(wording, term):
                adjacent.append(term)
            else:
                terms.append(term)
        for value in item.adjacent:
            term = canonical.get(value.strip().casefold())
            if term is None:
                dropped.append(value)
            else:
                adjacent.append(term)
        terms = list(dict.fromkeys(terms))[:MAX_TERMS]
        adjacent = [t for t in dict.fromkeys(adjacent) if t not in terms][:MAX_TERMS]
        if terms or adjacent:
            out.append(RequirementQuery(requirement_id=req.id, terms=terms, adjacent=adjacent,
                                        evidence_types=sorted({t for t in item.evidence_types if t in types})))
    return EvidenceQuery(jd_id=jd.id, version=QUERY_VERSION, source="deepseek", requirements=out,
                         dropped_terms=sorted(set(dropped), key=str.casefold)[:40])


def build_evidence_query(jd: JobDescription, store: CareerStore, llm: DeepSeekClient, *, refresh: bool = False
                         ) -> tuple[EvidenceQuery, list[str], dict]:
    cached = None if refresh else load_query(jd)
    if cached is not None:
        return cached, [], {}
    if not llm.configured:
        return EvidenceQuery(jd_id=jd.id, version=QUERY_VERSION), [], {}
    try:
        raw, meta = llm.complete_json(task="build_evidence_query", system=prompts.QUERY_SYSTEM,
                                      user=prompts.query_user(jd, vocabulary(store)), schema=_RawQuery, max_tokens=3000,
                                      temperature=0.0)
    except DeepSeekError as exc:
        logger.warning("Evidence query fell back to requirement skills only: %s", exc.code)
        return EvidenceQuery(jd_id=jd.id, version=QUERY_VERSION), [f"DeepSeek evidence query unavailable ({exc}). "
                                                                   "Retrieved with requirement skills only."], {}
    query = sanitize(raw.requirements, jd, store)
    path = _path(jd.id)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(query.model_dump_json(indent=2), encoding="utf-8")
    return query, [], meta


def apply_query(jd: JobDescription, query: EvidenceQuery | None) -> JobDescription:
    if query is None or not query.requirements:
        return jd
    by_id = {q.requirement_id: q for q in query.requirements}
    return jd.model_copy(update={"requirements": [
        r.model_copy(update={"query_terms": by_id[r.id].terms, "adjacent_terms": by_id[r.id].adjacent}) if r.id in by_id else r
        for r in jd.requirements]})
