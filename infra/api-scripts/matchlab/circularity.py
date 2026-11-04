"""Is the role-shape result real, or an artefact of title-derived labels?

The concern, and it is the right one to raise: bootstrap labels come from the
job title, and role-family detection reads the job title. A feature that shares
its input with the label generator can score well by reconstructing the labeller
rather than by understanding the job. If that is what happened, 0.95 AUC means
very little.

This measures it directly, without needing human labels yet, by starving the
scorer of the information the labeller used:

    full        title + body            (what we reported)
    body-only   body, title withheld    (cannot see what the labeller saw)
    title-only  title, body withheld    (pure reconstruction of the labeller)

If body-only stays strong, role family is being recovered from how the job is
described and the signal is real. If body-only collapses to chance while
title-only stays high, the result is circular and the number is meaningless.

This is not a substitute for human labels. It is the cheap test that says
whether human labelling is worth the effort, and which way the bias runs.
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from matchlab import approaches as A  # noqa: E402
from matchlab.dataset import load_pairs  # noqa: E402
from matchlab.metrics import best_threshold, pr_auc, roc_auc  # noqa: E402
from matchlab.run import build_context  # noqa: E402
from matchlab.structure import detect_role_family, family_affinity  # noqa: E402


def family_score(pair, ctx, *, use_title: bool, use_body: bool) -> float:
    """Role-family affinity computed from a restricted view of the posting."""
    title = pair.title if use_title else ""
    body = pair.description if use_body else ""
    family, _ = detect_role_family(title, body)
    return 100.0 * family_affinity(family, ctx.resume_family)


def full_score(pair, ctx, *, use_title: bool, use_body: bool) -> float:
    """The whole role-shape scorer under the same restriction."""
    from matchlab.dataset import Pair

    view = Pair(
        id=pair.id, company=pair.company,
        title=pair.title if use_title else "Software Engineer",
        description=pair.description if use_body else "",
        label=pair.label,
    )
    return A.score_role_shape(view, ctx)


def evaluate(name, scores, labels) -> dict:
    gate = best_threshold(scores, labels) or {}
    return {
        "view": name,
        "rocAuc": _r(roc_auc(scores, labels)),
        "prAuc": _r(pr_auc(scores, labels)),
        "gatePrecision": gate.get("precision"),
        "gateRecall": gate.get("recall"),
    }


def _r(v):
    return None if v is None else round(v, 3)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--jobs", type=int, default=140)
    ap.add_argument("--out", default="data/matchlab_circularity.json")
    args = ap.parse_args()

    pairs = [p for p in load_pairs(limit=args.jobs) if p.binary is not None]
    ctx = build_context(pairs)
    labels = [p.binary for p in pairs]
    print(f"{len(pairs)} gradable postings "
          f"({sum(labels)} APPLY, {len(labels) - sum(labels)} SKIP)\n")

    views = [
        ("title + body", True, True),
        ("body only", False, True),
        ("title only", True, False),
    ]

    rows = []
    print(f"{'view':16} {'family-only':>26}   {'full role-shape':>26}")
    print(f"{'':16} {'auc':>7}{'pr':>7}{'gateR':>7}   {'auc':>7}{'pr':>7}{'gateR':>7}")
    print("-" * 74)
    for name, use_title, use_body in views:
        fam = evaluate(name, [family_score(p, ctx, use_title=use_title, use_body=use_body)
                              for p in pairs], labels)
        whole = evaluate(name, [full_score(p, ctx, use_title=use_title, use_body=use_body)
                                for p in pairs], labels)
        rows.append({"view": name, "familyOnly": fam, "roleShape": whole})
        print(f"{name:16} {_f(fam['rocAuc'])}{_f(fam['prAuc'])}{_f(fam['gateRecall'])}   "
              f"{_f(whole['rocAuc'])}{_f(whole['prAuc'])}{_f(whole['gateRecall'])}")

    body = next(r for r in rows if r["view"] == "body only")
    title = next(r for r in rows if r["view"] == "title only")
    full = next(r for r in rows if r["view"] == "title + body")

    print("\ninterpretation:")
    body_auc = body["roleShape"]["rocAuc"] or 0
    title_auc = title["roleShape"]["rocAuc"] or 0
    full_auc = full["roleShape"]["rocAuc"] or 0

    # Two independent questions, and an earlier version of this only asked the
    # first - which let a clearly circular result be reported as "not primarily
    # circular" because body-only happened to clear a threshold.
    #
    # 1. Is there signal beyond the title?      body-only vs chance
    # 2. Is the headline number inflated?       title-only vs title+body
    #
    # The second is the actual circularity test. A scorer that does BETTER
    # without the body than with it is not understanding jobs; it is
    # reconstructing the labeller, and the extra information is only noise to
    # it.
    real_signal = body_auc >= 0.70
    inflated = title_auc >= full_auc - 0.005

    if real_signal:
        print(f"  Real signal: body-only reaches {body_auc:.3f} with the title withheld,")
        print("  well above chance. Role family is recoverable from how the work is")
        print("  described, so the feature is measuring something.")
    else:
        print(f"  Weak signal: body-only is {body_auc:.3f}. Without the title there is")
        print("  little left, so the feature may be mostly reading the labeller's input.")

    if inflated:
        print(f"\n  BUT INFLATED: title-only ({title_auc:.3f}) scores at or above")
        print(f"  title+body ({full_auc:.3f}). Adding the job description makes the")
        print("  scorer WORSE, which only happens when the label is a function of the")
        print("  title. The headline number is optimistic; the honest estimate of")
        print(f"  out-of-distribution performance is nearer body-only ({body_auc:.3f}).")
        print("  Human labels are required before this number can be trusted.")
    else:
        print(f"\n  Not inflated: title-only ({title_auc:.3f}) sits below title+body")
        print(f"  ({full_auc:.3f}), so the description is contributing rather than")
        print("  interfering. Circularity is unlikely to be driving the result.")

    Path(args.out).write_text(json.dumps({
        "generatedAt": time.strftime("%Y-%m-%d %H:%M"),
        "gradablePairs": len(pairs), "views": rows,
    }, indent=1), encoding="utf-8")
    print(f"\nwrote {args.out}")


def _f(v) -> str:
    return "    n/a" if v is None else f"{v:7.3f}"


if __name__ == "__main__":
    main()
