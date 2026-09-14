"""CPU-only, extractive resume composition. No model, network, or invented claims.

Database accomplishments are authoritative. Narrative sentences are candidates,
not permission to synthesize new facts. Every selection retains its exact source
and revision; unreviewed evidence remains a draft and cannot pass export gates.
"""
from __future__ import annotations

import hashlib
import json
import math
import re
from dataclasses import dataclass
from functools import lru_cache
from typing import Any

from app.services.resume_intelligence import quality, semantic
from app.services.resume_intelligence.bm25 import BM25Index
from app.services.resume_intelligence.fusion import reciprocal_rank_fusion
from app.services.story_index import flat_tags as _flat_tags

VERSION = "local-evidence-v2"
STOP = set("the and for with that this your you our are will have from into role work team years experience required preferred must should ability strong excellent skills knowledge including about using build develop".split())


def plain(value: Any) -> str:
    text = re.sub(r"<[^>]*>", "", str(value or "")).strip()
    return re.sub(r"\*\*(.*?)\*\*|`([^`]+)`", lambda m: m.group(1) if m.group(1) is not None else m.group(2), text)


@lru_cache(maxsize=1024)
def flat_tags(text: str) -> frozenset[str]:
    return frozenset(_flat_tags(text))


def _raw_tokens(text: str) -> list[str]:
    # A trailing "." is sentence punctuation, not part of the word - without
    # stripping it, "Kubernetes." at a clause's end and "Kubernetes" elsewhere
    # tokenize as two different words and silently fail to match each other.
    return [w.rstrip(".") for w in re.findall(r"[a-z][a-z0-9+#.]*", text.lower())]


@lru_cache(maxsize=1024)
def words(text: str) -> frozenset[str]:
    return frozenset(w for w in _raw_tokens(text) if len(w) > 2 and w not in STOP)


@lru_cache(maxsize=1024)
def tokenize(text: str) -> tuple[str, ...]:
    """Same vocabulary as words(), but keeps repeats and order for BM25 term frequency."""
    return tuple(w for w in _raw_tokens(text) if len(w) > 2 and w not in STOP)


def revision(record: dict) -> str:
    content = {k: v for k, v in record.items() if k not in ("revisionHistory", "updatedAt")}
    return hashlib.sha256(json.dumps(content, sort_keys=True, default=str).encode()).hexdigest()[:16]


def with_profile(records: list[dict], profile: dict) -> list[dict]:
    """Include profile achievements without overwriting the authored corpus."""
    result = list(records)
    for index, exp in enumerate(profile.get("workExperience") or []):
        if not isinstance(exp, dict):
            continue
        for number, sentence in enumerate(re.split(r"(?<=[.!?])\s+|\n+", plain(exp.get("description")))):
            if sentence.strip():
                result.append({"id": f"profile-experience-{index}-{number}", "company": exp.get("company"),
                    "role": exp.get("jobTitle"), "project": exp.get("jobTitle"), "currentBullet": sentence.strip(" -•"),
                    "evidenceTier": "professional", "profileSource": exp})
    return result


def evidenced_skills(bullets: list[dict], records: list[dict]) -> list[str]:
    """Retrieval aliases are not permission to assert a different technology."""
    sources = {str(r.get("id")): r for r in records}
    skills = set()
    for bullet in bullets:
        record = sources.get(str(bullet.get("id")), {})
        for skill in [*(record.get("technologies") or []), *(record.get("techStack") or [])]:
            if isinstance(skill, str) and skill and re.search(r"(?<!\w)" + re.escape(skill) + r"(?!\w)", bullet.get("optimizedBullet") or "", re.I):
                skills.add(skill)
    return sorted(skills)


def _normalized(line: str) -> str:
    return re.sub(r"\s+", " ", re.sub(r"[^a-z0-9 ]+", " ", line.lower())).strip()


def requirements(description: str, title: str = "") -> list[dict]:
    """Retain full requirement clauses, including vocabulary outside the tag map.

    Two clauses that restate the same requirement - a JD repeating a phrase
    verbatim in a summary and again under "Requirements", or two near-identical
    bullets differing only in wording - are folded into one entry so coverage
    and selection aren't double-counted or artificially inflated.
    """
    result: list[dict] = []
    seen_by_category: dict[str, list[tuple[str, frozenset[str], int]]] = {}
    category = "responsibility"
    for line in re.split(r"[\n;]+|(?<=[.!?])\s+(?=[A-Z])", description):
        line = line.strip(" \t-*•")
        if not line:
            continue
        if re.search(r"preferred|nice.to.have|bonus", line, re.I):
            category = "preferred"
        elif re.search(r"required|minimum qualifications|must.have|requirements", line, re.I):
            category = "required"
        elif re.search(r"responsibilities|what you.ll do", line, re.I):
            category = "responsibility"
        if len(words(line)) < 2 and not flat_tags(line):
            continue
        normalized = _normalized(line)
        line_words = words(line)
        seen = seen_by_category.setdefault(category, [])
        is_duplicate = False
        for existing_norm, existing_words, _index in seen:
            if existing_norm == normalized:
                is_duplicate = True
                break
            union = existing_words | line_words
            if union and len(existing_words & line_words) / len(union) >= 0.85:
                is_duplicate = True
                break
        if is_duplicate:
            continue
        result.append({"id": f"req-{len(result)+1}", "text": line, "category": category,
                       "weight": 3 if category == "required" else 1 if category == "preferred" else 2,
                       "tags": sorted(flat_tags(line))})
        seen.append((normalized, line_words, len(result) - 1))
    if title.strip():
        result.append({"id": "target-role", "text": title, "category": "seniority", "weight": 1,
                       "tags": sorted(flat_tags(title))})
    return result


def _candidates(records: list[dict]) -> list[dict]:
    candidates = []
    for record in records:
        if record.get("strength") == "unwritten" or record.get("status") in ("draft", "archived"):
            continue
        source_id = str(record.get("id") or "")
        if not source_id:
            continue
        source_revision = revision(record)
        entries = []
        evolution = record.get("resumeEvolution") or {}
        if isinstance(evolution, dict) and "current" in evolution:
            entries.append(("resumeEvolution.current", evolution["current"], None))
        for field in (() if entries else ("currentBullet", "description")):
            if isinstance(record.get(field), str) and record[field].strip():
                entries.append((field, record[field], None))
                break
        for index, variant in enumerate(record.get("resumeVariants") or []):
            if isinstance(variant, dict) and (variant.get("approved") is True or variant.get("status") == "published"):
                entries.append((f"resumeVariants.{index}.content", variant.get("content") or variant.get("text", ""), None))
        for story in record.get("interviewStories") or []:
            if not isinstance(story, dict):
                continue
            # Extract complete sentences, never splice facts from separate stories.
            for sentence in re.split(r"(?<=[.!?])\s+|\n+", story.get("body") or ""):
                if re.match(r"^(?:I |We |Built |Designed |Implemented |Led |Created |Delivered |Reduced |Improved |Developed )", sentence.strip()):
                    entries.append(("interviewStories.body", sentence, story))
        seen = set()
        for field, text, story in entries:
            text = plain(text)
            if text in seen or not 35 <= len(text) <= 650 or not re.search(r"[.!?]$", text):
                continue
            seen.add(text)
            if re.search(r"\b(?:do not claim|could have|would have|hypothetical)\b", text, re.I):
                continue
            if re.match(r"^(?:I|We) (?:wanted|planned|hoped|considered|would|could|needed)\b", text, re.I):
                continue
            metrics = record.get("metrics") or []
            unresolved = [m for m in metrics if isinstance(m, dict) and m.get("verification") != "verified"]
            metric_metadata = record.get("metricMetadata") or {}
            unresolved.extend(m for m in metric_metadata.values() if isinstance(m, dict) and m.get("verification") != "verified")
            approved = record.get("resumeApproved") is not False and not unresolved
            # Narrative extraction always requires a review of the selected sentence.
            if story is not None:
                approved = story.get("resumeApproved") is True and not unresolved
            tier = (story or {}).get("evidence") or record.get("evidenceTier") or "unclassified"
            if tier == "personal-project" and re.match(r"^(?:At |When |Before )", text):
                continue  # Background about employer work is not a personal-project achievement.
            candidates.append({"id": source_id, "company": str(record.get("company") or ""),
                "role": str(record.get("role") or ""), "project": str(record.get("project") or record.get("title") or ""),
                "optimizedBullet": text, "original": text, "evidenceTier": tier,
                "source": {"accomplishmentId": source_id, "storyId": (story or {}).get("id"),
                           "field": field, "text": text, "revision": source_revision},
                "approved": approved, "doNotClaim": record.get("doNotClaim") or [],
                "facts": {key: record.get(key) for key in ("problem", "problemContext", "ownership", "roleDetails", "architectureDecision", "decisions", "scale", "scaleMetrics", "impact", "verifiedMetrics") if record.get(key)},
            })
    return candidates


@dataclass
class _Eligible:
    index: int
    candidate: dict
    matches: list[str]
    relevance: float
    raw_score: float
    quality_score: float
    line_cost: int
    value_density: float


def _normalize01(values: list[float]) -> list[float]:
    if not values:
        return values
    lo, hi = min(values), max(values)
    if hi - lo < 1e-9:
        return [0.5] * len(values)
    return [(v - lo) / (hi - lo) for v in values]


def compose(records: list[dict], description: str, title: str = "", max_pages: int = 1, *,
            char_budget: int | None = None, max_bullets: int | None = None,
            bm25_k1: float = 1.5, bm25_b: float = 0.75, rrf_k: int = 60, mmr_lambda: float = 0.75,
            use_semantic: bool = True) -> dict:
    """Ranking: BM25 and (optionally) local sentence embeddings each rank every
    candidate against every requirement; the two rankings are fused with
    Reciprocal Rank Fusion (never mixing their raw, incompatible score scales).
    A candidate must still pass the original lexical/tag overlap gate to count
    toward a requirement at all - the fused score only re-orders candidates
    that already lexically match, it never invents a match the tag/word
    overlap wouldn't. Selection is then a Maximal Marginal Relevance greedy
    pick: prefer high fused relevance per line of page space, penalized by
    similarity to bullets already selected, so the result stays relevant but
    non-repetitive. requirementCoverage below is computed purely from lexical/
    tag overlap - BM25 and semantic scores never touch that number, so it
    stays an honest word-overlap estimate rather than a model-flavored score.
    """
    reqs = requirements(description, title)
    candidates = _candidates(records)
    doc_word_sets = [words(c["optimizedBullet"]) for c in candidates]
    doc_tags = [flat_tags(c["optimizedBullet"]) for c in candidates]
    bm25_index = BM25Index.build([tokenize(c["optimizedBullet"]) for c in candidates], k1=bm25_k1, b=bm25_b)

    semantic_vectors: dict[str, tuple[float, ...]] = {}
    semantic_ready = False
    if use_semantic and candidates and reqs:
        items = [(c["source"]["revision"], c["optimizedBullet"]) for c in candidates]
        items += [("req", req["text"]) for req in reqs]
        embedded = semantic.embed_many(items)
        if embedded is not None:
            semantic_vectors = embedded
            semantic_ready = True

    def candidate_vector(index: int) -> tuple[float, ...] | None:
        c = candidates[index]
        return semantic_vectors.get(semantic.cache_key(c["source"]["revision"], c["optimizedBullet"]))

    # Per requirement: BM25 rank, semantic rank (if available), and their RRF fusion.
    # These depend only on the fixed candidate pool, not on what's picked yet,
    # so they're computed once up front rather than inside the selection loop.
    req_fused: list[dict[int, float]] = []
    req_debug: list[dict[str, list[int]]] = []
    for req in reqs:
        bm25_rank = bm25_index.rank(tokenize(req["text"]))
        ranked_lists = [bm25_rank]
        semantic_rank: list[int] = []
        if semantic_ready:
            req_vector = semantic_vectors.get(semantic.cache_key("req", req["text"]))
            if req_vector is not None:
                sims = [semantic.cosine(req_vector, candidate_vector(i) or (0.0,) * len(req_vector)) for i in range(len(candidates))]
                semantic_rank = sorted(range(len(candidates)), key=lambda i: (-sims[i], i))
                ranked_lists.append(semantic_rank)
        req_fused.append(reciprocal_rank_fusion(ranked_lists, k=rrf_k))
        req_debug.append({"bm25Rank": bm25_rank, "semanticRank": semantic_rank})

    covered: set[str] = set()
    selected: list[dict] = []
    selected_indices: list[int] = []
    used: set[str] = set()
    used_text: set[str] = set()
    budget = char_budget if char_budget is not None else max(1, min(3, max_pages)) * 2300
    for _ in range(max_bullets if max_bullets is not None else max(1, min(3, max_pages)) * 10):
        eligible: list[_Eligible] = []
        for index, c in enumerate(candidates):
            if c["id"] in used or c["optimizedBullet"] in used_text or len(c["optimizedBullet"]) > budget:
                continue
            if c["evidenceTier"] != "professional" and sum(s["evidenceTier"] != "professional" for s in selected) >= 3 * max_pages:
                continue
            token_set = doc_word_sets[index]
            tags = doc_tags[index]
            matches = []
            raw_score = 0.0
            for req_index, req in enumerate(reqs):
                overlap = words(req["text"]) & token_set
                tag_overlap = set(req["tags"]) & tags
                if tag_overlap or len(overlap) >= 2:
                    matches.append(req["id"])
                    fused = req_fused[req_index].get(index, 0.0)
                    raw_score += req["weight"] * (fused + 0.15 * len(tag_overlap)) * (0.2 if req["id"] in covered else 1)
            if raw_score <= 0:
                continue
            tier_multiplier = 1.5 if c["evidenceTier"] == "professional" else 0.65
            quality_multiplier = quality.score(c, tags=tags)
            relevance = raw_score * tier_multiplier * quality_multiplier
            line_cost = max(1, math.ceil(len(c["optimizedBullet"]) / 95))
            eligible.append(_Eligible(index=index, candidate=c, matches=matches, relevance=relevance,
                                       raw_score=raw_score, quality_score=round(quality_multiplier, 3),
                                       line_cost=line_cost, value_density=relevance / line_cost))
        if not eligible:
            break
        densities = _normalize01([e.value_density for e in eligible])
        best: _Eligible | None = None
        best_mmr: float | None = None
        best_diversity = 0.0
        for entry, normalized_density in zip(eligible, densities, strict=True):
            index = entry.index
            vector = candidate_vector(index) if semantic_ready else None
            if not selected_indices:
                diversity_penalty = 0.0
            elif vector is not None:
                diversity_penalty = max(
                    (semantic.cosine(vector, candidate_vector(s) or (0.0,) * len(vector)) for s in selected_indices),
                    default=0.0,
                )
            else:
                diversity_penalty = max(
                    (len(doc_word_sets[index] & doc_word_sets[s]) / max(1, len(doc_word_sets[index] | doc_word_sets[s]))
                     for s in selected_indices),
                    default=0.0,
                )
            mmr = mmr_lambda * normalized_density - (1 - mmr_lambda) * diversity_penalty
            if best is None or best_mmr is None or mmr > best_mmr or (mmr == best_mmr and index < best.index):
                best, best_mmr, best_diversity = entry, mmr, diversity_penalty
        assert best is not None
        index, c, matches = best.index, best.candidate, best.matches
        primary_req = max(matches, key=lambda rid: next(r["weight"] for r in reqs if r["id"] == rid)) if matches else None
        primary_req_index = next((i for i, r in enumerate(reqs) if r["id"] == primary_req), None)
        debug = {
            "matchedRequirementIds": matches,
            "matchedTags": sorted(doc_tags[index]),
            "bm25Rank": (req_debug[primary_req_index]["bm25Rank"].index(index) + 1) if primary_req_index is not None else None,
            "semanticRank": (req_debug[primary_req_index]["semanticRank"].index(index) + 1)
                if primary_req_index is not None and req_debug[primary_req_index]["semanticRank"] else None,
            "semanticAvailable": semantic_ready,
            "rrfScore": round(best.raw_score, 4),
            "qualityScore": best.quality_score,
            "diversityPenalty": round(best_diversity, 4),
            "lineCostEstimate": best.line_cost,
            "finalRelevance": round(best.relevance, 4),
        }
        selected.append({**c, "requirementIds": matches, "debug": debug,
                          "selectionReason": "Source sentence matches " + ", ".join(matches)})
        covered.update(matches)
        used.add(c["id"])
        used_text.add(c["optimizedBullet"])
        selected_indices.append(index)
        budget -= len(c["optimizedBullet"])
    # Matching one term is only partial support for a compound requirement.
    selected_words = set().union(*(words(s["optimizedBullet"]) for s in selected)) if selected else set()
    selected_tags = set().union(*(flat_tags(s["optimizedBullet"]) for s in selected)) if selected else set()
    for req in reqs:
        fraction = len(words(req["text"]) & selected_words) / max(1, len(words(req["text"])))
        req["coverageFraction"] = round(fraction, 2)
        req["coverageStatus"] = "covered" if fraction >= 0.6 and set(req["tags"]) <= selected_tags else "partial" if req["id"] in covered else "uncovered"
    coverage = round(100 * sum(r["weight"] * r["coverageFraction"] for r in reqs) / max(1, sum(r["weight"] for r in reqs)), 1)
    warnings = []
    if not description.strip():
        warnings.append("A full job description is required before export.")
    if not selected:
        warnings.append("No complete source bullets match this job. Add or approve a resume bullet for relevant stories.")
    for item in selected:
        if not item["approved"]:
            warnings.append(f"Review source claims before export: {item['project'] or item['id']}.")
        if item["evidenceTier"] == "unclassified":
            warnings.append(f"Classify evidence as professional or personal project: {item['id']}.")
        for restriction in item["doNotClaim"]:
            if flat_tags(str(restriction)) & flat_tags(item["optimizedBullet"]):
                warnings.append(f"Check claim restriction for {item['id']}: {restriction}")
    return {"targetRoleMatched": title, "atsMatchScore": None, "requirementCoverage": coverage,
            "scoreKind": "lexical-evidence-coverage", "overallCritique": "Selected existing source sentences locally; no claims were generated.",
            "skillsList": evidenced_skills(selected, records),
            "resumeBullets": selected, "requirements": reqs,
            "uncoveredRequirements": [r for r in reqs if r["coverageStatus"] != "covered"],
            "provenance": "selected-records", "method": VERSION, "warnings": warnings,
            "maxPages": max(1, min(3, max_pages)),
            "exportReady": bool(selected) and not warnings,
            "rankingDebug": {"semanticAvailable": semantic_ready, "bm25K1": bm25_k1, "bm25B": bm25_b,
                              "rrfK": rrf_k, "mmrLambda": mmr_lambda},
            "sourceRevision": revision({"records": records, "description": description, "title": title, "pages": max_pages, "version": VERSION})}


def validate_sources(result: dict, records: list[dict]) -> list[str]:
    if result.get("method") == "minimal-change-v1":
        from app.services.resume_intelligence.minimal_tailoring import validate
        return validate(result, records)
    sources = {str(r.get("id")): r for r in records}
    problems = []
    if not result.get("resumeBullets"):
        return ["Compose a resume with source-backed bullets before export."]
    for bullet in result.get("resumeBullets") or []:
        source = bullet.get("source") or {}
        record = sources.get(source.get("accomplishmentId"))
        if not record or revision(record) != source.get("revision"):
            problems.append("Evidence changed since composition; regenerate the resume.")
        elif not any(c["source"] == source and all(c.get(k) == bullet.get(k) for k in
                    ("id", "company", "role", "project", "optimizedBullet", "evidenceTier")) for c in _candidates([record])):
            problems.append("A bullet no longer matches its source.")
    allowed_skills = set(evidenced_skills(result.get("resumeBullets") or [], records))
    if not set(result.get("skillsList") or []) <= allowed_skills:
        problems.append("Skills must be evidenced in the selected bullets.")
    return list(dict.fromkeys(problems))
