"""Conservative, extractive slot selection. Coverage is diagnostic only."""
from __future__ import annotations

from copy import deepcopy
from dataclasses import asdict, dataclass, replace
import math

from app.services.resume_intelligence import quality, semantic
from app.services.resume_intelligence.baseline_document import load_baseline, replacement_runs, fits
from app.services.resume_intelligence.bm25 import BM25Index
from app.services.resume_intelligence.fusion import reciprocal_rank_fusion
from app.services.resume_intelligence.local_composer import _candidates, flat_tags, requirements, revision, tokenize, words

VERSION = "minimal-change-v1"
MODES = ("off", "honest", "aggressive")


def mode_config(mode: str, settings: dict | None = None) -> "TailoringConfig":
    if mode not in MODES:
        raise ValueError("Choose off, honest, or aggressive tailoring.")
    defaults = {}
    if mode == "aggressive":
        defaults = {"weak_relevance": .75, "retention_bonus": .05, "replacement_cost": .03,
                    "max_replacement_fraction": .5, "reorder_threshold": .05}
    # Existing explicitly saved preferences win over mode defaults. The 15%
    # material-improvement threshold remains the same unless configured.
    config = TailoringConfig(**{**defaults, **(settings or {})})
    return replace(config,use_semantic=False,weak_relevance=0,max_replacement_fraction=0,reorder_threshold=1) if mode=="off" else config


@dataclass(frozen=True)
class TailoringConfig:
    bm25_k1: float = 1.5
    bm25_b: float = .75
    rrf_k: int = 60
    mmr_lambda: float = .75
    use_semantic: bool = True
    replacement_threshold: float = .15
    weak_relevance: float = .35
    retention_bonus: float = .12
    replacement_cost: float = .08
    max_replacement_fraction: float = .25
    reorder_threshold: float = .15

    def __post_init__(self):
        for key, value in asdict(self).items():
            if not isinstance(value, (int, float)) or not math.isfinite(value):
                raise ValueError(f"Invalid tailoring setting: {key}")
        for key in ("mmr_lambda", "replacement_threshold", "weak_relevance", "retention_bonus", "replacement_cost", "max_replacement_fraction", "reorder_threshold"):
            if not 0 <= getattr(self, key) <= 1:
                raise ValueError(f"{key} must be between zero and one")
        if self.bm25_k1 <= 0 or not 0 <= self.bm25_b <= 1 or self.rrf_k < 1:
            raise ValueError("Invalid BM25/RRF configuration")


def _rank(candidates, reqs, config):
    from app.services.resume_intelligence.evidence_match import support
    index = BM25Index.build([tokenize(c["optimizedBullet"]) for c in candidates], k1=config.bm25_k1, b=config.bm25_b)
    try:
        vectors = semantic.embed_many([(c["source"]["revision"], c["optimizedBullet"]) for c in candidates] +
                                     [("req", r["text"]) for r in reqs]) if config.use_semantic and reqs else None
    except Exception:
        vectors = None  # Missing weights, memory pressure, or encoder failures use lexical ranking.
    scores = [0.0] * len(candidates)
    matches = [[] for _ in candidates]
    total = max(1, sum(r["weight"] for r in reqs))
    for req in reqs:
        ranks = [index.rank(tokenize(req["text"]))]
        if vectors is not None:
            query = vectors.get(semantic.cache_key("req", req["text"]))
            if query:
                sims = [semantic.cosine(query, vectors.get(semantic.cache_key(c["source"]["revision"], c["optimizedBullet"]), (0.,) * len(query))) for c in candidates]
                ranks.append(sorted(range(len(candidates)), key=lambda i: (-sims[i], i)))
        fused = reciprocal_rank_fusion(ranks, k=config.rrf_k)
        ceiling = len(ranks) / (config.rrf_k + 1)
        for i, c in enumerate(candidates):
            overlap = words(req["text"]) & words(c["optimizedBullet"])
            tags = set(req["tags"]) & flat_tags(c["optimizedBullet"])
            if (tags or len(overlap) >= 2) and support(req["text"],c["optimizedBullet"])["status"] in ("supported","partial"):
                matches[i].append(req["id"])
                # Rank relevance, with an absolute overlap gate, not coverage gain.
                scores[i] += req["weight"] * fused.get(i, 0) / ceiling / total
    return scores, matches, vectors


def _priority(c):
    field = c["source"]["field"]
    return 4 if field == "approvedResume" else 3 if field.startswith("resumeVariants") else 1 if "interviewStories" in field else 2


def _reviewed_candidates(records):
    sources = {str(r.get("id")): r for r in records}
    result = []
    for candidate in _candidates(records):
        record = sources[candidate["id"]]
        field = candidate["source"]["field"]
        explicit = (field.startswith("resumeVariants") or "interviewStories" in field or
                    record.get("resumeApproved") is True or record.get("reviewStatus") in ("reviewed", "approved") or
                    record.get("reviewed") is True)
        if explicit and candidate["approved"]:
            result.append(candidate)
    return result


def tailor(records, description, title="", *, baseline=None, config=None, fit_check=None, mode="honest"):
    baseline = baseline or load_baseline()
    if mode not in MODES:
        raise ValueError("Choose off, honest, or aggressive tailoring.")
    config = config or mode_config(mode)
    if mode == "off":
        config = replace(config,use_semantic=False,weak_relevance=0,max_replacement_fraction=0,reorder_threshold=1)
    fit_check = fit_check or fits
    from app.services.resume_intelligence.evidence_match import extract_requirements
    reqs = extract_requirements(description)
    for req in reqs:
        req["tags"] = sorted(flat_tags(req["text"]))
    incumbents = [{"id": b["id"], "baselineBulletId": b["id"], "company": b["company"], "role": b["role"],
                   "project": b["project"], "optimizedBullet": b["text"], "original": b["text"],
                   "richText": deepcopy(b["richText"]), "source": b["source"], "approved": True,
                   "evidenceTier": "professional" if b["company"] else "personal-project", "doNotClaim": []}
                  for b in baseline["bullets"]]
    baseline_scores, _, _ = _rank(incumbents, reqs, config)
    weak = {i for i, value in enumerate(baseline_scores) if value < config.weak_relevance}
    # Do not even enumerate narrative/corpus candidates unless a weak slot exists.
    alternatives = _reviewed_candidates(records) if weak else []
    pool = incumbents + alternatives
    scores, matches, vectors = _rank(pool, reqs, config)
    def redundancy(c, others):
        vector = (vectors or {}).get(semantic.cache_key(c["source"]["revision"], c["optimizedBullet"]))
        def similarity(other):
            ov = (vectors or {}).get(semantic.cache_key(other["source"]["revision"], other["optimizedBullet"]))
            if vector and ov:
                return max(0., semantic.cosine(vector, ov))
            a, b = words(c["optimizedBullet"]), words(other["optimizedBullet"])
            return len(a & b) / max(1, len(a | b))
        return max((similarity(o) for o in others), default=0.)
    def utility(i, others, incumbent=False):
        c = pool[i]
        q = quality.score(c, tags=flat_tags(c["optimizedBullet"])) / quality.MAX_SCORE
        value = config.mmr_lambda * (.75 * scores[i] + .20 * q + .05 * _priority(c) / 4)
        value -= (1 - config.mmr_lambda) * redundancy(c, others)
        return value + config.retention_bonus if incumbent else value - config.replacement_cost
    selected = deepcopy(incumbents)
    replaced = 0
    cap = int(len(incumbents) * config.max_replacement_fraction)
    for i, (slot, item) in enumerate(zip(baseline["bullets"], selected)):
        item.update(decision="KEEP", requirementIds=matches[i], selectionReason="Strong approved bullet retained." if i not in weak else "No materially stronger, eligible evidence fits this slot.")
        if mode == "off":
            item["selectionReason"] = "OFF preserves the approved resume exactly."
        others = selected[:i] + selected[i+1:]
        base = utility(i, others, True)
        item["debug"] = {"baselineRelevance": baseline_scores[i], "baselineUtility": base, "semanticAvailable": vectors is not None}
        if i in weak and not alternatives:
            item["selectionReason"] = "Retained: no approved variant or reviewed source evidence is available for replacement."
        elif i in weak and replaced >= cap:
            item["selectionReason"] = "Retained to respect the configured baseline-retention limit."
        if i not in weak or replaced >= cap:
            continue
        options = []
        for j in range(len(incumbents), len(pool)):
            candidate = pool[j]
            if candidate["company"].casefold().strip() != slot["company"].casefold().strip():
                continue
            if slot["company"]:
                if candidate["role"] and candidate["role"].casefold().strip() != slot["role"].casefold().strip():
                    continue
                employer_groups = {b["group"] for b in baseline["bullets"] if b["company"].casefold() == slot["company"].casefold()}
                if not candidate["role"] and len(employer_groups) != 1:
                    continue  # Employer-only records are safe only for an unambiguous role.
            if not slot["company"] and candidate["project"].casefold().strip() != slot["project"].casefold().strip():
                continue
            if not candidate["approved"] or candidate["doNotClaim"] or candidate["evidenceTier"] != item["evidenceTier"]:
                continue
            if any(candidate["optimizedBullet"] == o["optimizedBullet"] for o in selected):
                continue
            if any(o.get("decision") == "REPLACE" and o["id"] == candidate["id"] for o in selected):
                continue  # Different variants of one accomplishment are not two achievements.
            value = utility(j, others)
            gain = value - base
            if gain <= max(abs(base), .1) * config.replacement_threshold or scores[j] <= scores[i]:
                continue
            runs = replacement_runs(candidate["optimizedBullet"], slot)
            if fit_check(slot, runs):
                options.append((_priority(candidate), value, j, runs, gain))
        if options:
            _, value, j, runs, gain = max(options, key=lambda o: (o[0], o[1], -o[2]))
            selected[i] = {**deepcopy(pool[j]), "original": slot["text"], "baselineBulletId": slot["id"],
                           "richText": runs, "decision": "REPLACE", "requirementIds": matches[j],
                           "selectionReason": f"Weak slot replaced with exact source evidence; utility improves {gain / max(abs(base), .1):.0%} after retention and replacement costs.",
                           "debug": {**item["debug"], "candidateUtility": value, "improvementFraction": gain / max(abs(base), .1)}}
            replaced += 1
    # Compare all compatible slots in a role, not only immediate neighbours.
    # A three-line bullet between two two-line bullets must not block a safe move.
    def geometry(slot):
        return (slot["group"], tuple(round(line["spans"][0]["origin"][1] - slot["lines"][0]["spans"][0]["origin"][1], 1) for line in slot["lines"]),
                round(slot["rect"][3] - slot["rect"][1], 1), round(slot["right"] - slot["rect"][0], 1))
    groups = {}
    for index, slot in enumerate(baseline["bullets"]):
        if selected[index]["decision"] == "KEEP":
            groups.setdefault(geometry(slot), []).append(index)
    score_by_id = {c["baselineBulletId"]: score for c, score in zip(incumbents, baseline_scores)}
    def relevance(index):
        return score_by_id[selected[index]["baselineBulletId"]]
    for indices in groups.values():
        for offset, target in enumerate(indices):
            candidates = indices[offset:]
            best = max(candidates, key=relevance)
            if relevance(best) - relevance(target) > config.reorder_threshold:
                selected[target], selected[best] = selected[best], selected[target]
    for slot, item in zip(baseline["bullets"], selected):
        if item["decision"] != "REPLACE" and slot["id"] != item["baselineBulletId"]:
            item.update(decision="REORDER", selectionReason="Moved within the same role to lead with more relevant evidence; original text and rich-text runs retained.")
    selected_words = set().union(*(words(c["optimizedBullet"]) for c in selected))
    for r in reqs:
        fraction = len(words(r["text"]) & selected_words) / max(1, len(words(r["text"])))
        r.update(coverageFraction=round(fraction, 2), coverageStatus="covered" if fraction >= .6 else "partial" if fraction else "uncovered")
    warnings = [] if description.strip() else ["A full job description is required before export."]
    changed_count = sum(item["decision"] != "KEEP" for item in selected)
    explanation = ("OFF returns the approved resume unchanged." if mode == "off" else
        f"{changed_count} bullets moved or replaced using source-backed evidence." if changed_count else
        "No safe improvement met the configured threshold and layout constraints.")
    if mode != "off" and not alternatives and weak:
        explanation += " No approved replacement evidence is available; review accomplishments before enabling replacements."
    result = {"tailoringSummary": explanation, "eligibleReplacementCount": len(alternatives), "method": VERSION, "mode": mode, "baselineRevision": baseline["revision"], "baselineFilename": baseline["filename"],
              "targetRoleMatched": title, "resumeBullets": selected, "requirements": reqs,
              "uncoveredRequirements": [r for r in reqs if r["coverageStatus"] != "covered"],
              "requirementCoverage": round(100 * sum(r["weight"] * r["coverageFraction"] for r in reqs) / max(1, sum(r["weight"] for r in reqs)), 1),
              "scoreKind": "lexical-evidence-coverage", "atsMatchScore": None, "skillsList": [],
              "warnings": warnings, "exportReady": not warnings, "maxPages": 1, "provenance": "approved-baseline-and-source-records",
              "overallCritique": "Preserved the approved resume; only material, source-backed changes are eligible. Coverage is diagnostic.",
              "decisions": [{"slotId": b["id"], "baselineBulletId": c["baselineBulletId"], "decision": c["decision"], "reason": c["selectionReason"]} for b, c in zip(baseline["bullets"], selected)],
              "retentionFraction": (len(selected)-replaced)/len(selected), "tailoringConfig": asdict(config),
              "rankingDebug": {"semanticAvailable": vectors is not None, "bm25K1": config.bm25_k1, "bm25B": config.bm25_b, "rrfK": config.rrf_k, "mmrLambda": config.mmr_lambda}}
    result["sourceRevision"] = revision({"baseline": baseline["revision"], "records": records, "description": description, "title": title, "config": asdict(config), "version": VERSION})
    result["documentRevision"] = revision(result)
    return result


def validate(result, records):
    baseline = load_baseline()
    problems = []
    if result.get("baselineRevision") != baseline["revision"]:
        return ["Approved baseline changed; regenerate."]
    if revision({k: v for k, v in result.items() if k not in ("documentRevision", "content")}) != result.get("documentRevision"):
        problems.append("Tailoring document changed; regenerate.")
    sources = {b["id"]: b for b in baseline["bullets"]}
    for item in result.get("resumeBullets", []):
        if item.get("decision") in ("KEEP", "REORDER"):
            b = sources.get(item.get("baselineBulletId"))
            if not b or item.get("richText") != b["richText"] or item.get("optimizedBullet") != b["text"] or item.get("source") != b["source"]:
                problems.append("Baseline text or formatting changed; regenerate.")
        elif not any(c["source"] == item.get("source") and c["approved"] and not c["doNotClaim"] and
                     all(c[k] == item.get(k) for k in ("optimizedBullet", "company", "role", "project", "evidenceTier")) for c in _reviewed_candidates(records)):
            problems.append("Replacement evidence changed; regenerate.")
    return list(dict.fromkeys(problems))
