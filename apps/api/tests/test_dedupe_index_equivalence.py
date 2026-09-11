"""The incremental DedupeIndex must agree with the implementation it replaced.

The optimisation exists to stop a scrape rebuilding every lookup table once per
board batch. It is only safe if it produces the same records, so the original
single-pass function is kept and compared against here - on synthetic overlaps
and, when available, on the real indexed corpus.
"""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path

import pytest

from app.services.job_discover.dedup import (
    DedupeIndex,
    _legacy_cross_source_deduplicate,
    cross_source_deduplicate,
)

DB = Path(__file__).resolve().parents[1] / "data" / "career_os.db"


def _identity(jobs):
    """Compare on the fields dedup is responsible for, in order."""
    return [
        (
            j.get("id"),
            (j.get("companyName") or j.get("company") or "").lower(),
            (j.get("title") or "").lower(),
            j.get("url"),
            tuple(sorted(set(j.get("discoverySources") or []))),
        )
        for j in jobs
    ]


def _sample():
    return [
        {"id": "a", "companyName": "Vercel", "title": "Software Engineer, Backend",
         "location": "San Francisco, CA", "url": "https://boards.greenhouse.io/vercel/jobs/1",
         "description": "Own the platform.", "source": "greenhouse", "externalId": "1"},
        {"id": "b", "companyName": "Vercel", "title": "Software Engineer, Backend",
         "location": "USA", "url": "https://jobicy.com/jobs/9",
         "description": "Hiring a backend engineer.", "source": "jobicy", "externalId": "9"},
        {"id": "c", "companyName": "Datadog", "title": "Software Engineer",
         "location": "New York, NY", "url": "https://boards.greenhouse.io/datadog/jobs/2",
         "description": "Team A", "source": "greenhouse", "externalId": "2"},
        {"id": "d", "companyName": "Datadog", "title": "Software Engineer",
         "location": "New York, NY", "url": "https://boards.greenhouse.io/datadog/jobs/3",
         "description": "Team B", "source": "greenhouse", "externalId": "3"},
        {"id": "e", "companyName": "Fastly", "title": "Senior SRE - Networks",
         "location": "Remote", "url": "https://weworkremotely.com/x",
         "description": "X", "source": "weworkremotely"},
        {"id": "f", "companyName": "Fastly", "title": "SRE - Networks",
         "location": "Denver, CO", "url": "https://boards.greenhouse.io/fastly/jobs/4",
         "description": "Y", "source": "greenhouse", "externalId": "4"},
    ]


def test_matches_legacy_on_synthetic_overlaps():
    new = cross_source_deduplicate([dict(j) for j in _sample()])
    old = _legacy_cross_source_deduplicate([dict(j) for j in _sample()])
    assert _identity(new) == _identity(old)


def test_incremental_batches_match_one_shot():
    """Feeding batches must equal deduplicating the concatenation."""
    jobs = _sample()
    index = DedupeIndex()
    for start in range(0, len(jobs), 2):
        index.extend([dict(j) for j in jobs[start : start + 2]])
    one_shot = cross_source_deduplicate([dict(j) for j in jobs])
    assert _identity(index.values()) == _identity(one_shot)


def test_empty_and_single_inputs():
    assert cross_source_deduplicate([]) == []
    index = DedupeIndex()
    index.extend([])
    assert index.values() == []
    only = [dict(_sample()[0])]
    assert len(cross_source_deduplicate(only)) == 1


@pytest.mark.skipif(not DB.exists(), reason="no local corpus to compare against")
def test_matches_legacy_on_the_real_corpus():
    """The case that matters: thousands of real records from live boards."""
    conn = sqlite3.connect(f"file:{DB}?mode=ro", uri=True)
    try:
        row = conn.execute("SELECT value FROM kv_store WHERE key='job_discover'").fetchone()
    finally:
        conn.close()
    if not row:
        pytest.skip("job_discover snapshot not present")

    jobs = json.loads(row[0]).get("jobs") or []
    if len(jobs) < 50:
        pytest.skip("corpus too small to be meaningful")

    corpus = jobs[:2000]
    new = cross_source_deduplicate([dict(j) for j in corpus])
    old = _legacy_cross_source_deduplicate([dict(j) for j in corpus])
    assert len(new) == len(old)
    assert _identity(new) == _identity(old)


@pytest.mark.skipif(not DB.exists(), reason="no local corpus to compare against")
def test_incremental_matches_legacy_on_the_real_corpus():
    """Batched ingestion over real data, which is how a scrape actually runs."""
    conn = sqlite3.connect(f"file:{DB}?mode=ro", uri=True)
    try:
        row = conn.execute("SELECT value FROM kv_store WHERE key='job_discover'").fetchone()
    finally:
        conn.close()
    if not row:
        pytest.skip("job_discover snapshot not present")

    jobs = (json.loads(row[0]).get("jobs") or [])[:2000]
    if len(jobs) < 50:
        pytest.skip("corpus too small to be meaningful")

    index = DedupeIndex()
    for start in range(0, len(jobs), 137):  # deliberately uneven batches
        index.extend([dict(j) for j in jobs[start : start + 137]])

    old = _legacy_cross_source_deduplicate([dict(j) for j in jobs])
    assert _identity(index.values()) == _identity(old)
