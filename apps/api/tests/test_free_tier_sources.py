"""Free-tier source enablement regression tests (issue #95).

Every key-gated source must be inert without its key, and every quota guard
must self-limit to the source's documented free allowance:

    SerpApi        100 successful searches/month (cached calls are free)
    Google CSE     100 queries/day (adapter budget defaults below that)
    Fantastic.jobs ~500 job credits/month + ~50 API requests/week
    TheirStack     ~1,000 one-time signup credits (1 credit = 1 job)

The Fantastic/TheirStack fixtures mirror the vendors' own documented
response shapes (Fantastic publishes sample files; TheirStack publishes an
OpenAPI spec) so a vendor field rename fails here before production does.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

import httpx
import pytest

from app.services.job_discover.scraper_service import (
    _fantastic_key,
    _serpapi_key,
    _theirstack_key,
    compile_role_patterns,
)
from app.services.job_discover.sources import fantasticjobs, serpapi_google_jobs, theirstack
from app.services.job_discover.scraper_service import _as_job_dicts


# ── Shared fakes ─────────────────────────────────────────────────────────────


class _FakeClient:
    """Stands in for httpx.AsyncClient inside JobSourceAdapter.execute_request."""

    def __init__(self, status_code: int = 200, text: str = ""):
        self.status_code = status_code
        self.text = text
        self.calls: list[dict] = []

    async def request(self, *, method, url, headers=None, json=None, params=None, timeout=None):
        self.calls.append({"method": method, "url": url, "headers": headers,
                           "params": params, "json": json})
        return httpx.Response(
            self.status_code,
            text=self.text,
            request=httpx.Request(method or "GET", url),
        )


@pytest.fixture
def quota_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Redirect both adapters' persisted quota files into a temp dir."""
    monkeypatch.setattr(fantasticjobs, "DATA_DIR", tmp_path)
    monkeypatch.setattr(fantasticjobs, "QUOTA_FILE", tmp_path / "fantastic_quota.json")
    monkeypatch.setattr(serpapi_google_jobs, "DATA_DIR", tmp_path)
    monkeypatch.setattr(serpapi_google_jobs, "QUOTA_FILE", tmp_path / "serpapi_quota.json")
    monkeypatch.setattr(theirstack, "DATA_DIR", tmp_path)
    monkeypatch.setattr(theirstack, "QUOTA_FILE", tmp_path / "theirstack_quota.json")
    return tmp_path


CUTOFF = datetime.now(UTC) - timedelta(hours=24)


# ── SerpApi: guard sizes must match the documented free plan ────────────────


def test_serpapi_guards_match_the_free_tier():
    """SerpApi's free plan is 100 successful searches/month. The daily budget
    must never allow a month's worth of runs to over-spend it."""
    from calendar import monthrange

    now = datetime.now(UTC)
    assert serpapi_google_jobs.MONTHLY_FREE_QUOTA == 100
    assert serpapi_google_jobs.DAILY_REQUEST_BUDGET * monthrange(now.year, now.month)[1] <= 100


def test_serpapi_quota_stops_at_daily_budget(quota_dir, monkeypatch):
    monkeypatch.delenv("SERPAPI_KEY", raising=False)
    monkeypatch.delenv("SERPAPI_API_KEY", raising=False)
    source = serpapi_google_jobs.SerpApiGoogleJobsSource()

    accepted = 0
    for _ in range(serpapi_google_jobs.DAILY_REQUEST_BUDGET + 2):
        if source._increment_quota():
            accepted += 1
    assert accepted == serpapi_google_jobs.DAILY_REQUEST_BUDGET
    persisted = json.loads((quota_dir / "serpapi_quota.json").read_text(encoding="utf-8"))
    assert persisted["daily_count"] == serpapi_google_jobs.DAILY_REQUEST_BUDGET
    assert persisted["monthly_count"] == serpapi_google_jobs.DAILY_REQUEST_BUDGET


def test_serpapi_inert_without_key(monkeypatch, quota_dir):
    monkeypatch.delenv("SERPAPI_KEY", raising=False)
    monkeypatch.delenv("SERPAPI_API_KEY", raising=False)
    assert _serpapi_key() == ""


# ── Fantastic.jobs ───────────────────────────────────────────────────────────

# Fixture mirrors the vendor's official sample-ats.json row shape.
FANTASTIC_FIXTURE_ROWS = [
    {
        "id": 2420528751,
        "date_posted": "2026-10-18T01:05:54",
        "date_created": "2026-10-18T01:13:59.319275",
        "title": "Senior AI Engineer, Inference",
        "organization": "Acme AI",
        "url": "https://job-boards.greenhouse.io/acmeai/jobs/4091886009",
        "source_type": "ats",
        "source": "greenhouse",
        "source_slug": "acmeai",
        "locations_derived": ["New York, New York, United States", "California, United States"],
        "description": "Own inference workloads.",
    },
    {
        "id": 2420528752,
        "title": "Executive Assistant to CEO",
        "organization": "Acme AI",
        "url": "https://job-boards.greenhouse.io/acmeai/jobs/4091886010",
        "source": "greenhouse",
        "locations": ["California, United States"],
    },
    {
        # No `id` and only raw schema.org Place objects for locations: id falls
        # back to a URL hash and the locality is extracted from the dict.
        "title": "Machine Learning Engineer, Data",
        "organization": "Acme AI",
        "url": "https://boards.greenhouse.io/acmeai/jobs/4091886011",
        "source": "greenhouse",
        "locations": [
            {"@type": "Place", "address": {"@type": "PostalAddress", "addressLocality": "Austin, United States"}}
        ],
        "ai_work_arrangement": "Remote",
    },
]

_FANTASTIC_BODY = json.dumps(FANTASTIC_FIXTURE_ROWS)


@pytest.mark.anyio
async def test_fantastic_inert_without_key(quota_dir, monkeypatch):
    monkeypatch.delenv("FANTASTIC_JOBS_API_KEY", raising=False)
    source = fantasticjobs.FantasticJobsSource()
    assert not source.enabled
    jobs = await source.fetch_jobs(_FakeClient(), company="all", config={})
    assert jobs == []


@pytest.mark.anyio
async def test_fantastic_skips_call_when_budget_exhausted(quota_dir, monkeypatch):
    monkeypatch.setenv("FANTASTIC_JOBS_API_KEY", "k")
    now = datetime.now(UTC)  # same month bucket the adapter resets on — no reset
    quota_dir.joinpath("fantastic_quota.json").write_text(
        json.dumps({
            "month": now.strftime("%Y-%m"),
            "monthly_jobs": fantasticjobs.MONTHLY_JOBS_QUOTA,
            "week": now.strftime("%G-W%V"),
            "weekly_requests": 0,
        }),
        encoding="utf-8",
    )
    client = _FakeClient(200, _FANTASTIC_BODY)
    jobs = await fantasticjobs.FantasticJobsSource().fetch_jobs(client, company="all", config={})
    assert jobs == []
    assert client.calls == []  # no paid request consumed


@pytest.mark.anyio
async def test_fantastic_pull_parses_official_row_shape(quota_dir, monkeypatch):
    monkeypatch.setenv("FANTASTIC_JOBS_API_KEY", "k")
    client = _FakeClient(200, _FANTASTIC_BODY)
    jobs = await fantasticjobs.FantasticJobsSource().fetch_jobs(
        client, company="all", config={}, compiled_patterns=compile_role_patterns(None),
        cutoff=CUTOFF,
    )

    # Only the AI-matching rows survive the shared title filter…
    assert [j.title for j in jobs] == [
        "Senior AI Engineer, Inference",
        "Machine Learning Engineer, Data",
    ]
    assert jobs[0].company_name == "Acme AI"
    assert jobs[0].title == "Senior AI Engineer, Inference"
    assert jobs[0].apply_url == "https://job-boards.greenhouse.io/acmeai/jobs/4091886009"
    assert jobs[0].canonical_url == jobs[0].apply_url
    assert "New York, New York, United States" in jobs[0].location
    # Row 3: id falls back to a URL hash, locality out of the Place dict.
    assert jobs[1].id.startswith("fantasticjobs:") and "None" not in jobs[1].id
    assert jobs[1].location == "Austin, United States"
    assert jobs[1].remote is True

    # …but the rollback accounting is per returned row (all three billed).
    quota = json.loads((quota_dir / "fantastic_quota.json").read_text(encoding="utf-8"))
    assert quota["monthly_jobs"] == len(FANTASTIC_FIXTURE_ROWS) == 3
    assert quota["weekly_requests"] == 1
    # US-only server-side location filter + shared sensible limit.
    sent_params = client.calls[0]["params"]
    assert sent_params["location"] == "United States"
    assert sent_params["time_frame"] == "24h"
    assert sent_params["limit"] <= fantasticjobs.MAX_JOBS_PER_RUN


@pytest.mark.anyio
async def test_fantastic_failure_still_charges_the_weekly_request(quota_dir, monkeypatch):
    monkeypatch.setenv("FANTASTIC_JOBS_API_KEY", "k")
    client = _FakeClient(401, "")
    jobs = await fantasticjobs.FantasticJobsSource().fetch_jobs(client, company="all", config={})
    assert jobs == []
    quota = json.loads((quota_dir / "fantastic_quota.json").read_text(encoding="utf-8"))
    assert quota["weekly_requests"] == 1  # failed calls consume a request either way


# ── TheirStack ───────────────────────────────────────────────────────────────

THEIRSTACK_FIXTURE_ROWS = {
    "data": [
        {
            "id": 1001,
            "job_title": "Staff AI Product Manager",
            "url": "https://jobs.ashbyhq.com/acme/1111-2222",
            "final_url": "https://acme.ai/careers/staff-ai-pm",
            "source_url": "https://jobs.ashbyhq.com/acme/1111-2222",
            "date_posted": "2026-10-17",
            "discovered_at": "2026-10-18T00:00:00",
            "company": "Acme",  # deprecated field
            "company_object": {"name": "Acme AI", "domain": "acme.ai"},
            "location": "New York",
            "short_location": "New York, NY, United States",
            "country_code": "US",
            "remote": False,
            "hybrid": True,
            "min_annual_salary_usd": 150000,
            "max_annual_salary_usd": 200000,
            "employment_statuses": ["full_time"],
            "is_closed": False,
        },
        {
            "id": 1002,
            "job_title": "Executive Assistant",
            "url": "https://jobs.ashbyhq.com/acme/3333",
            "final_url": "https://acme.ai/careers/ea",
            "company": "Acme",
            "company_object": {"name": "Acme AI"},
            "short_location": "New York, NY",
            "country_code": "US",
            "is_closed": False,
        },
    ]
}


@pytest.mark.anyio
async def test_theirstack_inert_without_key(quota_dir, monkeypatch):
    monkeypatch.delenv("THEIRSTACK_API_KEY", raising=False)
    assert _theirstack_key() == ""
    source = theirstack.TheirStackSource()
    assert not source.enabled
    jobs = await source.fetch_jobs(_FakeClient(), company="all", config={})
    assert jobs == []


@pytest.mark.anyio
async def test_theirstack_refuses_to_run_after_lifetime_budget(quota_dir, monkeypatch):
    monkeypatch.setenv("THEIRSTACK_API_KEY", "k")
    monkeypatch.setattr(theirstack, "TOTAL_CREDIT_BUDGET", 900)
    quota_dir.joinpath("theirstack_quota.json").write_text(
        json.dumps({"credits_spent": 900}), encoding="utf-8"
    )
    client = _FakeClient(200, json.dumps(THEIRSTACK_FIXTURE_ROWS))
    jobs = await theirstack.TheirStackSource().fetch_jobs(client, company="all", config={})
    assert jobs == []
    assert client.calls == []  # budget spent -> zero paid requests


@pytest.mark.anyio
async def test_theirstack_maps_documented_response_and_never_overspends(
    quota_dir, monkeypatch
):
    monkeypatch.setenv("THEIRSTACK_API_KEY", "k")
    # Only 3 credits remain of the lifetime allowance; the sent limit must clamp.
    quota_dir.joinpath("theirstack_quota.json").write_text(
        json.dumps({"credits_spent": theirstack.TOTAL_CREDIT_BUDGET - 3}), encoding="utf-8"
    )
    client = _FakeClient(200, json.dumps(THEIRSTACK_FIXTURE_ROWS))
    jobs = await theirstack.TheirStackSource().fetch_jobs(
        client, company="all", config={}, compiled_patterns=compile_role_patterns(None),
        cutoff=CUTOFF,
    )

    body = client.calls[0]["json"]
    assert client.calls[0]["method"] == "POST"
    assert body["limit"] == 3
    assert body["job_country_code_or"] == ["US"]
    assert body["job_title_or"][0] == "AI Engineer"

    # Only the AI PM row survives the shared title filter…
    assert len(jobs) == 1
    job = jobs[0]
    assert job.company_name == "Acme AI"          # from company_object, not the deprecated field
    assert job.apply_url == "https://acme.ai/careers/staff-ai-pm"  # final_url preferred
    assert job.remote_status == "HYBRID"
    assert job.salary_range == "$150000-$200000 USD"
    jobs_dicts = _as_job_dicts([job])
    assert jobs_dicts and jobs_dicts[0]["applyUrl"].startswith("https://acme.ai")

    # Credit ledger: we returned 2 rows from the API, so 2 credits were spent,
    # even though only 1 survived filtering.
    quota = json.loads((quota_dir / "theirstack_quota.json").read_text(encoding="utf-8"))
    assert quota["credits_spent"] == theirstack.TOTAL_CREDIT_BUDGET - 3 + 2


@pytest.mark.anyio
async def test_theirstack_skips_closed_and_blurred_rows(quota_dir, monkeypatch):
    rows = json.loads(json.dumps(THEIRSTACK_FIXTURE_ROWS))
    # Row 0: not closed, but blurred (partial employer data) — must be skipped.
    rows["data"][0]["is_closed"] = False
    rows["data"][0]["has_blurred_data"] = True
    rows["data"][1]["job_title"] = "Principal AI Engineer"
    monkeypatch.setenv("THEIRSTACK_API_KEY", "k")
    client = _FakeClient(200, json.dumps(rows))
    jobs = await theirstack.TheirStackSource().fetch_jobs(
        client, company="all", config={}, compiled_patterns=compile_role_patterns(None)
    )
    assert [j.title for j in jobs] == ["Principal AI Engineer"]


# ── Google CSE: AI-track terms + budget below the 100/day free tier ─────────


def test_google_cse_defaults_cover_both_ai_tracks_and_fit_free_tier():
    from app.services.job_discover.sources.google_cse import DEFAULT_SEARCH_TERMS
    from app.services.job_discover.google_cse_resolver import DEFAULT_DAILY_BUDGET

    terms = " | ".join(DEFAULT_SEARCH_TERMS[:2])
    assert terms[:13] == "AI Engineer |"
    assert any("AI Product Manager" in t for t in DEFAULT_SEARCH_TERMS)
    assert DEFAULT_DAILY_BUDGET <= 100


def test_google_cse_helper_reads_env():  # covers the env-plumbing contract
    import os

    monkeypatch = pytest.MonkeyPatch()
    monkeypatch.setenv("GOOGLE_CSE_API_KEY", "k")
    monkeypatch.setenv("GOOGLE_CSE_ENGINE_ID", "e")
    from app.services.job_discover.google_cse_resolver import is_configured

    assert is_configured() is True
    monkeypatch.undo()
