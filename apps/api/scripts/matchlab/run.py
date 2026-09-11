"""Run every candidate scorer over the evaluation set and report.

Reports ranking quality, gate behaviour, cost and determinism together, because
choosing on any one of them in isolation is how you end up with a 21-hour
queue rescore.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
import tracemalloc
from pathlib import Path
from typing import Any

# api root (for app.*) and scripts/ (for matchlab.*)
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from matchlab import approaches as A  # noqa: E402
from matchlab.dataset import (  # noqa: E402
    ADVERSARIAL,
    adversarial_assertions,
    apply_human_labels,
    load_pairs,
)
from matchlab.metrics import Report, determinism_check  # noqa: E402
from matchlab.structure import build_resume_shape, detect_role_family  # noqa: E402


def build_context(pairs) -> A.Context:
    from app.db.store import get_kv, session_scope
    from app.services.application_assistant.candidate_match_context import extract_resume_text
    from app.services.story_index import load_corpus

    with session_scope() as db:
        profile = get_kv(db, "profile") or {}
        documents = get_kv(db, "documents") or {}

    corpus_records = load_corpus()
    resume = build_resume_shape(corpus_records, headline=str(profile.get("headline") or ""))

    professional = " ".join(e.text for e in resume.professional)
    project = " ".join(e.text for e in resume.projects)
    resume_text = extract_resume_text(documents) or ""
    skills = " ".join(
        str(s) for s in (profile.get("skills") or [])
    ) if isinstance(profile.get("skills"), list) else str(profile.get("skills") or "")

    combined = f"{resume_text}\n{professional}\n{project}\n{skills}"

    # IDF is fitted over the postings, which is what makes common hiring
    # vocabulary cheap and specific technology expensive.
    corpus = A.fit_corpus([p.description for p in pairs] + [combined])

    family, _ = detect_role_family(
        str(profile.get("headline") or "Senior Software Engineer"), combined
    )
    return A.Context(
        corpus=corpus, resume=resume, resume_text=combined,
        resume_tokens=A.tokenize(combined),
        professional_text=professional + "\n" + resume_text,
        project_text=project, skills_text=skills,
        resume_family=family or "backend", resume_seniority=3,
    )


def run_approach(name: str, scorer, pairs, ctx, repeats: int = 2) -> Report:
    report = Report(name=name)
    tracemalloc.start()
    runs: list[list[float]] = []
    for attempt in range(repeats):
        scores: list[float] = []
        for pair in pairs:
            start = time.perf_counter()
            try:
                value = float(scorer(pair, ctx))
            except Exception as exc:  # noqa: BLE001
                if attempt == 0:
                    report.failures += 1
                    report.notes.append(f"{pair.id}: {type(exc).__name__}: {exc}"[:120])
                value = None  # type: ignore[assignment]
            elapsed = time.perf_counter() - start
            if attempt == 0:
                report.latencies.append(elapsed)
            scores.append(value)
        runs.append(scores)
    current, peak = tracemalloc.get_traced_memory()
    tracemalloc.stop()

    report.scores = runs[0]
    report.labels = [p.binary for p in pairs]
    report.resources = {
        "peakPythonMb": round(peak / 1e6, 1),
        "modelMb": 0,
        "vramMb": 0,
        **determinism_check(runs),
    }
    return report


def check_adversarial(scorer, ctx) -> list[dict[str, Any]]:
    scores = {p.id: scorer(p, ctx) for p in ADVERSARIAL}
    results = []
    for case in adversarial_assertions():
        high, low = scores[case["higher"]], scores[case["lower"]]
        results.append({
            "name": case["name"],
            "pass": high > low,
            "margin": round(high - low, 1),
            "scores": {case["higher"]: round(high, 1), case["lower"]: round(low, 1)},
        })
    return results


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--jobs", type=int, default=60)
    ap.add_argument("--only", nargs="*", default=None)
    ap.add_argument("--out", default="data/matchlab_results.json")
    ap.add_argument("--neural", action="store_true",
                    help="also run MiniLM/cross-encoder approaches (needs torch)")
    args = ap.parse_args()

    pairs = load_pairs(limit=args.jobs)
    confirmed = apply_human_labels(pairs)
    ctx = build_context(pairs)

    positives = sum(1 for p in pairs if p.binary == 1)
    print(f"evaluation set: {len(pairs)} jobs, {positives} labelled APPLY, "
          f"{confirmed} human-confirmed")
    print(f"resume role family: {ctx.resume_family}   "
          f"corpus: {ctx.corpus.document_count} docs, "
          f"avg {ctx.corpus.average_length:.0f} tokens\n")

    available = dict(A.APPROACHES)
    if args.neural:
        try:
            from matchlab.neural import NEURAL_APPROACHES

            available.update(NEURAL_APPROACHES)
        except ImportError as exc:
            print(f"neural approaches unavailable ({exc}); deterministic only\n")

    selected = {k: v for k, v in available.items()
                if not args.only or k in args.only}

    rows = []
    for name, scorer in selected.items():
        report = run_approach(name, scorer, pairs, ctx)
        summary = report.summary()
        summary["adversarial"] = check_adversarial(scorer, ctx)
        summary["adversarialPassed"] = sum(1 for a in summary["adversarial"] if a["pass"])
        rows.append(summary)
        if name.startswith(("minilm", "cross", "bge")):
            # Never leave two models resident: this machine cannot hold them,
            # and a leftover model also distorts the next approach's memory
            # measurement.
            from matchlab.neural import model_footprint, unload_all

            summary.update(model_footprint(
                "sentence-transformers/all-MiniLM-L6-v2" if name.startswith("minilm")
                else "cross-encoder/ms-marco-MiniLM-L6-v2"
            ))
            unload_all()
            ctx.cache.clear()
        gate = summary["gate"] or {}
        print(f"{name:18} auc={_f(summary['rocAuc'])} pr={_f(summary['prAuc'])} "
              f"pair={_f(summary['pairwise'])}  "
              f"gate: p={_f(gate.get('precision'))} r={_f(gate.get('recall'))} "
              f"fp={gate.get('falseAutoApplies')}  "
              f"{summary['latencyMs']:.1f}ms  adv={summary['adversarialPassed']}/3  "
              f"{'stable' if summary.get('stable') else 'UNSTABLE'}")

    Path(args.out).write_text(json.dumps({
        "generatedAt": time.strftime("%Y-%m-%d %H:%M"),
        "evaluation": {
            "jobs": len(pairs), "positives": positives,
            "humanConfirmed": confirmed,
            "resumeFamily": ctx.resume_family,
        },
        "results": rows,
    }, indent=1), encoding="utf-8")
    print(f"\nwrote {args.out}")

    print("\nadversarial detail (all approaches):")
    for row in rows:
        for case in row["adversarial"]:
            mark = "PASS" if case["pass"] else "FAIL"
            print(f"  {row['approach']:18} {mark}  {case['name']:42} "
                  f"margin {case['margin']:+.1f}  {case['scores']}")


def _f(value) -> str:
    return "  n/a" if value is None else f"{value:5.3f}"


if __name__ == "__main__":
    main()
