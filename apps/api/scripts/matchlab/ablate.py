"""Which parts of the role-shape scorer actually earn their place?

A composite that scores well tells you nothing about whether every component
contributed. This runs every subset of the signals over the same evaluation set,
so the simplest configuration that holds the gate can be chosen on evidence.

It also sweeps the evidence-tier parameter rather than asserting it, because
hard-coding a multiplier and declaring success is not a measurement.
"""

from __future__ import annotations

import argparse
import itertools
import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from matchlab import approaches as A  # noqa: E402
from matchlab.dataset import ADVERSARIAL, adversarial_assertions, load_pairs  # noqa: E402
from matchlab.metrics import (  # noqa: E402
    best_threshold,
    pairwise_accuracy,
    pr_auc,
    roc_auc,
)
from matchlab.run import build_context  # noqa: E402

SIGNALS = ("family", "seniority", "coverage", "bm25")


def score_with(subset: tuple[str, ...], pair, ctx) -> float:
    parts = A.role_shape_components(pair, ctx)
    weights = {k: A.ROLE_SHAPE_WEIGHTS[k] for k in subset}
    total = sum(weights.values()) or 1.0
    return 100.0 * sum(weights[k] * parts[k] for k in subset) / total


def evaluate(subset, pairs, ctx) -> dict:
    scores = [score_with(subset, p, ctx) for p in pairs]
    labels = [p.binary for p in pairs]
    gate = best_threshold(scores, labels) or {}

    adversarial = {p.id: score_with(subset, p, ctx) for p in ADVERSARIAL}
    passed = sum(
        1 for c in adversarial_assertions()
        if adversarial[c["higher"]] > adversarial[c["lower"]]
    )
    return {
        "signals": list(subset),
        "rocAuc": _r(roc_auc(scores, labels)),
        "prAuc": _r(pr_auc(scores, labels)),
        "pairwise": _r(pairwise_accuracy(scores, labels)),
        "gatePrecision": gate.get("precision"),
        "gateRecall": gate.get("recall"),
        "falseAutoApplies": gate.get("falseAutoApplies"),
        "adversarialPassed": passed,
    }


def _r(v):
    return None if v is None else round(v, 3)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--jobs", type=int, default=140)
    ap.add_argument("--out", default="data/matchlab_ablation.json")
    args = ap.parse_args()

    pairs = load_pairs(limit=args.jobs)
    ctx = build_context(pairs)
    gradable = sum(1 for p in pairs if p.binary is not None)
    print(f"ablation over {len(pairs)} jobs ({gradable} gradable)\n")

    rows = []
    for size in range(1, len(SIGNALS) + 1):
        for subset in itertools.combinations(SIGNALS, size):
            rows.append(evaluate(subset, pairs, ctx))

    rows.sort(key=lambda r: (-(r["rocAuc"] or 0), len(r["signals"])))
    print(f"{'signals':44} {'auc':>6} {'pr':>6} {'gateP':>6} {'gateR':>6} {'adv':>4}")
    print("-" * 80)
    for row in rows:
        print(f"{'+'.join(row['signals']):44} {_f(row['rocAuc'])} {_f(row['prAuc'])} "
              f"{_f(row['gatePrecision'])} {_f(row['gateRecall'])} "
              f"{row['adversarialPassed']:>3}/3")

    # Parameter sweep: does the professional-vs-project weighting matter, and
    # where? Asserting 0.45 without measuring it would be exactly the mistake
    # the brief warns against.
    print("\nevidence-tier sweep (project weight, professional fixed at 1.0):")
    sweep = []
    original = dict(ctx.tiers)
    for project_weight in (0.0, 0.15, 0.3, 0.45, 0.6, 0.8, 1.0):
        ctx.tiers = {**original, "project": project_weight}
        result = evaluate(SIGNALS, pairs, ctx)
        sweep.append({"projectWeight": project_weight, **result})
        print(f"  project={project_weight:<5} auc={_f(result['rocAuc'])} "
              f"pr={_f(result['prAuc'])} gateR={_f(result['gateRecall'])} "
              f"adv={result['adversarialPassed']}/3")
    ctx.tiers = original

    Path(args.out).write_text(json.dumps({
        "generatedAt": time.strftime("%Y-%m-%d %H:%M"),
        "jobs": len(pairs), "gradable": gradable,
        "subsets": rows, "tierSweep": sweep,
    }, indent=1), encoding="utf-8")
    print(f"\nwrote {args.out}")


def _f(v) -> str:
    return "   n/a" if v is None else f"{v:6.3f}"


if __name__ == "__main__":
    main()
