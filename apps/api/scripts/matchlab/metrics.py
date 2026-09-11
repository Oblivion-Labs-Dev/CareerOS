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
