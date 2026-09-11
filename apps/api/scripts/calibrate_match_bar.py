"""Find the submit bar for a scoring model, from the real job distribution.

The 80% bar was set while qwen3:4b-instruct was scoring. That model rates
almost everything in the high 70s and 80s, so the number carried little
information; on labelled postings its fitting and unfitting ranges overlapped
completely and no threshold separated them at all. A better-calibrated scorer
puts the same jobs far lower, so the bar cannot simply be carried across.

This scores a sample of real queued jobs and reports the distribution, so the
bar is chosen from what the model actually does rather than from a number
inherited from a different model.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import sqlite3
import statistics
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


async def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--model", default="mistral:7b-instruct")
    ap.add_argument("--jobs", type=int, default=20)
    ap.add_argument("--out", default="data/calibration.json")
    args = ap.parse_args()

    os.environ["CAREEROS_MATCH_MODEL"] = args.model

    from app.db.store import get_entity, get_kv, list_entities, session_scope
    from app.services.application_assistant.persistence import ENTITY_DISCOVERED_JOB
    from app.services.application_assistant.resume_diff_service import (
        CANONICAL_MASTER_BULLETS,
    )
    from app.services.application_assistant.tailored_match import score_tailored_resume

    with session_scope() as db:
        profile = get_kv(db, "profile") or {}
        documents = get_kv(db, "documents") or {}
        accomplishments = list_entities(db, "accomplishment")

    conn = sqlite3.connect(Path(__file__).resolve().parents[1] / "data" / "career_os.db")
    rows = conn.execute(
        "SELECT payload FROM entities WHERE entity_type='aa_autopilot_job' "
        "AND json_extract(payload,'$.status')='QUEUED' "
        "ORDER BY json_extract(payload,'$.matchScore') DESC"
    ).fetchall()

    # Spread the sample across the old score range rather than taking the top N,
    # or the distribution would only describe jobs the previous scorer liked.
    jobs = []
    for (payload,) in rows:
        job = json.loads(payload)
        with session_scope() as db:
            src = get_entity(db, ENTITY_DISCOVERED_JOB, job["jobId"]) if job.get("jobId") else None
        desc = (src or {}).get("description") or ""
        if len(desc) >= 2500:
            jobs.append({**job, "description": desc})
    step = max(1, len(jobs) // args.jobs)
    jobs = jobs[::step][: args.jobs]

    masters = [b["fullText"] for b in CANONICAL_MASTER_BULLETS]
    print(f"scoring {len(jobs)} queued jobs with {args.model}\n")
    print(f"{'old':>6} {'new':>6}  company / title")
    print("-" * 78)

    results = []
    for job in jobs:
        t0 = time.time()
        scored = await score_tailored_resume(
            job, masters, profile=profile, documents=documents,
            accomplishments=accomplishments,
        )
        new = float(scored.get("matchScore")) if scored else None
        old = float(job.get("matchScore") or 0)
        results.append({
            "id": job.get("id"), "company": job.get("company"), "title": job.get("title"),
            "old": old, "new": new, "seconds": round(time.time() - t0, 1),
            "missing": (scored or {}).get("missingSkills", [])[:6],
        })
        print(f"{old:6.1f} {('%6.1f' % new) if new is not None else '  FAIL'}  "
              f"{str(job.get('company'))[:18]:18} {str(job.get('title'))[:38]}", flush=True)
        Path(args.out).write_text(json.dumps(results, indent=1), encoding="utf-8")

    scores = sorted(r["new"] for r in results if r["new"] is not None)
    if not scores:
        print("\nnothing scored")
        return

    print()
    print(f"n={len(scores)}  failures={sum(1 for r in results if r['new'] is None)}")
    print(f"min {scores[0]}  median {statistics.median(scores)}  max {scores[-1]}")
    print(f"mean {statistics.mean(scores):.1f}  stdev "
          f"{statistics.stdev(scores):.1f}" if len(scores) > 1 else "")
    print()
    print("jobs clearing each candidate bar:")
    for bar in (50, 55, 60, 62, 65, 70, 75, 80):
        n = sum(1 for s in scores if s >= bar)
        print(f"  {bar:3}  {n:3} of {len(scores)}  ({100 * n / len(scores):4.0f}%)  "
              + "#" * n)


if __name__ == "__main__":
    asyncio.run(main())
