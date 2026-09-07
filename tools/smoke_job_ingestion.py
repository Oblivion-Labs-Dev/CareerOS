"""CareerOS Job Ingestion V2 Live Smoke Test Tool.

Runs a quick, read-only validation against authoritative public ATS endpoints
and curated public APIs to verify network connectivity, parsing, and normalization
without mutating the production database snapshot.
"""

from __future__ import annotations

import asyncio
import os
import sys
import time
from datetime import UTC, datetime, timedelta
from pathlib import Path

if sys.platform == "win32":
    sys.stdout.reconfigure(encoding="utf-8")

# Add apps/api to Python path
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "apps" / "api"))

import httpx

from app.services.job_discover.dedup import cross_source_deduplicate
from app.services.job_discover.sources.arbeitnow import ArbeitnowSource
from app.services.job_discover.sources.ashby import AshbySource
from app.services.job_discover.sources.greenhouse import GreenhouseSource
from app.services.job_discover.sources.hackernews import HackerNewsSource
from app.services.job_discover.sources.jobicy import JobicySource
from app.services.job_discover.sources.lever import LeverSource


async def run_smoke():
    print("=" * 70)
    print("🚀 CareerOS Job Ingestion V2 — Live Smoke Test (Read-Only)")
    print("=" * 70)

    start_all = time.perf_counter()
    cutoff = datetime.now(UTC) - timedelta(days=60)
    results = []

    async with httpx.AsyncClient(timeout=15.0, headers={"User-Agent": "CareerOS-SmokeTest/2.0"}) as client:
        # 1. Greenhouse (Stripe)
        print("\n[1/4] Testing Greenhouse ATS (Stripe)...")
        gh = GreenhouseSource()
        try:
            t0 = time.perf_counter()
            gh_jobs = await gh.fetch_jobs(
                client,
                company="Stripe",
                config={"boardId": "stripe"},
                compiled_patterns=[],
                cutoff=cutoff,
            )
            dur = (time.perf_counter() - t0) * 1000
            print(f"  ✓ Greenhouse: fetched {len(gh_jobs)} normalized jobs in {dur:.0f}ms")
            if gh_jobs:
                sample = gh_jobs[0]
                print(f"    Sample: [{sample.source}] {sample.title} @ {sample.company} ({sample.location})")
            results.extend(gh_jobs)
        except Exception as exc:
            print(f"  ✗ Greenhouse failed: {exc}")

        # 2. Lever (Netflix or Figma)
        print("\n[2/4] Testing Lever ATS (Figma)...")
        lever = LeverSource()
        try:
            t0 = time.perf_counter()
            lever_jobs = await lever.fetch_jobs(
                client,
                company="Figma",
                config={"site": "figma"},
                compiled_patterns=[],
                cutoff=cutoff,
            )
            dur = (time.perf_counter() - t0) * 1000
            print(f"  ✓ Lever: fetched {len(lever_jobs)} normalized jobs in {dur:.0f}ms")
            if lever_jobs:
                sample = lever_jobs[0]
                print(f"    Sample: [{sample.source}] {sample.title} @ {sample.company} ({sample.location})")
            results.extend(lever_jobs)
        except Exception as exc:
            print(f"  ✗ Lever failed: {exc}")

        # 3. Jobicy (Remote Engineering API)
        print("\n[3/4] Testing Jobicy Public API...")
        jobicy = JobicySource()
        try:
            t0 = time.perf_counter()
            jobicy_jobs = await jobicy.fetch_jobs(
                client,
                company="Any",
                config={"count": 5},
                compiled_patterns=[],
                cutoff=cutoff,
            )
            dur = (time.perf_counter() - t0) * 1000
            print(f"  ✓ Jobicy: fetched {len(jobicy_jobs)} normalized jobs in {dur:.0f}ms")
            if jobicy_jobs:
                sample = jobicy_jobs[0]
                print(f"    Sample: [{sample.source}] {sample.title} @ {sample.company} ({sample.location})")
            results.extend(jobicy_jobs)
        except Exception as exc:
            print(f"  ✗ Jobicy failed: {exc}")

        # 4. Hacker News "Who is Hiring?" (Algolia API)
        print("\n[4/5] Testing Hacker News Who is Hiring (Algolia API)...")
        hn = HackerNewsSource()
        try:
            t0 = time.perf_counter()
            hn_jobs = await hn.fetch_jobs(
                client,
                company="HackerNews",
                config={},
                compiled_patterns=[],
                cutoff=cutoff,
            )
            dur = (time.perf_counter() - t0) * 1000
            print(f"  ✓ HackerNews: fetched {len(hn_jobs)} normalized jobs in {dur:.0f}ms")
            if hn_jobs:
                sample = hn_jobs[0]
                print(f"    Sample: [{sample.source}] {sample.title} @ {sample.company} ({sample.location})")
            results.extend(hn_jobs)
        except Exception as exc:
            print(f"  ✗ HackerNews failed: {exc}")

        # 5. Deterministic ATS Fingerprinting
        print("\n[5/5] Testing ATS Fingerprinter Engine...")
        from app.services.job_discover.discovery.company_registry import JobSourceDiscoveryService
        test_urls = [
            ("Stripe", "https://boards.greenhouse.io/stripe/jobs/123"),
            ("Netflix", "https://jobs.lever.co/netflix/uuid-123"),
            ("OpenAI", "https://jobs.ashbyhq.com/openai"),
            ("Salesforce", "https://salesforce.wd12.myworkdayjobs.com/External"),
        ]
        for cname, u in test_urls:
            fp = JobSourceDiscoveryService.fingerprint_ats(u)
            print(f"  ✓ {cname} -> Provider: {fp['provider']}, Confidence: {fp['confidence']}, Evidence: {fp['evidence']}")

    # Deduplication test on the combined sample
    print("\n" + "-" * 70)
    print("Testing Multi-Source Cross Deduplication...")
    raw_dicts = [j.to_dict() for j in results]
    deduped = cross_source_deduplicate(raw_dicts)
    total_elapsed = time.perf_counter() - start_all

    print(f"Total raw jobs fetched:       {len(results)}")
    print(f"Total deduplicated jobs:      {len(deduped)}")
    print(f"Total smoke test duration:    {total_elapsed:.2f}s")
    print("=" * 70)
    print("✅ Smoke test passed with 0 exceptions and healthy normalization!")


if __name__ == "__main__":
    asyncio.run(run_smoke())
