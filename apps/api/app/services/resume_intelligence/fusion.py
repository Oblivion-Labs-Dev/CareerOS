"""Reciprocal Rank Fusion: combine ranked lists from incompatible scoring
scales (BM25's unbounded term-weight sum vs. cosine similarity in [-1, 1])
without mixing their raw scores. Only rank position matters.
"""
from __future__ import annotations

DEFAULT_K = 60


def reciprocal_rank_fusion(ranked_lists: list[list[int]], *, k: int = DEFAULT_K) -> dict[int, float]:
    """ranked_lists: each a list of item indices, best first. Returns index -> fused score."""
    scores: dict[int, float] = {}
    for ranked in ranked_lists:
        for position, item in enumerate(ranked):
            scores[item] = scores.get(item, 0.0) + 1.0 / (k + position + 1)
    return scores
