"""Candidate scorers. Every one takes a Pair and returns 0..100.

All of these are dependency-free and deterministic. Neural approaches live in a
separate module so that installing torch is a decision taken after these have
been measured, not before.
"""

from __future__ import annotations

import math
import re
from collections import Counter
from dataclasses import dataclass
from typing import Any, Callable

from .dataset import Pair
from .structure import (
    DEFAULT_TIERS,
    ResumeShape,
    detect_role_family,
    detect_seniority,
    family_affinity,
    parse_job,
)

_TOKEN = re.compile(r"[a-z0-9+#.]{2,}")

_STOP = frozenset("""
the and for with that this from will have are was been being our your you all can
may must should would about into through during before after above below between
each other some such than too very just also who whom what which when where why how
a an of in on at to by as is it be or if we us they them their there here not no
role team work working experience years year strong ability able help make made
join company opportunity benefits equal employer position candidate candidates
""".split())


def tokenize(text: str) -> list[str]:
    return [t for t in _TOKEN.findall(str(text or "").lower()) if t not in _STOP and len(t) > 2]


# ---------------------------------------------------------------------------
# Corpus statistics, fitted once over all postings
# ---------------------------------------------------------------------------

@dataclass
class Corpus:
    """Document frequencies fitted over the whole job corpus.

    Fitting IDF across the corpus rather than one posting is the point: it is
    what makes "Kubernetes" count for more than "engineering", automatically,
    without anyone maintaining a list of important words.
    """

    document_count: int
    document_frequency: Counter
    average_length: float

    def idf(self, term: str) -> float:
        # BM25's probabilistic IDF, with the +1 that keeps it non-negative for
        # terms appearing in more than half the corpus.
        df = self.document_frequency.get(term, 0)
        return math.log(1 + (self.document_count - df + 0.5) / (df + 0.5))

    def tfidf_idf(self, term: str) -> float:
        df = self.document_frequency.get(term, 0)
        return math.log((self.document_count + 1) / (df + 1)) + 1.0


def fit_corpus(documents: list[str]) -> Corpus:
    df = Counter()
    lengths = []
    for document in documents:
        tokens = tokenize(document)
        lengths.append(len(tokens))
        df.update(set(tokens))
    return Corpus(
        document_count=len(documents),
        document_frequency=df,
        average_length=(sum(lengths) / len(lengths)) if lengths else 1.0,
    )


# ---------------------------------------------------------------------------
# 1. BM25
# ---------------------------------------------------------------------------

def bm25(query_tokens: list[str], doc_tokens: list[str], corpus: Corpus,
         k1: float = 1.5, b: float = 0.75) -> float:
    """Standard Okapi BM25. The query is the posting, the document is the resume."""
    if not doc_tokens:
        return 0.0
    counts = Counter(doc_tokens)
    length = len(doc_tokens)
    score = 0.0
    for term in set(query_tokens):
        tf = counts.get(term, 0)
        if not tf:
            continue
        denominator = tf + k1 * (1 - b + b * length / (corpus.average_length or 1))
        score += corpus.idf(term) * (tf * (k1 + 1)) / denominator
    return score


def cosine_tfidf(a_tokens: list[str], b_tokens: list[str], corpus: Corpus) -> float:
    """TF-IDF cosine similarity, IDF fitted over the corpus."""
    if not a_tokens or not b_tokens:
        return 0.0

    def vector(tokens: list[str]) -> dict[str, float]:
        counts = Counter(tokens)
        longest = max(counts.values())
        return {
            t: (0.5 + 0.5 * c / longest) * corpus.tfidf_idf(t)
            for t, c in counts.items()
        }

    va, vb = vector(a_tokens), vector(b_tokens)
    shared = set(va) & set(vb)
    if not shared:
        return 0.0
    dot = sum(va[t] * vb[t] for t in shared)
    na = math.sqrt(sum(v * v for v in va.values()))
    nb = math.sqrt(sum(v * v for v in vb.values()))
    return dot / (na * nb) if na and nb else 0.0


# ---------------------------------------------------------------------------
# Scorer interface
# ---------------------------------------------------------------------------

@dataclass
class Context:
    """Everything a scorer may use, built once for the whole run."""

    corpus: Corpus
    resume: ResumeShape
    resume_text: str
    resume_tokens: list[str]
    professional_text: str
    project_text: str
    skills_text: str
    resume_family: str = "backend"
    resume_seniority: int = 3
    tiers: dict[str, float] = None  # type: ignore[assignment]
    #: Scratch space for anything expensive that is constant across pairs -
    #: resume embeddings above all. Computing those once rather than per job is
    #: the difference between a usable bi-encoder and a pointless one.
    cache: dict[str, Any] = None  # type: ignore[assignment]

    def __post_init__(self) -> None:
        if self.tiers is None:
            self.tiers = dict(DEFAULT_TIERS)
        if self.cache is None:
            self.cache = {}


Scorer = Callable[[Pair, Context], float]


def _scale(raw: float, ceiling: float) -> float:
    """Map an unbounded similarity onto 0..100 without clipping information away."""
    return 100.0 * (raw / (raw + ceiling)) if raw > 0 else 0.0


# ---------------------------------------------------------------------------
# A. Whole-document BM25
# ---------------------------------------------------------------------------

def score_bm25_whole(pair: Pair, ctx: Context) -> float:
    query = tokenize(f"{pair.title} {pair.description}")
    return _scale(bm25(query, ctx.resume_tokens, ctx.corpus), 40.0)


# ---------------------------------------------------------------------------
# A2. Sectioned BM25 - posting sections against matching resume sections
# ---------------------------------------------------------------------------

def score_bm25_sectioned(pair: Pair, ctx: Context) -> float:
    job = parse_job(pair.title, pair.company, pair.description)
    parts = [
        (tokenize(pair.title), tokenize(ctx.resume.headline or ctx.professional_text[:400]), 0.25),
        (tokenize(" ".join(job.must_have)), tokenize(ctx.professional_text + " " + ctx.skills_text), 0.40),
        (tokenize(" ".join(job.responsibilities)), tokenize(ctx.professional_text), 0.25),
        (tokenize(" ".join(job.preferred)), tokenize(ctx.resume_text), 0.10),
    ]
    total = 0.0
    used = 0.0
    for query, document, weight in parts:
        if not query:
            continue
        total += weight * _scale(bm25(query, document, ctx.corpus), 25.0)
        used += weight
    return total / used if used else 0.0


# ---------------------------------------------------------------------------
# B. TF-IDF cosine
# ---------------------------------------------------------------------------

def score_tfidf(pair: Pair, ctx: Context) -> float:
    query = tokenize(f"{pair.title} {pair.description}")
    return 100.0 * cosine_tfidf(query, ctx.resume_tokens, ctx.corpus)


# ---------------------------------------------------------------------------
# C. Role shape - the fix for the measured coverage failure
# ---------------------------------------------------------------------------

def role_shape_components(pair: Pair, ctx: Context) -> dict[str, float]:
    """The individual signals, exposed so ablations can turn them off."""
    job = parse_job(pair.title, pair.company, pair.description)

    affinity = family_affinity(job.role_family, ctx.resume_family)

    # Seniority: being one level under is a real mismatch, being over is mild.
    gap = job.seniority - ctx.resume_seniority
    seniority = 1.0 if gap == 0 else (0.85 if gap < 0 else max(0.0, 1.0 - 0.35 * gap))

    must_tokens = tokenize(" ".join(job.must_have)) or tokenize(pair.description)
    professional = tokenize(ctx.professional_text)
    project = tokenize(ctx.project_text)

    # Evidence is weighted by where it comes from, and rare requirements count
    # for more than common ones - that is what stops a long list of generic
    # requirements outweighing a few decisive ones.
    pro_set, proj_set = set(professional), set(project)
    weighted_hit = 0.0
    weighted_total = 0.0
    for term in set(must_tokens):
        weight = ctx.corpus.idf(term)
        weighted_total += weight
        if term in pro_set:
            weighted_hit += weight * ctx.tiers["professional"]
        elif term in proj_set:
            weighted_hit += weight * ctx.tiers["project"]
    coverage = (weighted_hit / weighted_total) if weighted_total else 0.0

    return {
        "family": affinity,
        "seniority": seniority,
        "coverage": coverage,
        "bm25": _scale(bm25(must_tokens, ctx.resume_tokens, ctx.corpus), 30.0) / 100.0,
    }


#: Initial experimental weights. Swept in the ablation, not asserted.
ROLE_SHAPE_WEIGHTS = {"family": 0.45, "seniority": 0.10, "coverage": 0.30, "bm25": 0.15}


def score_role_shape(pair: Pair, ctx: Context) -> float:
    parts = role_shape_components(pair, ctx)
    return 100.0 * sum(ROLE_SHAPE_WEIGHTS[k] * v for k, v in parts.items())


# ---------------------------------------------------------------------------
# D. The existing production-style coverage scorer, for comparison
# ---------------------------------------------------------------------------

def score_naive_coverage(pair: Pair, ctx: Context) -> float:
    """Reproduces the failing approach so the leaderboard has its baseline."""
    try:
        from app.services.story_index import get_index

        index = get_index()
        wanted = index.requirement_weights(pair.description, pair.title)
        if not wanted:
            return 0.0
        evidenced = set(index.by_tag)
        total = sum(wanted.values())
        hit = sum(w for t, w in wanted.items() if t in evidenced)
        return 100.0 * hit / total if total else 0.0
    except Exception:
        return 0.0


APPROACHES: dict[str, Scorer] = {
    "naive-coverage": score_naive_coverage,
    "bm25-whole": score_bm25_whole,
    "bm25-sectioned": score_bm25_sectioned,
    "tfidf-cosine": score_tfidf,
    "role-shape": score_role_shape,
}
