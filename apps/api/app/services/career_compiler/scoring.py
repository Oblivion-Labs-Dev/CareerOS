"""Stage 12: deterministic resume metrics. No LLM is involved; the same inputs always give the same numbers.

Recall is weighted only over requirements career.json can actually support (best available evidence strong or
moderate): a requirement with no supported evidence is a skill gap, not a resume failure.
"""
from __future__ import annotations

from typing import Any

from app.services.career_compiler.lexicon import mentions_tech, technologies
from app.services.career_compiler.models import Bullet, JobDescription, ResumeDocument, Retrieval
from app.services.career_compiler.store import CareerStore, tokens
from app.services.career_compiler.validator import numbers, validate_bullet
from app.services.career_compiler.weights import requirement_class, requirement_weight, weights

SUFFICIENT = ("strong", "moderate")
TOP_N = 5
REDUNDANT_OVERLAP = .5
EVIDENCE_CODES = {"missing_evidence", "unknown_evidence", "evidence_not_allowed", "wrong_company", "unresolved_conflict"}
METRIC_CODES = {"unsupported_metric", "unsupported_experience"}
OTHER_CODES = {"unsupported_title", "unsupported_scale", "unsupported_ownership", "sparse_detail", "date_mismatch"}
STOP = set("a an and the of for to in on with by from at as into across over under via its their".split())


def _validate(bullet: Bullet, store: CareerStore, allowed: dict[str, set[str]]):
    if bullet.id == "summary":
        return validate_bullet(bullet, store, summary=True)
    return validate_bullet(bullet, store, allowed=allowed.get(bullet.project_id))


def claim_precision(bullets: list[Bullet], store: CareerStore, allowed: dict[str, set[str]]) -> dict[str, Any]:
    """Atomic claims per bullet: each quantity, each named technology, each title/scale/ownership word, plus the
    bullet's own statement (supported when its evidence chain is valid)."""
    known = technologies(store.technologies)
    totals = {"metric": [0, 0], "technology": [0, 0], "other": [0, 0]}
    traced = leaks = 0
    for b in bullets:
        issues = _validate(b, store, allowed)
        codes = [i.code for i in issues]
        quantities = len(numbers(b.text))
        techs = sum(1 for t in known if mentions_tech(b.text, t))
        totals["metric"][0] += quantities
        totals["metric"][1] += min(quantities, sum(c in METRIC_CODES for c in codes))
        totals["technology"][0] += techs
        totals["technology"][1] += min(techs, codes.count("unsupported_technology"))
        others = sum(c in OTHER_CODES for c in codes)
        totals["other"][0] += 1 + others
        totals["other"][1] += others + (1 if any(c in EVIDENCE_CODES for c in codes) else 0)
        traced += 1 if b.evidence_ids and not any(c in EVIDENCE_CODES for c in codes) else 0
        leaks += codes.count("unresolved_conflict") + sum(
            1 for i in b.evidence_ids if i in store.evidence and store.evidence[i].status == "needs_reconciliation")
    claims = sum(t[0] for t in totals.values())
    failed = sum(t[1] for t in totals.values())

    def ratio(pair: list[int]) -> float | None:
        return round((pair[0] - pair[1]) / pair[0], 4) if pair[0] else None

    return {"factual_precision": round((claims - failed) / claims, 4) if claims else None,
            "metric_precision": ratio(totals["metric"]), "technology_precision": ratio(totals["technology"]),
            "traceability": round(traced / len(bullets), 4) if bullets else None, "conflict_leakage": leaks,
            "claims": claims, "unsupported_claims": failed}


def _content_words(text: str) -> set[str]:
    return {w for w in tokens(text) if w not in STOP and len(w) > 2}


def redundancy(bullets: list[Bullet]) -> tuple[float | None, list[list[str]]]:
    pairs, flagged = [], set()
    items = [b for b in bullets if b.id != "summary"]
    for i, a in enumerate(items):
        for b in items[i + 1:]:
            wa, wb = _content_words(a.text), _content_words(b.text)
            overlap = len(wa & wb) / len(wa | wb) if wa | wb else 0
            if overlap >= REDUNDANT_OVERLAP or (a.evidence_ids and set(a.evidence_ids) == set(b.evidence_ids)):
                pairs.append([a.id, b.id])
                flagged.add(b.id)
    return (round(len(flagged) / len(items), 4) if items else None), pairs


def requirement_metrics(jd: JobDescription, trace_rows: list[dict], retrieval: Retrieval,
                        document: ResumeDocument) -> dict[str, Any]:
    rows = {r["id"]: r for r in trace_rows}
    by_id = {r.id: r for r in jd.requirements}
    supported = [r for r in jd.requirements if rows.get(r.id, {}).get("best_available") in SUFFICIENT]
    covered = {r.id for r in supported if rows[r.id].get("resume_strength") in SUFFICIENT}
    total = sum(requirement_weight(r) for r in supported)
    recall = round(sum(requirement_weight(r) for r in supported if r.id in covered) / total, 4) if total else None
    top = sorted(supported, key=lambda r: (-requirement_weight(r), int(r.id[1:])))[:TOP_N]
    on_page = {b.project_id for b in document.bullets()}
    used = 0
    for r in supported:
        best = (retrieval.matches.get(r.id) or [None])[0]
        if best is None or best.project_id in on_page or rows[r.id].get("resume_strength") in SUFFICIENT:
            used += 1
    unused = [r.id for r in supported if r.id not in covered]
    gaps = [r.id for r in jd.requirements if rows.get(r.id, {}).get("best_available") not in SUFFICIENT]
    return {
        "supported_jd_recall": recall,
        "top_requirement_coverage": round(sum(1 for r in top if r.id in covered) / len(top), 4) if top else None,
        "top_requirements": [r.id for r in top],
        "evidence_utilization": round(used / len(supported), 4) if supported else None,
        "supported_requirements": len(supported), "covered_requirements": len(covered),
        "supported_but_not_used": [{"id": i, "class": requirement_class(by_id[i]), "text": by_id[i].original_text,
                                    "best_available": rows[i].get("best_available")} for i in unused],
        "no_supported_evidence": [{"id": i, "class": requirement_class(by_id[i]), "text": by_id[i].original_text,
                                   "best_available": rows.get(i, {}).get("best_available")} for i in gaps],
        "weights": weights(),
    }


def evaluate(*, document: ResumeDocument, jd: JobDescription, retrieval: Retrieval, store: CareerStore,
             trace_rows: list[dict], allowed: dict[str, set[str]], pages: int, drift: list[str],
             style_scores: dict[str, int] | None = None, feedback: dict | None = None) -> dict[str, Any]:
    bullets = ([document.summary] if document.summary else []) + document.bullets()
    rate, pairs = redundancy(bullets)
    scores = list((style_scores or {}).values())
    return {
        **claim_precision(bullets, store, allowed),
        **requirement_metrics(jd, trace_rows, retrieval, document),
        "redundant_bullet_rate": rate, "redundant_pairs": pairs,
        "page_compliance": 1.0 if pages == 1 else 0.0, "pages": pages,
        "template_fidelity": 1.0 if not drift else 0.0, "template_drift": drift,
        "style_score": round(sum(scores) / len(scores), 1) if scores else None,
        "user_acceptance_rate": (feedback or {}).get("acceptance_rate"),
        "user_rejection_rate": (feedback or {}).get("rejection_rate"),
        "bullets": len(bullets),
    }


def retrieval_recall(retrieval: Retrieval, expected_evidence: list[str], expected_projects: list[str]) -> dict[str, Any]:
    offered = {c.evidence_id for p in retrieval.projects for c in p.evidence}
    offered |= {m.evidence_id for found in retrieval.matches.values() for m in found}
    projects = {p.project_id for p in retrieval.projects}
    return {"evidence_retrieval_recall": round(sum(e in offered for e in expected_evidence) / len(expected_evidence), 4)
            if expected_evidence else None,
            "project_retrieval_recall": round(sum(p in projects for p in expected_projects) / len(expected_projects), 4)
            if expected_projects else None,
            "missed_evidence": [e for e in expected_evidence if e not in offered]}
