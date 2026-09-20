"""Ranking and gate metrics, in pure Python.

No numpy, deliberately: the evaluation sets here are tens of items, the formulas
are short, and adding a dependency to compute an average would be a poor trade
on a machine this constrained.

The metric that decides the architecture is `precision_at_threshold` for the
AUTO APPLY gate, not accuracy. Sending a good job to REVIEW costs the user a
click. Auto-submitting a bad application costs a real opportunity and cannot be
undone, so the two errors are not interchangeable and must not be averaged into
one number.
"""

from __future__ import annotations

import math
import statistics
from dataclasses import dataclass, field
from typing import Any


def roc_auc(scores: list[float], labels: list[int]) -> float | None:
    """Probability a random positive outranks a random negative.

    Computed by rank-sum rather than by sweeping thresholds so ties are handled
    correctly - several approaches here produce heavily tied scores, and a
    naive sweep silently rewards that.
    """
    pairs = [(s, l) for s, l in zip(scores, labels) if s is not None and l is not None]
    pos = [s for s, l in pairs if l == 1]
    neg = [s for s, l in pairs if l == 0]
    if not pos or not neg:
        return None
    ranked = sorted(pairs, key=lambda p: p[0])
    ranks: dict[int, float] = {}
    i = 0
    while i < len(ranked):
        j = i
        while j + 1 < len(ranked) and ranked[j + 1][0] == ranked[i][0]:
            j += 1
        average_rank = (i + j) / 2 + 1
        for k in range(i, j + 1):
            ranks[k] = average_rank
        i = j + 1
    rank_sum = sum(ranks[k] for k, (_, l) in enumerate(ranked) if l == 1)
    return (rank_sum - len(pos) * (len(pos) + 1) / 2) / (len(pos) * len(neg))


def pr_auc(scores: list[float], labels: list[int]) -> float | None:
    """Average precision. More informative than ROC when positives are rare."""
    pairs = sorted(
        [(s, l) for s, l in zip(scores, labels) if s is not None and l is not None],
        key=lambda p: -p[0],
    )
    total_pos = sum(1 for _, l in pairs if l == 1)
    if not total_pos:
        return None
    hits = 0
    summed = 0.0
    for index, (_, label) in enumerate(pairs, start=1):
        if label == 1:
            hits += 1
            summed += hits / index
    return summed / total_pos


def pairwise_accuracy(scores: list[float], labels: list[int]) -> float | None:
    """Share of positive/negative pairs ordered correctly. Ties count as half."""
    pairs = [(s, l) for s, l in zip(scores, labels) if s is not None and l is not None]
    pos = [s for s, l in pairs if l == 1]
    neg = [s for s, l in pairs if l == 0]
    if not pos or not neg:
        return None
    wins = sum((1.0 if p > n else 0.5 if p == n else 0.0) for p in pos for n in neg)
    return wins / (len(pos) * len(neg))


def precision_at_threshold(scores, labels, threshold: float) -> dict[str, Any]:
    """What the AUTO APPLY gate would actually do at this threshold."""
    known = [(s, l) for s, l in zip(scores, labels) if s is not None and l is not None]
    applied = [(s, l) for s, l in known if s >= threshold]
    skipped = [(s, l) for s, l in known if s < threshold]
    total_pos = sum(1 for _, l in known if l == 1)
    true_apply = sum(1 for _, l in applied if l == 1)
    false_apply = sum(1 for _, l in applied if l == 0)
    false_skip = sum(1 for _, l in skipped if l == 1)
    return {
        "threshold": threshold,
        "applied": len(applied),
        "precision": round(true_apply / len(applied), 3) if applied else None,
        "recall": round(true_apply / total_pos, 3) if total_pos else None,
        "falseAutoApplies": false_apply,
        "falseSkips": false_skip,
    }


def best_threshold(scores, labels, *, min_precision: float = 1.0) -> dict[str, Any] | None:
    """Lowest threshold that still holds the precision floor.

    Lowest rather than highest on purpose: among thresholds that never
    auto-apply to a bad job, the one that admits the most good ones is best.
    A perfect-precision gate that fires on nothing is useless.
    """
    candidates = sorted({s for s in scores if s is not None})
    best = None
    for t in candidates:
        result = precision_at_threshold(scores, labels, t)
        if result["precision"] is not None and result["precision"] >= min_precision:
            if best is None or (result["recall"] or 0) > (best["recall"] or 0):
                best = result
    return best


@dataclass
class Report:
    name: str
    scores: list[float] = field(default_factory=list)
    labels: list[int] = field(default_factory=list)
    latencies: list[float] = field(default_factory=list)
    failures: int = 0
    resources: dict[str, Any] = field(default_factory=dict)
    notes: list[str] = field(default_factory=list)

    def summary(self, *, apply_threshold: float | None = None) -> dict[str, Any]:
        graded = [(s, l) for s, l in zip(self.scores, self.labels)
                  if s is not None and l is not None]
        latency = statistics.mean(self.latencies) if self.latencies else None
        gate = (
            precision_at_threshold(self.scores, self.labels, apply_threshold)
            if apply_threshold is not None else best_threshold(self.scores, self.labels)
        )
        return {
            "approach": self.name,
            "n": len(graded),
            "failures": self.failures,
            "rocAuc": _round(roc_auc(self.scores, self.labels)),
            "prAuc": _round(pr_auc(self.scores, self.labels)),
            "pairwise": _round(pairwise_accuracy(self.scores, self.labels)),
            "gate": gate,
            "latencyMs": round(latency * 1000, 1) if latency else None,
            "jobsPerSecond": round(1 / latency, 1) if latency else None,
            "rescore851Seconds": round(851 * latency, 1) if latency else None,
            **self.resources,
            "notes": self.notes,
        }


def _round(value: float | None, places: int = 3) -> float | None:
    return None if value is None else round(value, places)


def determinism_check(runs: list[list[float]]) -> dict[str, Any]:
    """Are repeated runs over identical input identical?

    A gate that answers differently for the same input cannot be reasoned
    about, so this is pass/fail rather than a tolerance.
    """
    if len(runs) < 2:
        return {"stable": None}
    first = runs[0]
    identical = all(r == first for r in runs[1:])
    drift = max(
        (abs(a - b) for r in runs[1:] for a, b in zip(first, r)
         if a is not None and b is not None),
        default=0.0,
    )
    return {"stable": identical, "maxDrift": round(drift, 4)}


# ---------------------------------------------------------------------------
# Ranked retrieval
# ---------------------------------------------------------------------------
# The metrics above grade one score against one binary label, which is the
# right shape for the AUTO APPLY gate. Evidence retrieval is a different
# question: given a posting, does the *ordering* put the bullets that genuinely
# support it at the top? A single AUC cannot answer that, because what matters
# is the first handful - a resume has room for a few bullets, so a retriever
# that finds everything relevant at rank 40 is useless.
#
# Precision and recall are therefore reported @k, and they pull in opposite
# directions by construction: precision@k asks "of the k I showed, how many
# were right", recall@k asks "of all the right ones, how many did I show". A
# retriever is only better if it improves one without giving back the other,
# which is why both are always printed together.


def precision_at_k(ranked_labels: list[int], k: int) -> float | None:
    """Fraction of the top k that are relevant."""
    if k <= 0 or not ranked_labels:
        return None
    top = ranked_labels[:k]
    return sum(top) / len(top)


def recall_at_k(ranked_labels: list[int], k: int) -> float | None:
    """Fraction of all relevant items that appear in the top k."""
    total = sum(ranked_labels)
    if not total:
        return None  # No relevant evidence exists; recall is undefined, not zero.
    return sum(ranked_labels[:k]) / total


def reciprocal_rank(ranked_labels: list[int]) -> float:
    """1/rank of the first relevant item, or 0 if none is retrieved."""
    for index, label in enumerate(ranked_labels, start=1):
        if label:
            return 1 / index
    return 0.0


def average_precision(ranked_labels: list[int]) -> float | None:
    """Mean of precision@k taken at every rank where a relevant item appears."""
    total = sum(ranked_labels)
    if not total:
        return None
    hits = 0
    running = 0.0
    for index, label in enumerate(ranked_labels, start=1):
        if label:
            hits += 1
            running += hits / index
    return running / total


def ndcg_at_k(ranked_labels: list[int], k: int) -> float | None:
    """Discounted gain over the best possible ordering of the same labels."""
    total = sum(ranked_labels)
    if not total or k <= 0:
        return None
    def dcg(labels: list[int]) -> float:
        return sum(label / math.log2(index + 1) for index, label in enumerate(labels[:k], start=1))
    ideal = sorted(ranked_labels, reverse=True)
    best = dcg(ideal)
    return dcg(ranked_labels) / best if best else None


@dataclass
class RetrievalReport:
    """One retriever's ranked results over a set of queries."""

    name: str
    #: One list of 0/1 labels per query, ordered by the retriever's ranking.
    rankings: list[list[int]] = field(default_factory=list)
    latencies: list[float] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)

    def summary(self, ks: tuple[int, ...] = (1, 3, 5, 10)) -> dict[str, Any]:
        graded = [r for r in self.rankings if sum(r)]
        latency = statistics.mean(self.latencies) if self.latencies else None
        out: dict[str, Any] = {
            "retriever": self.name,
            "queries": len(self.rankings),
            # Queries with no relevant evidence at all are excluded from the
            # averages rather than scored zero: they say something about the
            # corpus, not about the ranking, and counting them would make every
            # retriever look equally bad on the postings nothing can answer.
            "gradedQueries": len(graded),
        }
        for k in ks:
            precisions = [p for p in (precision_at_k(r, k) for r in graded) if p is not None]
            recalls = [r_ for r_ in (recall_at_k(r, k) for r in graded) if r_ is not None]
            out[f"p@{k}"] = _round(statistics.mean(precisions)) if precisions else None
            out[f"r@{k}"] = _round(statistics.mean(recalls)) if recalls else None
        maps = [a for a in (average_precision(r) for r in graded) if a is not None]
        ndcgs = [n for n in (ndcg_at_k(r, 10) for r in graded) if n is not None]
        out["map"] = _round(statistics.mean(maps)) if maps else None
        out["ndcg@10"] = _round(statistics.mean(ndcgs)) if ndcgs else None
        out["mrr"] = _round(statistics.mean([reciprocal_rank(r) for r in graded])) if graded else None
        out["latencyMs"] = round(latency * 1000, 1) if latency else None
        out["notes"] = self.notes
        return out
