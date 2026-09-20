"""Conservative, extractive slot selection. Coverage is diagnostic only."""
from __future__ import annotations

import logging

from copy import deepcopy
from dataclasses import asdict, dataclass, replace
import math
import re

from app.services.resume_intelligence import quality, semantic
from app.services.resume_intelligence.baseline_document import (
    fits,
    load_baseline,
    reflow_fits,
    replacement_runs,
)
from app.services.resume_intelligence.bm25 import BM25Index
from app.services.resume_intelligence.fusion import reciprocal_rank_fusion
from app.services.resume_intelligence.local_composer import (
    GENERIC_OVERLAP_WORDS,
    _candidates,
    flat_tags,
    requirements,
    revision,
    tokenize,
    words,
)

logger = logging.getLogger("career_os.resume_build")

VERSION = "minimal-change-v1"
MODES = ("off", "honest", "aggressive")
RETRIEVAL_MODES = ("fused", "semantic", "lexical")
#: Settings that are not numbers, and so are exempt from the numeric check.
_NON_NUMERIC_SETTINGS = frozenset({"retrieval"})

#: Every reason a candidate can be turned away from a slot, in the order the
#: selection loop checks them. Counting these is the difference between "the
#: resume did not change" and knowing *why* it did not change — which is the
#: question that took a bespoke script to answer the first three times it came
#: up. `tailor` logs the tally at INFO and each individual rejection at DEBUG.
REJECTION_REASONS = (
    "slot-not-weak",
    "company-mismatch",
    "role-mismatch",
    "ambiguous-employer-role",
    "project-mismatch",
    "tier-or-approval",
    "restates-a-caution",
    "duplicate-text",
    "same-accomplishment-already-used",
    "ranks-below-incumbent",
    "gain-below-threshold",
    "does-not-fit",
)


def _brief(text: str, limit: int = 90) -> str:
    """One line of a bullet, for a log record."""
    flat = " ".join(str(text or "").split())
    return flat if len(flat) <= limit else flat[: limit - 1] + "\u2026"


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
    #: How much the story index's own ranking of the posting counts in a
    #: candidate's utility, on top of the bullet-level BM25/semantic ranking.
    story_index_weight: float = .20
    #: How many stories the index is asked for. Candidates from outside that
    #: set are still allowed, they simply get no boost — retrieval narrows the
    #: field without being able to starve it.
    story_retrieval_limit: float = 12
    #: How bullet-level relevance is ranked: "fused" combines BM25 and the
    #: embedding model with reciprocal rank fusion, "semantic" uses the
    #: embedding model alone, "lexical" uses BM25 alone. Measured over 241
    #: labelled requirement queries by scripts/matchlab/evidence_retrieval.py,
    #: semantic alone ranks better than the fusion (MAP 0.454 against 0.416,
    #: nDCG@10 0.466 against 0.401) — fusing a strong dense retriever with a
    #: weaker lexical one drags it down rather than complementing it. "fused"
    #: remains the default because that bench uses proxy labels and this
    #: module's own tag-overlap gate means its ranking is not the only thing
    #: deciding a swap; flip it to "semantic" to take the measured gain.
    retrieval: str = "fused"

    def __post_init__(self):
        for key, value in asdict(self).items():
            if key in _NON_NUMERIC_SETTINGS:
                continue
            if not isinstance(value, (int, float)) or not math.isfinite(value):
                raise ValueError(f"Invalid tailoring setting: {key}")
        for key in ("mmr_lambda", "replacement_threshold", "weak_relevance", "retention_bonus", "replacement_cost", "max_replacement_fraction", "reorder_threshold", "story_index_weight"):
            if not 0 <= getattr(self, key) <= 1:
                raise ValueError(f"{key} must be between zero and one")
        if self.bm25_k1 <= 0 or not 0 <= self.bm25_b <= 1 or self.rrf_k < 1:
            raise ValueError("Invalid BM25/RRF configuration")
        if self.retrieval not in RETRIEVAL_MODES:
            raise ValueError("retrieval must be one of " + ", ".join(RETRIEVAL_MODES))
        if not 1 <= self.story_retrieval_limit <= 60:
            raise ValueError("story_retrieval_limit must be between one and sixty")


def story_relevance(description: str, title: str, config: TailoringConfig) -> dict[str, float]:
    """Story id -> how well the index thinks that story answers this posting.

    The story index already does the retrieval this module needs and was not
    being consulted: it tags a posting and the corpus with one controlled
    vocabulary, normalises aliases on both sides ("k8s", "EKS" and "container
    orchestration" all reach "Kubernetes"), and weights rare tags higher, so a
    posting full of generic cloud words still ranks the right story first.
    Bullet-level BM25 cannot do any of that, because it only ever sees one
    sentence at a time.

    The scores are normalised to 0..1 and used as a bonus, never as a filter,
    so an index that returns nothing (or fails) leaves selection exactly as it
    was.
    """
    try:
        from app.services.story_index import get_index

        matches = get_index().rank(description, title=title, limit=int(config.story_retrieval_limit))
    except Exception:
        return {}  # An unavailable index must not change what gets selected.
    if not matches:
        return {}
    top = max((m.score for m in matches), default=0.0)
    if top <= 0:
        return {}
    return {m.story.id: max(0.0, min(1.0, m.score / top)) for m in matches}


def _credited(req: dict, candidate_text: str) -> tuple[bool, set[str], set[str]]:
    """Whether this candidate may be credited with this requirement, and on what.

    Two ways in, and the first one is the one that matters:

    * **Shared tags.** The requirement names a technology or concept in the
      controlled vocabulary and the bullet demonstrates the same one. This is
      real evidence of fit.
    * **Shared distinctive words**, but *only for a requirement that carries no
      tags at all* — an untagged responsibility line like "own the systems you
      build" has nothing else to match on. Generic engineering vocabulary is
      excluded, so the two words have to actually mean something.

    The rule this replaces credited any requirement on any two shared content
    words. That let a bullet about Microsoft Defender and Entra claim a
    distributed-systems requirement on the words "backend" and "systems", score
    0.387, and take a slot on a streaming-platform posting. A requirement that
    names a technology is asking about that technology; if the bullet does not
    show it, the bullet does not answer it.
    """
    tags = set(req["tags"]) & flat_tags(candidate_text)
    overlap = words(req["text"]) & words(candidate_text)
    if tags:
        return True, tags, overlap
    if req["tags"]:
        # The requirement is about something specific and this bullet does not
        # show it. Shared prose is not evidence.
        return False, tags, overlap
    distinctive = {w for w in overlap if w not in GENERIC_OVERLAP_WORDS}
    return len(distinctive) >= 2, tags, distinctive


def _rank(candidates, reqs, config):
    from app.services.resume_intelligence.evidence_match import support
    index = BM25Index.build([tokenize(c["optimizedBullet"]) for c in candidates], k1=config.bm25_k1, b=config.bm25_b)
    try:
        # Bullets are passages, requirements are queries. BGE is trained with an
        # asymmetric convention and embedding both sides the same way loses
        # retrieval quality it was built to have; the two calls share one cache
        # keyed on the bare text, so a requirement looks up the same either way.
        vectors = None
        if config.use_semantic and reqs:
            passages = semantic.embed_many([(c["source"]["revision"], c["optimizedBullet"]) for c in candidates])
            queries = semantic.embed_queries([("req", r["text"]) for r in reqs])
            if passages is not None and queries is not None:
                vectors = {**passages, **queries}
    except Exception:
        vectors = None  # Missing weights, memory pressure, or encoder failures use lexical ranking.
    scores = [0.0] * len(candidates)
    matches = [[] for _ in candidates]
    total = max(1, sum(r["weight"] for r in reqs))
    for req in reqs:
        ranks = []
        if config.retrieval in ("fused", "lexical"):
            ranks.append(index.rank(tokenize(req["text"])))
        if vectors is not None and config.retrieval in ("fused", "semantic"):
            query = vectors.get(semantic.cache_key("req", req["text"], semantic.QUERY))
            if query:
                sims = [semantic.cosine(query, vectors.get(semantic.cache_key(c["source"]["revision"], c["optimizedBullet"]), (0.,) * len(query))) for c in candidates]
                ranks.append(sorted(range(len(candidates)), key=lambda i: (-sims[i], i)))
        if not ranks:
            # "semantic" with no model available: fall back to lexical rather
            # than ranking everything equally, which would make the order of
            # the corpus decide the resume.
            ranks.append(index.rank(tokenize(req["text"])))
        fused = reciprocal_rank_fusion(ranks, k=config.rrf_k)
        ceiling = len(ranks) / (config.rrf_k + 1)
        for i, c in enumerate(candidates):
            eligible, tags, evidence = _credited(req, c["optimizedBullet"])
            if eligible and support(req["text"],c["optimizedBullet"])["status"] in ("supported","partial"):
                matches[i].append(req["id"])
                if logger.isEnabledFor(logging.DEBUG):
                    logger.debug(
                        "resume build: %r credited with %r via tags=%s words=%s",
                        _brief(c["optimizedBullet"], 60), _brief(req["text"], 60),
                        sorted(tags), sorted(evidence),
                    )
                # Rank relevance, with an absolute overlap gate, not coverage gain.
                scores[i] += req["weight"] * fused.get(i, 0) / ceiling / total
    # Relevance is reported on a 0..1 scale, where 1 is the most relevant
    # candidate in this set. The raw sum divides by the posting's total
    # requirement weight, which puts it in a range that depends on how many
    # requirements the posting happens to list: on a four-bullet JD it lands
    # near 0.5, on a long one near 0.05. Every threshold in TailoringConfig is
    # written as a fraction -- a 0.35 "weak" floor, a 0.12 retention bonus, an
    # 0.08 replacement cost -- so on the raw scale those constants swamped the
    # signal by an order of magnitude: measured on a real posting, relevance
    # spanned 0 to 0.18 while retention plus replacement cost was a fixed 0.20
    # against any change, which no candidate could ever overcome. That is why
    # nothing was ever replaced. Normalising here makes the configured numbers
    # mean what they say.
    top = max(scores, default=0.0)
    if top > 0:
        scores = [value / top for value in scores]
    return scores, matches, vectors


#: How much of a caution's content words must appear in a sentence before the
#: sentence is treated as making that claim. High enough that an incidental
#: word or two in common is not a match, low enough that a re-worded version of
#: the same claim still is.
FORBIDDEN_CLAIM_OVERLAP = 0.6

#: Lead-ins the corpus writes its cautions with. They are instructions to the
#: reader, not part of the claim, so they are stripped before comparing.
_CAUTION_PREFIX = re.compile(
    r"^\s*(do not (claim|invent|say|state|imply)|don'?t (claim|invent|say)|never (claim|say))\b[:,]?\s*",
    re.I,
)


def asserts_forbidden_claim(candidate: dict) -> bool:
    """Whether this sentence makes one of its record's do-not-claim claims.

    `doNotClaim` used to disqualify every candidate from a record that had one.
    That is backwards: a caution exists so the rest of the story *can* be used
    while that specific claim is avoided, and because the corpus attaches
    cautions to its strongest, most-examined stories, the blanket veto removed
    31 of the 45 eligible candidates — the best evidence first.

    So the check moved onto the sentence. A caution's content words are
    compared against the sentence's; only a sentence that substantially
    restates the caution is refused. The comparison runs on the same tokenizer
    the rest of the ranking uses, so "exactly-once" and "exactly once" are one
    word either way.
    """
    sentence = words(candidate.get("optimizedBullet") or "")
    if not sentence:
        return False
    for caution in candidate.get("doNotClaim") or []:
        text = _CAUTION_PREFIX.sub("", str(caution or ""))
        # A caution often explains itself after a dash or semicolon ("it already
        # existed for users; my ownership was..."). Only the claim itself, up to
        # that break, is what must not be asserted.
        claim = re.split(r"\s+[-\u2013\u2014]\s+|;", text, maxsplit=1)[0]
        terms = words(claim)
        if len(terms) < 3:
            continue
        if len(terms & sentence) / len(terms) >= FORBIDDEN_CLAIM_OVERLAP:
            return True
    return False


#: A bullet on this resume opens with a verb, not a pronoun. Story prose
#: routinely opens "I owned ..." or "We built ...", which is the same claim in
#: the wrong voice, and one of those next to five verb-first bullets reads as a
#: seam. Rewriting it is the one thing this composer will not do, so the voice
#: is handled where it can be — in the ranking, by preferring the candidate
#: that already reads like the page.
_PRONOUN_OPENER = re.compile(r"^(?:I|We)", re.I)


def _voice_penalty(candidate: dict) -> float:
    return .5 if _PRONOUN_OPENER.match(candidate.get("optimizedBullet") or "") else 0.0


def _priority(c):
    field = c["source"]["field"]
    base = 4 if field == "approvedResume" else 3 if field.startswith("resumeVariants") else 1 if "interviewStories" in field else 2
    return base - _voice_penalty(c)


def _reviewed_candidates(records):
    """Candidates cleared for a resume, by the one policy that decides it.

    This used to apply a second gate of its own on top of `approved`: a
    candidate also had to look "explicitly reviewed", judged from record fields
    (`reviewStatus`, `reviewed`) that nothing in this application writes. With
    every record carrying `reviewStatus: None`, the two gates in series admitted
    nothing at all. `approved` now carries the whole policy — see
    `story_index.resume_approval_state` — so there is one gate and it is
    visible to the user in the corpus browser.
    """
    return [c for c in _candidates(records) if c["approved"]]


def _skill_relevance(item: str, posting_tags: frozenset[str], posting_words: frozenset[str], posting_text: str) -> int:
    """How strongly one skill speaks to this posting. Higher sorts earlier.

    Three tiers, strongest first: the posting names this exact technology
    through the controlled vocabulary (so "EKS" in the posting reaches
    "Kubernetes" in the skills line); the posting contains the skill's own
    wording verbatim; or the posting merely shares a distinctive word with it.
    """
    tags = flat_tags(item)
    if tags and tags & posting_tags:
        return 3
    if len(item) > 2 and item.casefold() in posting_text:
        return 2
    terms = words(item)
    if terms and terms & posting_words:
        return 1
    return 0


def skills_order(baseline: dict, description: str, title: str = "", *, fit_check=None) -> list[dict]:
    """Re-order each SKILLS line so what the posting asks for comes first.

    This is the cheapest honest improvement available and it was not being made
    at all: the Skills section is a list, not prose, so putting the technologies
    a posting names at the front of their line costs nothing and is the first
    thing a keyword screen reads. Crucially it is a *permutation* — every skill
    on the line stays on the line, and none is added — so there is no way for it
    to claim something the candidate has not.

    A re-ordered line is only accepted if it still fits the approved
    typography; item widths differ, so a permutation can wrap differently.
    """
    from app.services.resume_intelligence.baseline_document import fits, pack_to_fit, skills_runs

    fit_check = fit_check or fits
    posting = f"{title}\n{description}"
    posting_tags = frozenset(flat_tags(posting))
    posting_words = words(posting)
    posting_text = posting.casefold()
    result = []
    for entry in baseline.get("skills") or []:
        items = list(entry["items"])
        scored = sorted(
            range(len(items)),
            key=lambda i: (-_skill_relevance(items[i], posting_tags, posting_words, posting_text), i),
        )
        ordered = [items[i] for i in scored]
        matched = [item for item in items if _skill_relevance(item, posting_tags, posting_words, posting_text) > 0]
        decision = {"id": entry["id"], "label": entry["label"], "original": items,
                    "items": ordered, "matched": matched, "decision": "KEEP",
                    "reason": "Already leads with what this posting asks for."}
        if ordered != items:
            runs = skills_runs(entry, ordered)
            if not (runs and fit_check(entry, runs)):
                # The relevance order costs a line the approved layout has not
                # got. Repair the order instead of abandoning it.
                packed = pack_to_fit(entry, ordered, skills_runs, fit_check)
                ordered = packed if packed else items
                runs = skills_runs(entry, ordered) if packed else None
                decision["items"] = ordered
                decision["packed"] = bool(packed)
            if runs and ordered != items and fit_check(entry, runs):
                decision.update(decision="REORDER", richText=runs,
                                reason=f"Moved {len(matched)} skill(s) this posting names to the front of the line."
                                       + (" Long entries were pushed to the back so the line still fits."
                                          if decision.get("packed") else ""))
            else:
                decision["items"] = items
                decision["reason"] = "No better order fits the approved line; original kept."
        logger.info(
            "resume build: skills %r %s - %s",
            entry["label"], decision["decision"], decision["reason"],
        )
        if decision["decision"] == "REORDER":
            logger.debug("resume build: skills %r now leads with %s",
                         entry["label"], ", ".join(ordered[:6]))
        result.append(decision)
    return result


def _evidence_coverage(description: str, title: str, config: TailoringConfig) -> dict:
    """What this posting asks for that the corpus can and cannot evidence.

    Delegates to the story index, which answers the question at the level of a
    skill rather than a word: it knows that a posting saying "EKS" is asking
    about Kubernetes, and that a requirement nothing in the corpus speaks to is
    uncovered no matter how many of its words appear elsewhere on the page.
    `uncovered` is the actionable half — the per-posting form of what
    RESUME-GAPS.md reports across the whole index.
    """
    try:
        from app.services.story_index import get_index

        index = get_index()
        matches = index.select(description, title=title, limit=int(config.story_retrieval_limit))
        coverage = index.coverage(matches, description, title)
    except Exception:
        return {"percent": None, "kind": "unavailable", "covered": [], "uncovered": [],
                "stories": [], "detail": "The evidence index could not be read."}
    # `weightedCoverage` is a 0..1 share weighted by how much each requirement
    # separates candidates, which is the number worth showing; the raw
    # covered/uncovered lists are what makes it actionable.
    weighted = coverage.get("weightedCoverage")
    return {
        "percent": round(100 * float(weighted), 1) if isinstance(weighted, (int, float)) else None,
        "kind": "evidence-coverage",
        "requirements": coverage.get("requirements") or [],
        "covered": coverage.get("covered") or [],
        "uncovered": coverage.get("uncovered") or [],
        "stories": [m.story.id for m in matches],
        "detail": "Share of what this posting asks for that your recorded evidence can support.",
    }


def tailor(records, description, title="", *, baseline=None, config=None, fit_check=None, mode="honest"):
    baseline = baseline or load_baseline()
    if mode not in MODES:
        raise ValueError("Choose off, honest, or aggressive tailoring.")
    config = config or mode_config(mode)
    if mode == "off":
        config = replace(config,use_semantic=False,weak_relevance=0,max_replacement_fraction=0,reorder_threshold=1)
    fit_check = fit_check or fits
    reorder_skills = mode != "off"
    from app.services.resume_intelligence.evidence_match import extract_requirements
    reqs = extract_requirements(description)
    for req in reqs:
        req["tags"] = sorted(flat_tags(req["text"]))
    incumbents = [{"id": b["id"], "baselineBulletId": b["id"], "company": b["company"], "role": b["role"],
                   "project": b["project"], "optimizedBullet": b["text"], "original": b["text"],
                   "richText": deepcopy(b["richText"]), "source": b["source"], "approved": True,
                   "evidenceTier": "professional" if b["company"] else "personal-project", "doNotClaim": []}
                  for b in baseline["bullets"]]
    logger.info(
        "resume build: mode=%s baseline=%s slots=%d requirements=%d records=%d title=%r",
        mode, baseline["revision"], len(incumbents), len(reqs), len(records), title,
    )
    baseline_scores, _, _ = _rank(incumbents, reqs, config)
    weak = {i for i, value in enumerate(baseline_scores) if value < config.weak_relevance}
    logger.info(
        "resume build: %d/%d slots are weak (relevance < %.2f); baseline relevance %.3f-%.3f",
        len(weak), len(incumbents), config.weak_relevance,
        min(baseline_scores, default=0.0), max(baseline_scores, default=0.0),
    )
    # Do not even enumerate narrative/corpus candidates unless a weak slot exists.
    alternatives = _reviewed_candidates(records) if weak else []
    # Which stories the index picks for this posting, used to rank the
    # candidates drawn from them.
    story_scores = story_relevance(description, title, config) if alternatives else {}
    if not alternatives:
        logger.info("resume build: no eligible evidence in the pool%s",
                    "" if weak else " (and no weak slot to fill)")
    else:
        logger.info(
            "resume build: %d eligible candidates from %d stories the index ranked for this posting",
            len(alternatives), len(story_scores),
        )
    rejected: dict[str, int] = {reason: 0 for reason in REJECTION_REASONS}
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
        # The story this sentence came from, as the index ranked it for this
        # posting. An incumbent baseline bullet has no story behind it, so it
        # neither gains nor loses by this term.
        story = story_scores.get(str(c.get("source", {}).get("storyId") or "")) or 0.0
        value = config.mmr_lambda * (
            .75 * scores[i] + .20 * q + .05 * _priority(c) / 4 + config.story_index_weight * story
        )
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
            rejected["slot-not-weak" if i not in weak else "gain-below-threshold"] += 1
            continue
        options = []
        for j in range(len(incumbents), len(pool)):
            candidate = pool[j]
            if candidate["company"].casefold().strip() != slot["company"].casefold().strip():
                rejected["company-mismatch"] += 1
                continue
            if slot["company"]:
                if candidate["role"] and candidate["role"].casefold().strip() != slot["role"].casefold().strip():
                    rejected["role-mismatch"] += 1
                    continue
                employer_groups = {b["group"] for b in baseline["bullets"] if b["company"].casefold() == slot["company"].casefold()}
                if not candidate["role"] and len(employer_groups) != 1:
                    rejected["ambiguous-employer-role"] += 1
                    continue  # Employer-only records are safe only for an unambiguous role.
            if not slot["company"] and candidate["project"].casefold().strip() != slot["project"].casefold().strip():
                rejected["project-mismatch"] += 1
                continue
            if not candidate["approved"] or candidate["evidenceTier"] != item["evidenceTier"]:
                rejected["tier-or-approval"] += 1
                continue
            if asserts_forbidden_claim(candidate):
                rejected["restates-a-caution"] += 1
                logger.debug("resume build: %s refused for %s - restates a caution",
                             _brief(candidate["optimizedBullet"]), slot["id"])
                continue
            if any(candidate["optimizedBullet"] == o["optimizedBullet"] for o in selected):
                rejected["duplicate-text"] += 1
                continue
            if any(o.get("decision") == "REPLACE" and o["id"] == candidate["id"] for o in selected):
                rejected["same-accomplishment-already-used"] += 1
                continue  # Different variants of one accomplishment are not two achievements.
            value = utility(j, others)
            gain = value - base
            if scores[j] <= scores[i]:
                rejected["ranks-below-incumbent"] += 1
                continue
            if gain <= max(abs(base), .1) * config.replacement_threshold:
                rejected["gain-below-threshold"] += 1
                logger.debug(
                    "resume build: %s refused for %s - gain %.4f <= threshold %.4f",
                    _brief(candidate["optimizedBullet"]), slot["id"], gain,
                    max(abs(base), .1) * config.replacement_threshold,
                )
                continue
            runs = replacement_runs(candidate["optimizedBullet"], slot)
            # Per-slot first, so anything that already fitted is unchanged. Only
            # then ask whether the slots changing around this one can pool their
            # lines to take a slightly longer bullet.
            reflowed = False
            if not fit_check(slot, runs):
                pending = {item["baselineBulletId"]: item["richText"]
                           for item in selected if item.get("decision") == "REPLACE"}
                if not reflow_fits(baseline, slot, runs, pending):
                    rejected["does-not-fit"] += 1
                    logger.debug("resume build: %s refused for %s - does not fit the approved layout",
                                 _brief(candidate["optimizedBullet"]), slot["id"])
                    continue
                reflowed = True
            options.append((_priority(candidate), value, j, runs, gain, reflowed))
        if options:
            _, value, j, runs, gain, reflowed = max(options, key=lambda o: (o[0], o[1], -o[2]))
            selected[i] = {**deepcopy(pool[j]), "original": slot["text"], "baselineBulletId": slot["id"],
                           "richText": runs, "decision": "REPLACE", "requirementIds": matches[j],
                           "reflowed": reflowed,
                           "selectionReason": f"Weak slot replaced with exact source evidence; utility improves {gain / max(abs(base), .1):.0%} after retention and replacement costs."
                                              + (" The bullets changing in this role pooled their lines to fit it." if reflowed else ""),
                           "debug": {**item["debug"], "candidateUtility": value, "improvementFraction": gain / max(abs(base), .1)}}
            replaced += 1
            logger.info(
                "resume build: %s REPLACED by %r (story=%s relevance=%.3f gain=%.4f reflowed=%s)",
                slot["id"], _brief(pool[j]["optimizedBullet"]),
                pool[j].get("source", {}).get("storyId"), scores[j], gain, reflowed,
            )
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
    evidence_coverage = _evidence_coverage(description, title, config)
    skills = (skills_order(baseline, description, title, fit_check=None if fit_check is fits else fit_check)
              if reorder_skills else
              [{"id": e["id"], "label": e["label"], "original": list(e["items"]), "items": list(e["items"]),
                "matched": [], "decision": "KEEP", "reason": "OFF preserves the approved resume exactly."}
               for e in (baseline.get("skills") or [])])
    warnings = [] if description.strip() else ["A full job description is required before export."]
    changed_count = sum(item["decision"] != "KEEP" for item in selected)
    reordered_skills = sum(1 for entry in skills if entry["decision"] == "REORDER")
    skills_note = f" {reordered_skills} skills line(s) re-ordered to lead with what the posting names." if reordered_skills else ""
    explanation = ("OFF returns the approved resume unchanged." if mode == "off" else
        f"{changed_count} bullets moved or replaced using source-backed evidence.{skills_note}" if changed_count else
        f"No bullet change met the configured threshold.{skills_note}" if reordered_skills else
        "No safe improvement met the configured threshold and layout constraints.")
    if mode != "off" and not alternatives and weak:
        explanation += " No approved replacement evidence is available; review accomplishments before enabling replacements."
    result = {"tailoringSummary": explanation, "eligibleReplacementCount": len(alternatives), "method": VERSION, "mode": mode, "baselineRevision": baseline["revision"], "baselineFilename": baseline["filename"],
              "targetRoleMatched": title, "resumeBullets": selected, "requirements": reqs,
              "uncoveredRequirements": [r for r in reqs if r["coverageStatus"] != "covered"],
              # Headline coverage is now what the corpus can actually evidence
              # for this posting, from the story index's controlled vocabulary.
              # The old number counted how many of a requirement's words
              # happened to appear in the chosen bullets, which reported 25-40%
              # for every posting and told the user nothing.
              "requirementCoverage": evidence_coverage["percent"],
              "lexicalWordCoverage": round(100 * sum(r["weight"] * r["coverageFraction"] for r in reqs) / max(1, sum(r["weight"] for r in reqs)), 1),
              "evidenceCoverage": evidence_coverage,
              "unevidencedRequirements": evidence_coverage["uncovered"],
              "skillsOrder": skills,
              "skillsReordered": sum(1 for entry in skills if entry["decision"] == "REORDER"),
              "scoreKind": evidence_coverage["kind"], "atsMatchScore": None, "skillsList": [],
              "warnings": warnings, "exportReady": not warnings, "maxPages": 1, "provenance": "approved-baseline-and-source-records",
              "overallCritique": "Preserved the approved resume; only material, source-backed changes are eligible. Coverage is diagnostic.",
              "decisions": [{"slotId": b["id"], "baselineBulletId": c["baselineBulletId"], "decision": c["decision"], "reason": c["selectionReason"]} for b, c in zip(baseline["bullets"], selected)],
              "retentionFraction": (len(selected)-replaced)/len(selected), "tailoringConfig": asdict(config),
              "rankingDebug": {"semanticAvailable": vectors is not None, "bm25K1": config.bm25_k1, "bm25B": config.bm25_b, "rrfK": config.rrf_k, "mmrLambda": config.mmr_lambda}}
    logger.info(
        "resume build: done - %d kept, %d reordered, %d replaced, %d/%d skills lines reordered, "
        "evidence coverage %s%%, %d requirements unevidenced",
        sum(1 for item in selected if item["decision"] == "KEEP"),
        sum(1 for item in selected if item["decision"] == "REORDER"),
        replaced, reordered_skills, len(skills),
        evidence_coverage.get("percent"), len(evidence_coverage.get("uncovered") or []),
    )
    if any(rejected.values()):
        logger.info("resume build: candidates refused - %s",
                    ", ".join(f"{reason}={count}" for reason, count in rejected.items() if count))
    if evidence_coverage.get("uncovered"):
        logger.info("resume build: nothing in the corpus evidences %s",
                    ", ".join(evidence_coverage["uncovered"][:12]))
    result["rejectionCounts"] = {reason: count for reason, count in rejected.items() if count}
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
        elif not any(c["source"] == item.get("source") and c["approved"] and not asserts_forbidden_claim(c) and
                     all(c[k] == item.get(k) for k in ("optimizedBullet", "company", "role", "project", "evidenceTier")) for c in _reviewed_candidates(records)):
            problems.append("Replacement evidence changed; regenerate.")
    approved_skills = {entry["id"]: entry["items"] for entry in (baseline.get("skills") or [])}
    for entry in result.get("skillsOrder") or []:
        original = approved_skills.get(entry.get("id"))
        if original is None or sorted(entry.get("items") or []) != sorted(original):
            problems.append("Skills lines must keep exactly the approved skills; regenerate.")
            break
    return list(dict.fromkeys(problems))
