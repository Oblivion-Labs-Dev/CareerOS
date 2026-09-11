"""Label the evaluation set with Gemini, build every label source, compare them,
and re-run the matcher against each.

No local model is loaded at any point. The only inference is an HTTPS call to
Gemini, and every response is cached permanently.

The headline experiment is the last table: body-only matching scored against
title-blind teacher labels. Neither side can see the job title, so a good score
there cannot be title circularity.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
import time
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


def _ensure_key() -> None:
    if os.environ.get("GEMINI_API_KEY", "").strip():
        return
    env = (Path(__file__).resolve().parents[2] / ".env").read_text(
        encoding="utf-8", errors="ignore"
    )
    match = re.search(r"^GEMINI_API_KEY=(.+)$", env, re.M)
    if match:
        os.environ["GEMINI_API_KEY"] = match.group(1).strip()


_ensure_key()

from matchlab import approaches as A  # noqa: E402
from matchlab import labels as L  # noqa: E402
from matchlab.dataset import Pair, load_pairs  # noqa: E402
from matchlab.metrics import best_threshold, pr_auc, roc_auc  # noqa: E402
from matchlab.run import build_context  # noqa: E402
from matchlab.teacher import TEACHER_CACHE_NOTE, build_resume_summary, judge  # noqa: E402


def order_by_uncertainty(pairs, ctx) -> list:
    """Hardest postings first, so a capped run spends its quota where it counts.

    Labelling every posting is the wrong shape for this problem. The postings
    that move an evaluation are the ones the cheap label sources disagree
    about, or that they themselves report as undecided; a posting bootstrap and
    the deterministic scorer both call SKIP teaches almost nothing and costs the
    same API call as a hard one.

    This orders rather than filters, so --jobs still controls how many get
    labelled and no posting is permanently excluded from the pool.
    """
    from matchlab.dataset import REVIEW

    bootstrap = L.bootstrap_set(pairs)
    deterministic = L.deterministic_set(pairs, ctx)

    def rank(pair):
        a = bootstrap.label_for(pair.id)
        b = deterministic.label_for(pair.id)
        if a is not None and b is not None and a != b:
            return 0            # outright disagreement: the most informative
        if a == REVIEW or b == REVIEW:
            return 1            # undecided by at least one cheap source
        return 2                # both already agree; least worth an API call

    return sorted(pairs, key=rank)


def collect_teacher(pairs, resume: str, *, offline: bool) -> dict[str, Any]:
    """Run (or load) the teacher for every posting."""
    stored: dict[str, Any] = {}
    try:
        stored = json.loads(L.TEACHER_LABELS.read_text(encoding="utf-8"))
    except Exception:
        stored = {}

    fresh = cached = failed = 0
    for index, pair in enumerate(pairs, start=1):
        if pair.id in stored:
            cached += 1
            continue
        result = judge(resume, pair.title, pair.description, allow_network=not offline)
        if result is None:
            failed += 1
            continue
        stored[pair.id] = {
            **result.to_dict(),
            "company": pair.company, "title": pair.title,
        }
        fresh += 1 if not result.cached else 0
        cached += 1 if result.cached else 0
        L.TEACHER_LABELS.write_text(json.dumps(stored, indent=1), encoding="utf-8")
        if index % 10 == 0 or fresh <= 3:
            print(f"    {index}/{len(pairs)}  {pair.company[:16]:16} "
                  f"{result.decision:6} conf={result.confidence:.2f} "
                  f"{result.primary_role_family}", flush=True)

    print(f"  teacher: {fresh} new, {cached} cached, {failed} failed")
    return stored


def score_against(label_set: L.LabelSet, pairs, ctx, *, body_only: bool) -> dict[str, Any]:
    """Run role-shape against one label source, optionally blind to the title."""
    scores, binaries = [], []
    for pair in pairs:
        binary = label_set.binary_for(pair.id)
        if binary is None:
            continue
        view = Pair(
            id=pair.id, company=pair.company,
            title="Software Engineer" if body_only else pair.title,
            description=pair.description,
        )
        scores.append(A.score_role_shape(view, ctx))
        binaries.append(binary)

    if len(set(binaries)) < 2:
        return {"labels": label_set.source, "gradable": len(binaries),
                "note": "needs both APPLY and SKIP examples"}
    gate = best_threshold(scores, binaries) or {}
    return {
        "labels": label_set.source,
        "view": "body-only" if body_only else "title+body",
        "gradable": len(binaries),
        "positives": sum(binaries),
        "rocAuc": _r(roc_auc(scores, binaries)),
        "prAuc": _r(pr_auc(scores, binaries)),
        "gatePrecision": gate.get("precision"),
        "gateRecall": gate.get("recall"),
        "falseAutoApplies": gate.get("falseAutoApplies"),
    }


def _r(v):
    return None if v is None else round(v, 3)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--jobs", type=int, default=140)
    ap.add_argument("--offline", action="store_true",
                    help="use only cached teacher responses; make no API calls")
    ap.add_argument("--uncertain-first", action="store_true", default=True,
                    help="label the postings the cheap sources disagree about first")
    ap.add_argument("--in-order", dest="uncertain_first", action="store_false",
                    help="label postings in dataset order instead")
    ap.add_argument("--out", default="data/matchlab_label_study.json")
    args = ap.parse_args()

    # Load the whole pool, then let the sampler decide which of it is worth
    # spending calls on. Taking the first N postings and ranking them afterwards
    # would mean the ranking never saw the interesting ones.
    pool = load_pairs()
    ctx = build_context(pool)
    if args.uncertain_first:
        pool = order_by_uncertainty(pool, ctx)
    pairs = pool[: args.jobs]
    print(f"{len(pairs)} postings of {len(pool)} "
          f"({'uncertainty-sampled' if args.uncertain_first else 'in dataset order'})\n")

    print("1. teacher (Gemini, title hidden)")
    resume = build_resume_summary()
    teacher_records = collect_teacher(pairs, resume, offline=args.offline)

    print("\n2. label sources")
    bootstrap = L.bootstrap_set(pairs)
    teacher = L.load_teacher_set(pairs)
    deterministic = L.deterministic_set(pairs, ctx)
    consensus = L.consensus_set(pairs, teacher, deterministic, teacher_records)
    human = L.human_set(pairs)

    for source in (bootstrap, teacher, deterministic, consensus, human):
        counts = source.counts()
        print(f"  {source.source:15} {counts['APPLY']:3} apply  "
              f"{counts['REVIEW']:3} review  {counts['SKIP']:3} skip  "
              f"{counts['UNCERTAIN']:3} uncertain")

    print("\n3. agreement between sources")
    comparisons = []
    for a, b in ((bootstrap, teacher), (bootstrap, deterministic),
                 (teacher, deterministic), (teacher, human), (consensus, human)):
        result = L.agreement(a, b)
        comparisons.append(result)
        if result.get("shared"):
            print(f"  {result['a']:14} vs {result['b']:14} "
                  f"{result['agreement']:.3f} over {result['shared']:3} shared"
                  + (f"   apply-overlap {result['applyJaccard']}"
                     if result.get("applyJaccard") is not None else ""))

    top_disagreements = [
        c for c in comparisons if c.get("shared") and c["agreement"] < 0.9
    ]
    for comparison in top_disagreements:
        print(f"\n  {comparison['a']} vs {comparison['b']} — where they differ:")
        for pattern, count in list(comparison["confusion"].items())[:5]:
            if pattern.split("->")[0] != pattern.split("->")[1]:
                print(f"    {pattern:22} {count}")

    print("\n4. matcher scored against each label source")
    print(f"  {'labels':18} {'view':12} {'n':>4} {'auc':>7} {'pr':>7} "
          f"{'gateP':>7} {'gateR':>7}")
    print("  " + "-" * 68)
    evaluations = []
    for source in (bootstrap, teacher, consensus, human):
        if not source.labels:
            continue
        merged = L.with_human_override(source, human) if source.source != "human" else source
        for body_only in (False, True):
            row = score_against(merged, pairs, ctx, body_only=body_only)
            evaluations.append(row)
            if "rocAuc" not in row:
                print(f"  {row['labels']:18} {'':12} {row['gradable']:>4}  {row['note']}")
                continue
            print(f"  {row['labels']:18} {row['view']:12} {row['gradable']:>4} "
                  f"{_f(row['rocAuc'])} {_f(row['prAuc'])} "
                  f"{_f(row['gatePrecision'])} {_f(row['gateRecall'])}")

    print("\n5. the anti-circularity result")
    blind = next(
        (e for e in evaluations
         if e.get("view") == "body-only" and e["labels"].startswith("teacher")), None
    )
    titled = next(
        (e for e in evaluations
         if e.get("view") == "title+body" and e["labels"].startswith("bootstrap")), None
    )
    if blind and "rocAuc" in blind:
        print(f"  body-only matcher vs title-blind teacher labels: "
              f"{blind['rocAuc']:.3f} AUC over {blind['gradable']} postings")
        if titled and "rocAuc" in titled:
            print(f"  for comparison, the original title-derived setup scored "
                  f"{titled['rocAuc']:.3f}")
        print("  Neither side of the first number can see the job title, so it is not")
        print("  measuring the scorer's ability to reconstruct a title-based label.")

    Path(args.out).write_text(json.dumps({
        "generatedAt": time.strftime("%Y-%m-%d %H:%M"),
        "postings": len(pairs),
        "counts": {s.source: s.counts()
                   for s in (bootstrap, teacher, deterministic, consensus, human)},
        "agreement": comparisons,
        "evaluations": evaluations,
        "uncertain": sorted(consensus.uncertain),
        "note": TEACHER_CACHE_NOTE,
    }, indent=1), encoding="utf-8")
    print(f"\nwrote {args.out}")


def _f(v) -> str:
    return "    n/a" if v is None else f"{v:7.3f}"


if __name__ == "__main__":
    main()
