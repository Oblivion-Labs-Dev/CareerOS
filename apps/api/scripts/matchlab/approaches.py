"""Candidate scorers. Every one takes a Pair and returns 0..100.

All of these are dependency-free and deterministic. Neural approaches live in a
separate module so that installing torch is a decision taken after these have
been measured, not before.
"""

from __future__ import annotations

import math
from collections import Counter
from typing import Callable

from app.services.application_assistant.role_shape_match import (  # noqa: F401
    ROLE_SHAPE_WEIGHTS,
    Context,
    Corpus,
    _scale,
    bm25,
    fit_corpus,
    role_shape_components,
    score_role_shape,
    tokenize,
)

from .dataset import Pair
from .structure import parse_job

# ---------------------------------------------------------------------------
# 1. TF-IDF cosine (tokenize, Corpus and BM25 live in role_shape_match)
# ---------------------------------------------------------------------------

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

Scorer = Callable[[Pair, Context], float]


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
# C. Role shape - the fix for the measured coverage failure. Implemented in
#    app.services.application_assistant.role_shape_match and imported above,
#    so the benchmark measures exactly what the queue runs.
# ---------------------------------------------------------------------------

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
