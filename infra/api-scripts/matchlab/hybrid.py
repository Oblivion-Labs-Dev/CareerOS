"""Experiment 9: features into a small trained model, instead of a hand-tuned formula.

The argument for this is calibration rather than accuracy. A similarity score -
from BM25, an embedding, or a 7B model - has no fixed meaning, which is why the
submit bar had to move from 80 to 60 when the scoring model changed. A trained
classifier's output is a probability on a scale we own, so the threshold
survives changing any individual signal underneath it.

Logistic regression is implemented here rather than imported: the design target
is a model measured in kilobytes that can be read and audited, the feature count
is small, and adding scikit-learn to ship a dot product would be the wrong trade
on this machine.

Leave-one-out cross-validation throughout. With a few dozen labelled examples,
reporting training-set accuracy would be measuring memorisation.
"""

from __future__ import annotations

import argparse
import json
import math
import sys
import time
from pathlib import Path
from typing import Any, Callable

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from matchlab import approaches as A  # noqa: E402
from matchlab.dataset import ADVERSARIAL, adversarial_assertions, load_pairs  # noqa: E402
from matchlab.metrics import best_threshold, pairwise_accuracy, pr_auc, roc_auc  # noqa: E402
from matchlab.run import build_context  # noqa: E402


# ---------------------------------------------------------------------------
# Features
# ---------------------------------------------------------------------------

def feature_builders(use_neural: bool) -> dict[str, Callable]:
    builders: dict[str, Callable] = {
        "family": lambda p, c: A.role_shape_components(p, c)["family"],
        "seniority": lambda p, c: A.role_shape_components(p, c)["seniority"],
        "coverage": lambda p, c: A.role_shape_components(p, c)["coverage"],
        "bm25": lambda p, c: A.score_bm25_whole(p, c) / 100.0,
        "bm25_sectioned": lambda p, c: A.score_bm25_sectioned(p, c) / 100.0,
        "tfidf": lambda p, c: A.score_tfidf(p, c) / 100.0,
    }
    if use_neural:
        from matchlab.neural import score_minilm_whole

        builders["minilm"] = lambda p, c: score_minilm_whole(p, c) / 100.0
    return builders


def build_matrix(pairs, ctx, builders) -> tuple[list[list[float]], list[int], list[str]]:
    names = list(builders)
    rows, labels = [], []
    for pair in pairs:
        if pair.binary is None:
            continue
        # role_shape_components is recomputed per feature above; cache it once
        # per pair so the timing reflects the design rather than the harness.
        cached = A.role_shape_components(pair, ctx)
        row = []
        for name in names:
            if name in cached:
                row.append(float(cached[name]))
            else:
                row.append(float(builders[name](pair, ctx)))
        rows.append(row)
        labels.append(pair.binary)
    return rows, labels, names


# ---------------------------------------------------------------------------
# Logistic regression
# ---------------------------------------------------------------------------

def _standardise(rows: list[list[float]]) -> tuple[list[float], list[float]]:
    n = len(rows)
    width = len(rows[0])
    means = [sum(r[j] for r in rows) / n for j in range(width)]
    stds = []
    for j in range(width):
        variance = sum((r[j] - means[j]) ** 2 for r in rows) / max(1, n - 1)
        stds.append(math.sqrt(variance) or 1.0)
    return means, stds


def fit_logistic(rows, labels, *, epochs=4000, lr=0.15, l2=0.05):
    """Batch gradient descent with L2. Deterministic: fixed init, no shuffling."""
    means, stds = _standardise(rows)
    X = [[(v - means[j]) / stds[j] for j, v in enumerate(r)] for r in rows]
    n, width = len(X), len(X[0])
    weights = [0.0] * width
    bias = 0.0
    for _ in range(epochs):
        grad_w = [0.0] * width
        grad_b = 0.0
        for xi, yi in zip(X, labels):
            z = bias + sum(w * x for w, x in zip(weights, xi))
            prediction = 1.0 / (1.0 + math.exp(-max(-30.0, min(30.0, z))))
            error = prediction - yi
            for j in range(width):
                grad_w[j] += error * xi[j]
            grad_b += error
        for j in range(width):
            weights[j] -= lr * (grad_w[j] / n + l2 * weights[j])
        bias -= lr * (grad_b / n)
    return {"weights": weights, "bias": bias, "means": means, "stds": stds}


def predict(model, row: list[float]) -> float:
    z = model["bias"] + sum(
        w * ((v - m) / s)
        for w, v, m, s in zip(model["weights"], row, model["means"], model["stds"])
    )
    return 1.0 / (1.0 + math.exp(-max(-30.0, min(30.0, z))))


def leave_one_out(rows, labels) -> list[float]:
    """Honest out-of-sample scores: each point predicted by a model that never saw it."""
    predictions = []
    for index in range(len(rows)):
        train_rows = rows[:index] + rows[index + 1:]
        train_labels = labels[:index] + labels[index + 1:]
        if len(set(train_labels)) < 2:
            predictions.append(0.5)
            continue
        model = fit_logistic(train_rows, train_labels)
        predictions.append(predict(model, rows[index]))
    return predictions


# ---------------------------------------------------------------------------

def evaluate(name, scores, labels) -> dict[str, Any]:
    gate = best_threshold(scores, labels) or {}
    return {
        "approach": name,
        "rocAuc": _r(roc_auc(scores, labels)),
        "prAuc": _r(pr_auc(scores, labels)),
        "pairwise": _r(pairwise_accuracy(scores, labels)),
        "gatePrecision": gate.get("precision"),
        "gateRecall": gate.get("recall"),
        "falseAutoApplies": gate.get("falseAutoApplies"),
        "threshold": _r(gate.get("threshold"), 4),
    }


def _r(v, places=3):
    return None if v is None else round(v, places)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--jobs", type=int, default=140)
    ap.add_argument("--neural", action="store_true")
    ap.add_argument("--out", default="data/matchlab_hybrid.json")
    args = ap.parse_args()

    pairs = load_pairs(limit=args.jobs)
    ctx = build_context(pairs)
    builders = feature_builders(args.neural)

    started = time.perf_counter()
    rows, labels, names = build_matrix(pairs, ctx, builders)
    feature_seconds = time.perf_counter() - started
    print(f"{len(rows)} labelled pairs, {len(names)} features: {', '.join(names)}")
    print(f"feature extraction {1000 * feature_seconds / max(1, len(rows)):.1f}ms per job\n")

    out_of_sample = leave_one_out(rows, labels)
    results = [evaluate("hybrid-logreg (LOO-CV)", out_of_sample, labels)]

    # Ablation: drop each feature and see whether anything is lost. A feature
    # whose removal costs nothing is complexity without benefit.
    for dropped in range(len(names)):
        subset = [[v for j, v in enumerate(r) if j != dropped] for r in rows]
        results.append(evaluate(f"  without {names[dropped]}", leave_one_out(subset, labels), labels))

    # Single strongest feature, as the simplicity floor.
    for index, name in enumerate(names):
        column = [r[index] for r in rows]
        results.append(evaluate(f"  {name} alone", column, labels))

    print(f"{'model':34} {'auc':>6} {'pr':>6} {'gateP':>6} {'gateR':>6}")
    print("-" * 66)
    for row in results:
        print(f"{row['approach']:34} {_f(row['rocAuc'])} {_f(row['prAuc'])} "
              f"{_f(row['gatePrecision'])} {_f(row['gateRecall'])}")

    final = fit_logistic(rows, labels)
    weights = sorted(
        zip(names, final["weights"]), key=lambda kv: -abs(kv[1])
    )
    print("\nlearned weights (standardised, full fit):")
    for name, weight in weights:
        print(f"  {name:18} {weight:+.3f}")

    # Adversarial behaviour of the trained model.
    adversarial_rows = []
    for pair in ADVERSARIAL:
        cached = A.role_shape_components(pair, ctx)
        adversarial_rows.append([
            float(cached[n]) if n in cached else float(builders[n](pair, ctx))
            for n in names
        ])
    adversarial_scores = {p.id: predict(final, r) for p, r in zip(ADVERSARIAL, adversarial_rows)}
    print("\nadversarial:")
    passed = 0
    for case in adversarial_assertions():
        high, low = adversarial_scores[case["higher"]], adversarial_scores[case["lower"]]
        ok = high > low
        passed += ok
        print(f"  {'PASS' if ok else 'FAIL'}  {case['name']:44} "
              f"{high:.3f} vs {low:.3f}")

    Path(args.out).write_text(json.dumps({
        "generatedAt": time.strftime("%Y-%m-%d %H:%M"),
        "features": names, "labelledPairs": len(rows),
        "featureMsPerJob": round(1000 * feature_seconds / max(1, len(rows)), 2),
        "results": results,
        "weights": {n: round(w, 4) for n, w in weights},
        "adversarialPassed": passed,
        "model": {k: (v if not isinstance(v, list) else [round(x, 5) for x in v])
                  for k, v in final.items()},
    }, indent=1), encoding="utf-8")
    print(f"\nwrote {args.out}")


def _f(v) -> str:
    return "   n/a" if v is None else f"{v:6.3f}"


if __name__ == "__main__":
    main()
