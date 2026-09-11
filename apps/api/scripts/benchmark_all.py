"""Run every CareerOS model benchmark back to back, one model resident at a time.

Three axes, because CareerOS asks models to do three different things and being
good at one does not imply being good at another:

  1. QUESTION ANSWERING - the existing 40-case suite in benchmark_dataset.py.
     The only axis with real ground truth: each case has a known correct
     classification and answer, including cases where the correct answer is to
     abstain. Gives accuracy, hallucination rate and cost per 1000 applications.

  2. RESUME SCORING     - can the model tell a fitting posting from an
     unfitting one, and does it give the same answer twice.

  3. RESUME TAILORING   - can the model rewrite 17 bullets into something that
     passes the submission gate, plus a prompt-shape sweep.

Run sequentially rather than in parallel: this machine holds one model at a
time, and the two suites would otherwise evict each other's model between every
case.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import subprocess
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
API_ROOT = HERE.parent
sys.path.insert(0, str(API_ROOT))

MODELS = [
    "qwen2.5:3b",
    "qwen3:4b-instruct",
    "mistral:7b-instruct",
    "qwen3:8b",
    "gemma3:12b",
]


async def run_question_suite(models: list[str], out: Path) -> None:
    from app.services.application_assistant.benchmark_suite import (
        run_full_sequential_benchmark,
    )

    print("=" * 78)
    print("AXIS 1/3: application-question answering (40 ground-truth cases)")
    print("=" * 78, flush=True)
    await run_full_sequential_benchmark(
        gemini_api_key="",  # local models only; no cloud call from this run
        models_to_test=[{"model": m, "provider": "ollama"} for m in models],
        output_path=str(out),
    )
    print(f"\nwrote {out}", flush=True)


def run_resume_suite(models: list[str], out: Path, variant_model: str,
                     scoring_cases: int, tailoring_jobs: int) -> None:
    print("\n" + "=" * 78)
    print("AXIS 2+3/3: resume scoring, resume tailoring, prompt variants")
    print("=" * 78, flush=True)
    cmd = [
        sys.executable, str(HERE / "benchmark_models.py"),
        "--models", *models,
        "--scoring-cases", str(scoring_cases),
        "--tailoring-jobs", str(tailoring_jobs),
        "--variant-model", variant_model,
        "--out", str(out),
    ]
    subprocess.run(cmd, cwd=str(API_ROOT), check=False)


async def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--models", nargs="*", default=MODELS)
    ap.add_argument("--scoring-cases", type=int, default=3)
    ap.add_argument("--tailoring-jobs", type=int, default=2)
    ap.add_argument("--variant-model", default="qwen3:4b-instruct")
    ap.add_argument("--out-dir", default="data")
    ap.add_argument("--skip-questions", action="store_true")
    args = ap.parse_args()

    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    q_out = out_dir / "benchmark_questions.json"
    r_out = out_dir / "benchmark_resume.json"

    started = time.time()
    if not args.skip_questions:
        try:
            await run_question_suite(args.models, q_out)
        except Exception as exc:  # noqa: BLE001
            print(f"question suite failed: {exc}"[:300], flush=True)

    run_resume_suite(args.models, r_out, args.variant_model,
                     args.scoring_cases, args.tailoring_jobs)

    print(f"\nTOTAL {(time.time() - started) / 60:.1f} min")
    print(f"  questions -> {q_out}")
    print(f"  resume    -> {r_out}")


asyncio.run(main())
