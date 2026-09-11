"""Compare local models on the two jobs CareerOS actually asks them to do.

Those two jobs have different success criteria, so they are measured separately
and a model can win one and lose the other:

  SCORING   - judge how well a resume matches a posting. This number gates
              whether an application is sent, so what matters is not the score
              itself but whether it *separates*: a scorer that rates every
              posting 80% is useless as a gate however reasonable each number
              looks. Measured against postings whose correct ranking is known
              by construction - roles in the candidate's own domain should
              outscore roles built on skills the evidence ledger lists as gaps.

  TAILORING - rewrite 17 resume bullets against a posting. Measured by whether
              the result passes the submission gate: genuinely rewritten,
              structurally sound, and scoring better than the untailored resume.

Two design points worth stating, because they are what make the numbers mean
anything:

* **The tailoring comparison holds the scorer fixed.** Letting each model score
  its own output would measure self-agreement, not quality. Every candidate's
  bullets are scored by one model, in one pass, after all tailoring is done.

* **Only one model is resident at a time.** This machine cannot hold two, so
  the run is strictly sequential: load, run every case, unload, next. That is
  also why tailoring and scoring are separate phases rather than interleaved -
  interleaving would thrash the two models in and out for every single job.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import re
import sqlite3
import statistics
import sys
import time
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import httpx  # noqa: E402

OLLAMA = os.environ.get("OLLAMA_BASE_URL", "http://localhost:11434").replace("/v1", "")
DB = Path(__file__).resolve().parents[1] / "data" / "career_os.db"

#: Candidates, smallest first so a run that has to be cut short still produced
#: comparable numbers for the models most likely to be usable here.
DEFAULT_MODELS = [
    "qwen2.5:3b",
    "qwen3:4b-instruct",
    "mistral:7b-instruct",
    "qwen3:8b",
    "gemma3:12b",
]

#: The scorer used to judge every model's tailoring output. Held fixed.
REFERENCE_SCORER = os.environ.get("BENCH_REFERENCE_SCORER", "qwen3:4b-instruct")

#: Hosted models, included as a ceiling to measure the local ones against.
#: They cost no local memory, so they neither compete for the GPU nor need
#: unloading - but they do send the resume and the posting to a third party,
#: which is the whole reason CareerOS runs locally by default. Treat a cloud
#: win as information about how much local execution costs in quality, not as
#: a recommendation to switch.
CLOUD_MODELS: dict[str, tuple[str, str, str]] = {
    "gemini-flash-latest": (
        "https://generativelanguage.googleapis.com/v1beta/openai",
        "GEMINI_API_KEY",
        "gemini",
    ),
    "gpt-4o-mini": ("https://api.openai.com/v1", "OPENAI_API_KEY", "openai"),
}


def install_scorer(model: str) -> None:
    """Point the scoring path at `model`, hosted or local.

    Monkeypatching the client factory rather than adding a provider switch to
    it: the production factory is deliberately Ollama-only so queue scoring can
    never silently run against a vendor's API, and that property is worth more
    than the convenience of a benchmark flag.
    """
    from app.services.application_assistant import mistral_resume_match as mrm

    if model not in CLOUD_MODELS:
        os.environ["CAREEROS_MATCH_MODEL"] = model
        if hasattr(mrm, "_bench_original_factory"):
            mrm.build_mistral_match_client = mrm._bench_original_factory
        return

    base_url, key_env, provider = CLOUD_MODELS[model]
    api_key = os.environ.get(key_env, "")
    if not api_key:
        raise RuntimeError(f"{key_env} is not set; cannot benchmark {model}")

    from app.services.application_assistant.llm_client import LLMClient

    if not hasattr(mrm, "_bench_original_factory"):
        mrm._bench_original_factory = mrm.build_mistral_match_client

    def factory(*, timeout: int | None = None) -> LLMClient:
        return LLMClient(
            base_url=base_url, model=model, api_key=api_key,
            timeout=timeout or 120, max_retries=1, provider=provider,
            context_window=128_000, temperature=0.0,
        )

    mrm.build_mistral_match_client = factory


# ---------------------------------------------------------------------------
# Ollama lifecycle
# ---------------------------------------------------------------------------

async def unload(model: str) -> None:
    """Drop a model from memory so the next one has room. No-op for hosted models."""
    if model in CLOUD_MODELS:
        return
    try:
        async with httpx.AsyncClient(timeout=20) as c:
            await c.post(f"{OLLAMA}/api/generate", json={"model": model, "keep_alive": 0})
    except Exception:
        pass


async def resident() -> list[dict[str, Any]]:
    try:
        async with httpx.AsyncClient(timeout=10) as c:
            return (await c.get(f"{OLLAMA}/api/ps")).json().get("models", [])
    except Exception:
        return []


async def memory_of(model: str) -> dict[str, Any]:
    """What this model costs while loaded, as Ollama reports it."""
    for m in await resident():
        if m.get("name") == model or m.get("model") == model:
            total = int(m.get("size") or 0)
            vram = int(m.get("size_vram") or 0)
            return {
                "totalBytes": total,
                "vramBytes": vram,
                "cpuBytes": max(0, total - vram),
                # The number that predicts whether this model is usable here:
                # anything not in VRAM runs on the CPU at a few tokens/second.
                "vramFraction": round(vram / total, 3) if total else 0.0,
            }
    return {}


async def assert_alone(model: str) -> None:
    """Evict anything else before `model` runs. Hosted models still evict local
    ones, because a local model left resident would keep holding the GPU for no
    reason while the hosted calls run."""
    others = [m.get("name") for m in await resident() if m.get("name") != model]
    if others:
        print(f"    ! also resident: {others} - unloading", flush=True)
        for other in others:
            await unload(str(other))


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

def _jobs_by_title(
    patterns: list[str], limit: int, min_chars: int = 2500,
    seen_companies: set[str] | None = None,
    exclude: list[str] | None = None,
) -> list[dict]:
    """Postings whose TITLE matches `patterns` and matches none of `exclude`.

    The exclusion list is not optional in practice. Matching "platform" alone
    labelled "Staff Android Software Engineer, Cash App Consumer Platform" as a
    strong fit, which put an Android role in the group that is supposed to
    represent the candidate's own domain and made the separation metric
    measure nothing. A title has to be in the domain *and* not in an excluded
    one to count.
    """
    conn = sqlite3.connect(DB)
    out: list[dict] = []
    seen_companies = seen_companies if seen_companies is not None else set()
    exclude = exclude or []
    for (payload,) in conn.execute(
        "SELECT payload FROM entities WHERE entity_type='aa_discovered_job'"
    ):
        job = json.loads(payload)
        title = str(job.get("title") or "")
        desc = str(job.get("description") or "")
        company = str(job.get("company") or "")
        if len(desc) < min_chars or company in seen_companies:
            continue
        # Both sets must be engineering roles, or the comparison drifts into
        # comparing an SRE posting against a Product Manager posting, which
        # tests nothing about resume matching. ("Staff Product Manager,
        # Customer Care Platform" got picked as a strong engineering fit.)
        if not re.search(r"engineer", title, re.I):
            continue
        if any(re.search(p, title, re.I) for p in exclude):
            continue
        if any(re.search(p, title, re.I) for p in patterns):
            out.append({"id": job.get("id"), "company": company, "title": title,
                        "description": desc})
            seen_companies.add(company)
        if len(out) >= limit:
            break
    return out


def build_scoring_set(n_each: int) -> list[dict]:
    """Postings whose correct ordering is known before any model sees them.

    STRONG are the candidate's own domain - distributed systems, platform and
    infrastructure work. WEAK are real postings built on skills the evidence
    ledger reports as unevidenced (mobile, frontend-only, data science). The
    labels are about relative fit, not absolute scores: a good scorer need not
    agree with any particular number, it must rank strong above weak.
    """
    # Anything that makes a posting belong to the other group disqualifies it
    # from this one. Without this a title carrying both words ("Android
    # Engineer, Consumer Platform") lands in whichever set is built first.
    client_side = [
        r"android", r"\bios\b", r"\bmobile\b", r"front.?end", r"react native",
        r"\bui\b", r"web developer",
    ]
    server_side = [
        r"distributed", r"infrastructure", r"\bbackend\b", r"\bplatform\b",
        r"\bsre\b", r"reliability",
    ]

    seen: set[str] = set()
    strong = _jobs_by_title(
        server_side, n_each, seen_companies=seen,
        exclude=client_side + [
            r"data scientist", r"\bml\b", r"machine learning",
            # ERP and SaaS-configuration work. "Platform Engineer, Workday
            # Extend" is a platform role in a sense that has nothing to do with
            # the distributed-systems work this set is meant to represent.
            r"workday", r"salesforce", r"servicenow", r"netsuite",
        ],
    )
    weak = _jobs_by_title(
        client_side + [r"data scientist"], n_each, seen_companies=seen,
        exclude=server_side,
    )
    return (
        [{**j, "label": "strong"} for j in strong]
        + [{**j, "label": "weak"} for j in weak]
    )


def build_tailoring_set(n: int) -> list[dict]:
    conn = sqlite3.connect(DB)
    rows = conn.execute(
        "SELECT payload FROM entities WHERE entity_type='aa_autopilot_job' "
        "AND json_extract(payload,'$.status')='QUEUED' "
        "ORDER BY json_extract(payload,'$.matchScore') DESC LIMIT 60"
    ).fetchall()
    out = []
    for (payload,) in rows:
        job = json.loads(payload)
        from app.db.store import get_entity, session_scope
        from app.services.application_assistant.persistence import ENTITY_DISCOVERED_JOB

        with session_scope() as db:
            src = get_entity(db, ENTITY_DISCOVERED_JOB, job["jobId"]) if job.get("jobId") else None
        desc = (src or {}).get("description") or ""
        if len(desc) < 3000:
            continue
        out.append({**job, "description": desc})
        if len(out) >= n:
            break
    return out


# ---------------------------------------------------------------------------
# Phase 1 - scoring
# ---------------------------------------------------------------------------

async def bench_scoring(model: str, cases: list[dict], ctx: dict) -> dict[str, Any]:
    install_scorer(model)
    from app.services.application_assistant.resume_diff_service import CANONICAL_MASTER_BULLETS
    from app.services.application_assistant.tailored_match import score_tailored_resume

    masters = [b["fullText"] for b in CANONICAL_MASTER_BULLETS]
    results: list[dict] = []
    latencies: list[float] = []
    failures = 0
    fabricated = 0

    for case in cases:
        t0 = time.time()
        scored = await score_tailored_resume(
            case, masters, profile=ctx["profile"],
            documents=ctx["documents"], accomplishments=ctx["accomplishments"],
        )
        dt = time.time() - t0
        if not scored:
            failures += 1
            print(f"    {case['label']:6} {case['company'][:18]:18} FAILED ({dt:.0f}s)", flush=True)
            continue
        latencies.append(dt)
        fabricated += len(scored.get("unevidencedClaimsDropped") or [])
        results.append({
            "label": case["label"], "company": case["company"], "title": case["title"],
            "score": float(scored.get("matchScore") or 0),
            "dropped": len(scored.get("unevidencedClaimsDropped") or []),
        })
        print(f"    {case['label']:6} {case['company'][:18]:18} "
              f"{scored.get('matchScore'):5.1f}%  {dt:5.0f}s", flush=True)

    mem = await memory_of(model)

    # Determinism: the same input twice must give the same number, or the score
    # cannot be used as a gate at all.
    determinism = None
    if cases:
        a = await score_tailored_resume(cases[0], masters, profile=ctx["profile"],
                                        documents=ctx["documents"],
                                        accomplishments=ctx["accomplishments"])
        b = await score_tailored_resume(cases[0], masters, profile=ctx["profile"],
                                        documents=ctx["documents"],
                                        accomplishments=ctx["accomplishments"])
        if a and b:
            determinism = {
                "a": float(a.get("matchScore") or 0), "b": float(b.get("matchScore") or 0),
            }
            determinism["stable"] = determinism["a"] == determinism["b"]

    strong = [r["score"] for r in results if r["label"] == "strong"]
    weak = [r["score"] for r in results if r["label"] == "weak"]
    pairs = [(s, w) for s in strong for w in weak]
    return {
        "model": model,
        "cases": results,
        "strongMean": round(statistics.mean(strong), 1) if strong else None,
        "weakMean": round(statistics.mean(weak), 1) if weak else None,
        # The headline metric: how far apart it puts roles that fit and roles
        # that do not.
        "separation": round(statistics.mean(strong) - statistics.mean(weak), 1)
        if strong and weak else None,
        "rankAccuracy": round(sum(1 for s, w in pairs if s > w) / len(pairs), 3) if pairs else None,
        "spread": round(max(strong + weak) - min(strong + weak), 1) if results else None,
        "unevidencedClaims": fabricated,
        "failures": failures,
        "latencyMean": round(statistics.mean(latencies), 1) if latencies else None,
        "latencyMax": round(max(latencies), 1) if latencies else None,
        "determinism": determinism,
        "memory": mem,
    }


# ---------------------------------------------------------------------------
# Phase 2 - tailoring
# ---------------------------------------------------------------------------

async def bench_tailoring(model: str, jobs: list[dict], ctx: dict) -> dict[str, Any]:
    """Produce bullets with this model. Scored later, by the reference scorer."""
    os.environ["CAREEROS_TAILORING_MODEL"] = model
    from app.services.application_assistant.resume_diff_service import (
        generate_role_tailoring_diff,
    )

    out: list[dict] = []
    for job in jobs:
        t0 = time.time()
        try:
            diff = await generate_role_tailoring_diff(
                job, ctx["profile"], ctx["master_resume"], mode="honest",
                documents=ctx["documents"], accomplishments=ctx["accomplishments"],
                # Scoring happens later under the reference model.
                rescore=False,
            )
        except Exception as exc:  # noqa: BLE001
            print(f"    {job.get('company')[:20]:20} ERROR {exc}"[:110], flush=True)
            out.append({"job": job.get("id"), "company": job.get("company"), "error": str(exc)[:200]})
            continue
        dt = time.time() - t0
        bullets = [b.get("tailored") or b.get("original") for b in diff.get("bulletDiffs") or []]
        out.append({
            "job": job.get("id"), "company": job.get("company"), "title": job.get("title"),
            "changed": diff.get("totalChanges"),
            "tailoringFailed": diff.get("tailoringFailed"),
            "latency": round(dt, 1),
            "bullets": bullets,
        })
        print(f"    {str(job.get('company'))[:20]:20} {diff.get('totalChanges'):2}/17 changed "
              f"{dt:5.0f}s", flush=True)

    mem = await memory_of(model)
    lat = [r["latency"] for r in out if "latency" in r]
    return {
        "model": model,
        "runs": out,
        "latencyMean": round(statistics.mean(lat), 1) if lat else None,
        "memory": mem,
    }


async def score_tailoring_outputs(tailoring: list[dict], jobs: list[dict], ctx: dict) -> None:
    """One scorer, one pass, over every model's output plus the untailored control."""
    install_scorer(REFERENCE_SCORER)
    from app.services.application_assistant.resume_diff_service import CANONICAL_MASTER_BULLETS
    from app.services.application_assistant.resume_quality import assess
    from app.services.application_assistant.tailored_match import score_tailored_resume

    masters = [b["fullText"] for b in CANONICAL_MASTER_BULLETS]
    by_id = {j["id"]: j for j in jobs}

    async def score_or_none(job: dict, bullets: list[str]) -> float | None:
        """Score, retrying once. Returns None when it could not be scored.

        Returning 0.0 for a failed call was actively misleading: a baseline
        that failed to score recorded as 0%, and every tailored resume then
        looked like a +55 point improvement over nothing. A model outage is
        missing data, not a bad match.
        """
        for _ in range(2):
            scored = await score_tailored_resume(
                job, bullets, profile=ctx["profile"], documents=ctx["documents"],
                accomplishments=ctx["accomplishments"],
            )
            if scored:
                return float(scored.get("matchScore") or 0)
        return None

    baselines: dict[str, float | None] = {}
    for job in jobs:
        baselines[job["id"]] = await score_or_none(job, masters)
        shown = baselines[job["id"]]
        print(f"    baseline {str(job.get('company'))[:20]:20} "
              + (f"{shown:5.1f}%" if shown is not None else "COULD NOT SCORE"), flush=True)

    for entry in tailoring:
        for run in entry["runs"]:
            if "bullets" not in run:
                continue
            job = by_id.get(run["job"])
            if not job:
                continue
            run["score"] = await score_or_none(job, run["bullets"])
            run["baseline"] = baselines.get(run["job"])
            gradable = run["score"] is not None and run["baseline"] is not None
            run["delta"] = (
                round(run["score"] - run["baseline"], 1) if gradable else None
            )
            if gradable:
                report = assess(
                    masters, run["bullets"],
                    score_before=run["baseline"], score_after=run["score"],
                    min_changed=3, require_improvement=True,
                )
                run["quality"] = report.to_dict()
                run["gatePass"] = bool(report.ok and run["score"] >= 80)
            else:
                # Ungraded, not failed. Counting an unscorable run as a gate
                # failure would penalise a model for the scorer's outage.
                run["quality"] = None
                run["gatePass"] = None
            # Drop the bullet text now it has been judged; the report does not
            # need 17 paragraphs per model per job.
            run.pop("bullets", None)
            label = entry.get("model") or entry.get("variant") or "?"
            if gradable:
                print(f"    {str(label)[:20]:20} {str(run['company'])[:16]:16} "
                      f"{run['baseline']:5.1f} -> {run['score']:5.1f} "
                      f"({run['delta']:+.1f}) gate="
                      f"{'PASS' if run['gatePass'] else 'fail'}", flush=True)
            else:
                print(f"    {str(label)[:20]:20} {str(run['company'])[:16]:16} "
                      f"COULD NOT SCORE - excluded", flush=True)

    for entry in tailoring:
        graded = [r for r in entry["runs"] if r.get("gatePass") is not None]
        entry["passRate"] = (
            round(sum(1 for r in graded if r["gatePass"]) / len(graded), 3) if graded else None
        )
        entry["deltaMean"] = (
            round(statistics.mean([r["delta"] for r in graded]), 1) if graded else None
        )
        entry["changedMean"] = (
            round(statistics.mean([r["changed"] for r in graded]), 1) if graded else None
        )
        entry["errors"] = sum(1 for r in entry["runs"] if "error" in r)


# ---------------------------------------------------------------------------
# Phase 3 - prompt shape, on one model
# ---------------------------------------------------------------------------
#
# Run against a single model rather than every model. A full model x variant
# cross product costs hours on this hardware and answers a question nobody
# asked; what is worth knowing is whether these prompt choices earn their keep
# at all, which one model can establish.
#
# Each variant toggles something the tailoring prompt actually does, so a
# result here is directly actionable:
#
#   baseline        - what ships today: retrieved evidence, detected
#                     requirements, batches of 4.
#   no-evidence     - drops the retrieved story evidence. Answers whether the
#                     story index is doing real work or just spending context.
#   batch-8 / -17   - larger batches. 17 is the single call that was shipping
#                     before, and the one measured returning bullets in the
#                     wrong slots; this quantifies what batching bought.
#   aggressive      - the other mode, same everything else.

PROMPT_VARIANTS: dict[str, dict[str, Any]] = {
    "baseline": {},
    "no-evidence": {"evidence_share": 0.0},
    "batch-8": {"batch_size": 8},
    "batch-17": {"batch_size": 17},
    "aggressive": {"mode": "aggressive"},
}


async def bench_variants(
    model: str, variants: list[str], jobs: list[dict], ctx: dict
) -> list[dict[str, Any]]:
    os.environ["CAREEROS_TAILORING_MODEL"] = model
    import app.services.application_assistant.resume_diff_service as rds
    from app.services.application_assistant.resume_diff_service import (
        generate_role_tailoring_diff,
    )

    original = (rds.EVIDENCE_BUDGET_SHARE, rds.BULLET_BATCH_SIZE)
    out: list[dict[str, Any]] = []

    for name in variants:
        cfg = PROMPT_VARIANTS[name]
        rds.EVIDENCE_BUDGET_SHARE = cfg.get("evidence_share", original[0])
        rds.BULLET_BATCH_SIZE = cfg.get("batch_size", original[1])
        mode = cfg.get("mode", "honest")
        print(f"\n  -- variant '{name}' (evidence={rds.EVIDENCE_BUDGET_SHARE}, "
              f"batch={rds.BULLET_BATCH_SIZE}, mode={mode})", flush=True)

        runs = []
        for job in jobs:
            t0 = time.time()
            try:
                diff = await generate_role_tailoring_diff(
                    job, ctx["profile"], ctx["master_resume"], mode=mode,
                    documents=ctx["documents"], accomplishments=ctx["accomplishments"],
                    rescore=False,
                )
            except Exception as exc:  # noqa: BLE001
                runs.append({"job": job.get("id"), "company": job.get("company"),
                             "error": str(exc)[:200]})
                continue
            dt = time.time() - t0
            runs.append({
                "job": job.get("id"), "company": job.get("company"),
                "changed": diff.get("totalChanges"),
                "tailoringFailed": diff.get("tailoringFailed"),
                "latency": round(dt, 1),
                "bullets": [b.get("tailored") or b.get("original")
                            for b in diff.get("bulletDiffs") or []],
            })
            print(f"     {str(job.get('company'))[:20]:20} "
                  f"{diff.get('totalChanges'):2}/17 changed {dt:5.0f}s", flush=True)
        out.append({"model": model, "variant": name, "runs": runs})

    rds.EVIDENCE_BUDGET_SHARE, rds.BULLET_BATCH_SIZE = original
    return out


# ---------------------------------------------------------------------------

def out_path_for(args: Any) -> Path:
    return Path(args.out)


async def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--models", nargs="*", default=DEFAULT_MODELS)
    ap.add_argument("--scoring-cases", type=int, default=3, help="per label")
    ap.add_argument("--tailoring-jobs", type=int, default=2)
    ap.add_argument("--skip-tailoring", action="store_true")
    ap.add_argument("--variant-model", default=None,
                    help="run the prompt-variant sweep on this model")
    ap.add_argument("--variants", nargs="*", default=list(PROMPT_VARIANTS))
    ap.add_argument("--out", default="benchmark-results.json")
    ap.add_argument("--resume", action="store_true",
                    help="keep results already in --out and skip those models")
    ap.add_argument("--grade-only", action="store_true",
                    help="re-grade tailoring output already in --out; tailor nothing")
    args = ap.parse_args()

    from app.db.store import get_kv, list_entities, session_scope

    with session_scope() as db:
        ctx = {
            "profile": get_kv(db, "profile") or {},
            "documents": get_kv(db, "documents") or {},
            "master_resume": get_kv(db, "resume_corpus_master") or {},
            "accomplishments": list_entities(db, "accomplishment"),
        }

    if args.grade_only:
        # Tailoring output is expensive - minutes per model per job - and the
        # bullets are kept in the results file until they are graded, so a
        # grading bug costs a re-grade rather than a re-run.
        previous = json.loads(out_path_for(args).read_text(encoding="utf-8"))
        jobs = build_tailoring_set(args.tailoring_jobs)
        print(f"grading {len(previous.get('tailoring') or [])} models and "
              f"{len(previous.get('variants') or [])} variants "
              f"with {REFERENCE_SCORER}\n", flush=True)
        await assert_alone(REFERENCE_SCORER)
        install_scorer(REFERENCE_SCORER)
        if previous.get("tailoring"):
            await score_tailoring_outputs(previous["tailoring"], jobs, ctx)
        if previous.get("variants"):
            await score_tailoring_outputs(previous["variants"], jobs, ctx)
        await unload(REFERENCE_SCORER)
        out_path_for(args).write_text(json.dumps(previous, indent=1), encoding="utf-8")
        print(f"\nwrote {out_path_for(args)}")
        return

    scoring_cases = build_scoring_set(args.scoring_cases)
    tailoring_jobs = [] if args.skip_tailoring else build_tailoring_set(args.tailoring_jobs)
    print(f"scoring cases: {len(scoring_cases)}  tailoring jobs: {len(tailoring_jobs)}")
    print(f"models: {', '.join(args.models)}")
    print(f"reference scorer for tailoring: {REFERENCE_SCORER}\n")

    out_path = Path(args.out)
    # A run measured in hours on constrained hardware will sometimes be killed
    # part way - this one was, by the OOM killer, with a 12GB model resident.
    # Resuming keeps every model already measured instead of paying for it
    # twice; the phases are independent, so a partial file is still valid data.
    previous: dict[str, Any] = {}
    if args.resume and out_path.exists():
        try:
            previous = json.loads(out_path.read_text(encoding="utf-8"))
        except Exception:
            previous = {}

    results: dict[str, Any] = {
        "generatedAt": time.strftime("%Y-%m-%d %H:%M"),
        "referenceScorer": REFERENCE_SCORER,
        "scoringCases": [
            {"label": c["label"], "company": c["company"], "title": c["title"],
             "chars": len(c["description"])}
            for c in scoring_cases
        ],
        "tailoringJobs": [
            {"company": j.get("company"), "title": j.get("title"),
             "chars": len(j["description"])}
            for j in tailoring_jobs
        ],
        "scoring": list(previous.get("scoring") or []),
        "tailoring": list(previous.get("tailoring") or []),
    }
    done_scoring = {s["model"] for s in results["scoring"] if not s.get("error")}
    done_tailoring = {t["model"] for t in results["tailoring"] if not t.get("error")}
    if done_scoring or done_tailoring:
        print(f"resuming: scoring already done for {sorted(done_scoring)}; "
              f"tailoring already done for {sorted(done_tailoring)}\n")

    for model in args.models:
        if model in done_scoring:
            print(f"\n=== SCORING: {model} - already measured, skipping ===", flush=True)
            continue
        print(f"\n=== SCORING: {model} ===", flush=True)
        await assert_alone(model)
        try:
            results["scoring"].append(await bench_scoring(model, scoring_cases, ctx))
        except Exception as exc:  # noqa: BLE001
            print(f"    model failed entirely: {exc}"[:160], flush=True)
            results["scoring"].append({"model": model, "error": str(exc)[:300]})
        await unload(model)
        out_path.write_text(json.dumps(results, indent=1), encoding="utf-8")

    if tailoring_jobs:
        for model in args.models:
            if model in done_tailoring:
                print(f"\n=== TAILORING: {model} - already measured, skipping ===",
                      flush=True)
                continue
            print(f"\n=== TAILORING: {model} ===", flush=True)
            await assert_alone(model)
            try:
                results["tailoring"].append(await bench_tailoring(model, tailoring_jobs, ctx))
            except Exception as exc:  # noqa: BLE001
                print(f"    model failed entirely: {exc}"[:160], flush=True)
                results["tailoring"].append({"model": model, "error": str(exc)[:300]})
            await unload(model)
            out_path.write_text(json.dumps(results, indent=1), encoding="utf-8")

        if args.variant_model:
            print(f"\n=== PROMPT VARIANTS on {args.variant_model} ===", flush=True)
            await assert_alone(args.variant_model)
            try:
                results["variants"] = await bench_variants(
                    args.variant_model, args.variants, tailoring_jobs, ctx
                )
            except Exception as exc:  # noqa: BLE001
                print(f"    variant sweep failed: {exc}"[:160], flush=True)
                results["variants"] = []
            await unload(args.variant_model)
            out_path.write_text(json.dumps(results, indent=1), encoding="utf-8")

        print(f"\n=== GRADING with {REFERENCE_SCORER} ===", flush=True)
        await assert_alone(REFERENCE_SCORER)
        await score_tailoring_outputs(results["tailoring"], tailoring_jobs, ctx)
        if results.get("variants"):
            await score_tailoring_outputs(results["variants"], tailoring_jobs, ctx)
        await unload(REFERENCE_SCORER)

    out_path.write_text(json.dumps(results, indent=1), encoding="utf-8")
    print(f"\nwrote {out_path}")


if __name__ == "__main__":
    # Guarded so the fixture builders can be imported and inspected without
    # launching a full benchmark - which is exactly what happened once.
    asyncio.run(main())
