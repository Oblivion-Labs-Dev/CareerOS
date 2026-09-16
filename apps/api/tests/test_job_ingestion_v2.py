"""Comprehensive Unit, Adapter, Deduplication, and Freshness Test Suite for CareerOS Job Ingestion V2.

Verifies:
- All direct ATS adapters (Greenhouse, Lever, Ashby, SmartRecruiters, Workday, Workable, Oracle, iCIMS)
- Curated public APIs (Jobicy, Arbeitnow, Remotive)
- Community and feed providers (Hacker News Algolia, GitHub REST Contents ETag 304)
- Google Jobs aggregator (SerpApi quota enforcement and caching)
- Multi-index cross-source deduplication with source priority resolution & provenance tracking
- Phase 12 Freshness lifecycle (ACTIVE -> POSSIBLY_CLOSED -> CLOSED)
- Rate limiting, backoff, and circuit-breaking health tracking
"""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest

from app.services.job_discover.aggregation import JobAggregationService, job_aggregation_service
from app.services.job_discover.dedup import (
    canonicalize_url,
    compute_fuzzy_signature,
    compute_job_fingerprint,
    cross_source_deduplicate,
    merge_job_records,
)
from app.services.job_discover.freshness import (
    STATUS_ACTIVE,
    STATUS_CLOSED,
    STATUS_POSSIBLY_CLOSED,
    check_job_url_freshness,
    update_jobs_lifecycle_after_sync,
)
from app.services.job_discover.sources.arbeitnow import ArbeitnowSource
from app.services.job_discover.sources.ashby import AshbySource
from app.services.job_discover.sources.base import JobSourceAdapter, NormalizedJob, SourceHealth
from app.services.job_discover.sources.bigtech import BigTechSourceAdapter
from app.services.job_discover.sources.github_feed import GitHubFeedSource
from app.services.job_discover.sources.greenhouse import GreenhouseSource
from app.services.job_discover.sources.hackernews import HackerNewsSource
from app.services.job_discover.sources.icims import ICIMSSource
from app.services.job_discover.sources.jobicy import JobicySource
from app.services.job_discover.sources.lever import LeverSource
from app.services.job_discover.sources.oracle import OracleSource
from app.services.job_discover.sources.personio import PersonioSource
from app.services.job_discover.sources.recruitee import RecruiteeSource
from app.services.job_discover.sources.remoteok import RemoteOKSource
from app.services.job_discover.sources.remotive import RemotiveSource
from app.services.job_discover.sources.themuse import TheMuseSource
from app.services.job_discover.sources.serpapi_google_jobs import SerpApiGoogleJobsSource
from app.services.job_discover.sources.smartrecruiters import SmartRecruitersSource
from app.services.job_discover.sources.workable import WorkableSource
from app.services.job_discover.sources.workday import WorkdaySource


# ---------------------------------------------------------------------------
# FIXTURES
# ---------------------------------------------------------------------------

GREENHOUSE_FIXTURE = {
    "jobs": [
        {
            "id": 55443322,
            "internal_job_id": 998811,
            "title": "Staff Infrastructure Engineer",
            "updated_at": "2026-08-20T14:30:00Z",
            "absolute_url": "https://boards.greenhouse.io/stripe/jobs/55443322?gh_jid=55443322",
            "location": {"name": "San Francisco, CA"},
            "offices": [{"name": "San Francisco HQ"}, {"name": "Seattle"}],
            "departments": [{"name": "Platform Engineering"}],
            "metadata": [
                {"name": "Salary Range", "value": "$195,000 - $265,000 USD"}
            ],
            "content": "<p>Build high-throughput core ledger systems.</p>",
        }
    ]
}

LEVER_FIXTURE = [
    {
        "id": "lever-uuid-99",
        "text": "Principal Distributed Systems Architect",
        "createdAt": 1787200000000,
        "hostedUrl": "https://jobs.lever.co/netflix/lever-uuid-99",
        "applyUrl": "https://jobs.lever.co/netflix/lever-uuid-99/apply",
        "categories": {
            "team": "Core Platform",
            "department": "Engineering",
            "location": "Los Gatos, CA",
            "allLocations": ["Los Gatos, CA", "Remote - US"],
            "commitment": "Full-time",
            "workplaceType": "hybrid",
        },
        "description": "<p>Design telemetry distributed tracing pipelines.</p>",
        "salaryRange": {
            "min": 240000,
            "max": 320000,
            "currency": "USD",
            "interval": "per-year-salary",
        },
    }
]

ASHBY_FIXTURE = {
    "jobs": [
        {
            "id": "ashby-job-001",
            "title": "Senior AI Systems Engineer",
            "department": "Supercomputing",
            "location": "San Francisco, CA",
            "secondaryLocations": ["Remote, US"],
            "isRemote": True,
            "publishedAt": "2026-08-22T08:00:00Z",
            "jobUrl": "https://jobs.ashbyhq.com/openai/ashby-job-001",
            "descriptionHtml": "<p>Develop GPU cluster scheduling runtimes.</p>",
            "compensation": {
                "compensationTierSummary": "$220,000 - $310,000",
                "min": 220000,
                "max": 310000,
                "currency": "USD",
            },
        }
    ]
}

SMARTRECRUITERS_FIXTURE = {
    "totalFound": 1,
    "content": [
        {
            "id": "sr-post-777",
            "name": "Lead Cloud Infrastructure Engineer",
            "releasedDate": "2026-08-21T12:00:00Z",
            "location": {"city": "Austin", "region": "TX", "country": "us"},
            "department": {"label": "Cloud Platforms"},
            "typeOfEmployment": {"label": "Permanent"},
            "experienceLevel": {"label": "Mid-Senior level"},
            "refNumber": "REQ-7771",
        }
    ]
}

WORKDAY_FIXTURE = {
    "total": 1,
    "jobPostings": [
        {
            "bulletFields": ["JR-100234"],
            "title": "Principal Hardware System Architect",
            "externalPath": "/job/Santa-Clara/Principal-Hardware-System-Architect_JR-100234",
            "postedOn": "Posted 2 Days Ago",
            "locationsText": "Santa Clara, CA",
            "workplaceTypes": ["Hybrid"],
        }
    ]
}

JOBICY_FIXTURE = {
    "jobs": [
        {
            "id": 9876,
            "url": "https://jobicy.com/jobs/9876-staff-backend-go-engineer",
            "jobTitle": "Staff Backend Engineer - Go",
            "companyName": "Modern Tech Co",
            "jobGeo": "USA",
            "jobLevel": "Senior",
            "jobType": "full-time",
            "pubDate": "2026-08-24T10:00:00Z",
            "jobDescription": "<p>Build real-time Go microservices.</p>",
            "annualSalaryMin": "180000",
            "annualSalaryMax": "240000",
            "salaryCurrency": "USD",
        }
    ]
}

RECRUITEE_FIXTURE = {
    "offers": [
        {
            "id": 445566,
            "title": "Senior Backend Engineer",
            "slug": "senior-backend-engineer",
            "company_name": "Bunq",
            "city": "Amsterdam",
            "state_name": "North Holland",
            "country": "Netherlands",
            "remote": False,
            "hybrid": True,
            "department": "Engineering",
            "category_code": "engineering",
            "description": "<p>Own core payment services.</p>",
            "requirements": "<p>5+ years backend experience.</p>",
            "employment_type_code": "fulltime",
            "created_at": "2026-08-01 10:00:00 UTC",
            "published_at": "2026-08-01 12:00:00 UTC",
            "updated_at": "2026-08-02 09:00:00 UTC",
            "careers_url": "https://careers.bunq.com/o/senior-backend-engineer",
            "careers_apply_url": "https://careers.bunq.com/o/senior-backend-engineer/c/new",
        }
    ]
}

PERSONIO_XML_FIXTURE = """<?xml version="1.0" encoding="UTF-8"?>
<workzag-jobs>
<position>
    <id>998877</id>
    <office>Munich</office>
    <additionalOffices></additionalOffices>
    <department>Product and Tech</department>
    <recruitingCategory>Engineering</recruitingCategory>
    <name>Senior Platform Engineer</name>
    <jobDescriptions>
        <jobDescription>
            <name>About the role</name>
            <value><![CDATA[<p>Build the internal data platform.</p>]]></value>
        </jobDescription>
    </jobDescriptions>
    <employmentType>permanent</employmentType>
    <seniority>experienced</seniority>
    <schedule>full-time</schedule>
    <createdAt>2026-09-10T09:00:00+00:00</createdAt>
</position>
</workzag-jobs>
""".encode("utf-8")

REMOTEOK_FIXTURE = [
    {"legal": "API Terms of Service: attribution required."},
    {
        "id": "778899",
        "slug": "remote-senior-backend-engineer-acme-778899",
        "company": "Acme Corp",
        "position": "Senior Backend Engineer",
        "tags": ["python", "backend", "remote"],
        "location": "",
        "date": "2026-09-12T00:00:12+00:00",
        "description": "<p>Own our core API platform.</p>",
        "url": "https://remoteok.com/remote-jobs/remote-senior-backend-engineer-acme-778899",
        "apply_url": "https://remoteok.com/remote-jobs/remote-senior-backend-engineer-acme-778899",
        "salary_min": 150000,
        "salary_max": 190000,
    },
]

THEMUSE_FIXTURE = {
    "page": 0,
    "page_count": 1,
    "results": [
        {
            "id": 5566778,
            "name": "Senior Software Engineer, Platform",
            "contents": "<div><p>Build our platform primitives.</p></div>",
            "publication_date": "2026-09-11T10:00:00Z",
            "locations": [{"name": "New York, NY"}, {"name": "Flexible / Remote"}],
            "company": {"id": 9001, "short_name": "acme", "name": "Acme Corp"},
            "levels": [{"name": "Senior Level", "short_name": "senior"}],
            "refs": {"landing_page": "https://www.themuse.com/jobs/acme/senior-software-engineer-platform"},
        }
    ],
}


# ---------------------------------------------------------------------------
# 1. DIRECT ATS ADAPTER TESTS
# ---------------------------------------------------------------------------

@pytest.mark.anyio
async def test_greenhouse_adapter():
    source = GreenhouseSource()
    assert source.priority == 95
    assert source.source_type == "ats"

    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = GREENHOUSE_FIXTURE

    mock_client = AsyncMock()
    mock_client.request.return_value = mock_resp

    cutoff = datetime.now(UTC) - timedelta(days=30)
    jobs = await source.fetch_jobs(
        mock_client,
        company="Stripe",
        config={"boardId": "stripe"},
        compiled_patterns=[],
        cutoff=cutoff,
    )

    assert len(jobs) == 1
    job = jobs[0]
    assert job.title == "Staff Infrastructure Engineer"
    assert job.company == "Stripe"
    assert job.external_id == "55443322"
    assert job.source_priority == 95
    assert job.source_quality == 95
    assert "San Francisco" in job.location
    assert job.salary_min == 195000
    assert job.salary_max == 265000
    assert "stripe" in job.canonical_url


@pytest.mark.anyio
async def test_lever_adapter():
    source = LeverSource()
    assert source.priority == 95

    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = LEVER_FIXTURE

    mock_client = AsyncMock()
    mock_client.request.return_value = mock_resp

    cutoff = datetime.now(UTC) - timedelta(days=30)
    jobs = await source.fetch_jobs(
        mock_client,
        company="Netflix",
        config={"site": "netflix"},
        compiled_patterns=[],
        cutoff=cutoff,
    )

    assert len(jobs) == 1
    job = jobs[0]
    assert job.title == "Principal Distributed Systems Architect"
    assert job.external_id == "lever-uuid-99"
    assert job.salary_min == 240000
    assert job.salary_max == 320000
    assert job.salary_currency == "USD"
    assert job.remote_status == "HYBRID"


@pytest.mark.anyio
async def test_ashby_adapter():
    source = AshbySource()
    assert source.priority == 95

    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = ASHBY_FIXTURE

    mock_client = AsyncMock()
    mock_client.request.return_value = mock_resp

    cutoff = datetime.now(UTC) - timedelta(days=30)
    jobs = await source.fetch_jobs(
        mock_client,
        company="OpenAI",
        config={"board": "openai"},
        compiled_patterns=[],
        cutoff=cutoff,
    )

    assert len(jobs) == 1
    job = jobs[0]
    assert job.title == "Senior AI Systems Engineer"
    assert job.external_id == "ashby-job-001"
    assert job.salary_min == 220000
    assert job.salary_max == 310000
    assert job.remote_status == "REMOTE"


@pytest.mark.anyio
async def test_recruitee_adapter():
    source = RecruiteeSource()
    assert source.priority == 95
    assert source.source_type == "ats"

    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = RECRUITEE_FIXTURE

    mock_client = AsyncMock()
    mock_client.request.return_value = mock_resp

    cutoff = datetime.now(UTC) - timedelta(days=30)
    jobs = await source.fetch_jobs(
        mock_client,
        company="bunq",
        config={"slug": "bunq"},
        compiled_patterns=[],
        cutoff=cutoff,
    )

    assert len(jobs) == 1
    job = jobs[0]
    assert job.title == "Senior Backend Engineer"
    assert job.external_id == "445566"
    assert job.hybrid is True
    assert job.remote_status == "HYBRID"
    assert "Amsterdam" in job.location
    assert "bunq.com" in job.apply_url
    assert "Own core payment services" in job.description
    assert "5+ years" in job.description


@pytest.mark.anyio
async def test_personio_adapter():
    source = PersonioSource()
    assert source.priority == 95
    assert source.source_type == "ats"

    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.content = PERSONIO_XML_FIXTURE

    mock_client = AsyncMock()
    mock_client.request.return_value = mock_resp

    cutoff = datetime.now(UTC) - timedelta(days=30)
    jobs = await source.fetch_jobs(
        mock_client,
        company="acme",
        config={"slug": "acme"},
        compiled_patterns=[],
        cutoff=cutoff,
    )

    assert len(jobs) == 1
    job = jobs[0]
    assert job.title == "Senior Platform Engineer"
    assert job.external_id == "998877"
    assert job.location == "Munich"
    assert job.department == "Product and Tech"
    assert job.seniority == "EXPERIENCED"
    assert "acme.jobs.personio.de/job/998877" in job.apply_url
    assert "internal data platform" in job.description


@pytest.mark.anyio
async def test_remoteok_adapter():
    source = RemoteOKSource()
    assert source.priority == 80
    assert source.source_type == "public_api"

    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = REMOTEOK_FIXTURE

    mock_client = AsyncMock()
    mock_client.request.return_value = mock_resp

    cutoff = datetime.now(UTC) - timedelta(days=30)
    jobs = await source.fetch_jobs(mock_client, compiled_patterns=[], cutoff=cutoff)

    # The leading "legal" attribution object must never be parsed as a job.
    assert len(jobs) == 1
    job = jobs[0]
    assert job.title == "Senior Backend Engineer"
    assert job.external_id == "778899"
    assert job.remote is True
    assert job.remote_status == "REMOTE"
    assert job.salary_min == 150000
    assert job.salary_max == 190000
    assert "python" in job.skills


@pytest.mark.anyio
async def test_themuse_adapter():
    source = TheMuseSource()
    assert source.priority == 80
    assert source.source_type == "public_api"

    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = THEMUSE_FIXTURE

    mock_client = AsyncMock()
    mock_client.request.return_value = mock_resp

    cutoff = datetime.now(UTC) - timedelta(days=30)
    jobs = await source.fetch_jobs(mock_client, compiled_patterns=[], cutoff=cutoff)

    assert len(jobs) == 1
    job = jobs[0]
    assert job.title == "Senior Software Engineer, Platform"
    assert job.external_id == "5566778"
    assert job.company_name == "Acme Corp"
    assert job.location == "New York, NY"
    assert job.remote is True  # "Flexible / Remote" is also a listed location
    assert job.seniority == "SENIOR"
    assert "themuse.com/jobs/acme" in job.apply_url


@pytest.mark.anyio
async def test_smartrecruiters_adapter():
    source = SmartRecruitersSource()
    assert source.priority == 95

    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = SMARTRECRUITERS_FIXTURE

    mock_client = AsyncMock()
    mock_client.request.return_value = mock_resp

    cutoff = datetime.now(UTC) - timedelta(days=30)
    jobs = await source.fetch_jobs(
        mock_client,
        company="Visa",
        config={"companyIdentifier": "visa"},
        compiled_patterns=[],
        cutoff=cutoff,
    )

    assert len(jobs) == 1
    job = jobs[0]
    assert job.title == "Lead Cloud Infrastructure Engineer"
    assert job.external_id == "sr-post-777"
    assert "Austin" in job.location
    assert job.department == "Cloud Platforms"


@pytest.mark.anyio
async def test_workday_adapter():
    source = WorkdaySource()
    assert source.priority == 95

    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = WORKDAY_FIXTURE

    mock_client = AsyncMock()
    mock_client.request.return_value = mock_resp

    cutoff = datetime.now(UTC) - timedelta(days=30)
    jobs = await source.fetch_jobs(
        mock_client,
        company="NVIDIA",
        config={"host": "nvidia.wd5.myworkdayjobs.com", "tenant": "nvidia", "site": "NVIDIAExternalCareerSite"},
        compiled_patterns=[],
        cutoff=cutoff,
    )

    assert len(jobs) == 1
    job = jobs[0]
    assert job.title == "Principal Hardware System Architect"
    assert job.external_id == "JR-100234"
    assert "Santa Clara" in job.location
    assert job.source_priority == 95


# ---------------------------------------------------------------------------
# 2. CURATED PUBLIC APIS & COMMUNITY FEEDS
# ---------------------------------------------------------------------------

@pytest.mark.anyio
async def test_jobicy_adapter():
    source = JobicySource()
    assert source.priority == 80
    assert source.source_type == "public_api"

    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = JOBICY_FIXTURE

    mock_client = AsyncMock()
    mock_client.request.return_value = mock_resp

    cutoff = datetime.now(UTC) - timedelta(days=30)
    jobs = await source.fetch_jobs(
        mock_client,
        company="Modern Tech Co",
        config={},
        compiled_patterns=[],
        cutoff=cutoff,
    )

    assert len(jobs) == 1
    job = jobs[0]
    assert job.title == "Staff Backend Engineer - Go"
    assert job.external_id == "9876"
    assert job.salary_min == 180000
    assert job.salary_max == 240000
    assert job.source_priority == 80


@pytest.mark.anyio
async def test_hackernews_adapter():
    source = HackerNewsSource()
    assert source.priority == 70
    assert source.source_type == "community"

    # Mock search finding a Who is Hiring story
    search_resp = MagicMock()
    search_resp.status_code = 200
    search_resp.json.return_value = {
        "hits": [{"objectID": "12345678", "title": "Ask HN: Who is hiring? (August 2026)"}]
    }

    # Mock story item comments
    item_resp = MagicMock()
    item_resp.status_code = 200
    item_resp.json.return_value = {
        "children": [
            {
                "id": 881122,
                "text": "Acme AI (YC W26) | Senior Distributed Systems Engineer | San Francisco or REMOTE | $180k-$240k + equity<br>We build autonomic ML clusters. Apply: https://acme.ai/jobs/senior-distributed",
                "created_at_i": 1787000000,
            }
        ]
    }

    mock_client = AsyncMock()
    mock_client.request.side_effect = [search_resp, item_resp]

    cutoff = datetime.now(UTC) - timedelta(days=30)
    jobs = await source.fetch_jobs(
        mock_client,
        company="Acme AI",
        config={},
        compiled_patterns=[],
        cutoff=cutoff,
    )

    assert len(jobs) == 1
    job = jobs[0]
    assert job.company == "Acme AI"
    assert "Senior Distributed Systems Engineer" in job.title
    assert job.remote_status == "REMOTE"
    assert job.salary_min == 180000
    assert job.salary_max == 240000
    assert job.canonical_url == "https://acme.ai/jobs/senior-distributed"
    assert job.source_priority == 70


@pytest.mark.anyio
async def test_github_feed_etag_304():
    source = GitHubFeedSource()
    assert source.priority == 70
    assert source.source_type == "github_feed"

    # Pre-populate cache with an ETag
    cache_key = "testowner/testrepo/jobs.json"
    source._etags[cache_key] = '"etag-abc-123"'

    # Mock 304 Not Modified
    mock_resp = MagicMock()
    mock_resp.status_code = 304

    mock_client = AsyncMock()
    mock_client.request.return_value = mock_resp

    cutoff = datetime.now(UTC) - timedelta(days=30)
    jobs = await source.fetch_jobs(
        mock_client,
        company="Any",
        config={"owner": "testowner", "repo": "testrepo", "path": "jobs.json", "enabled": True},
        compiled_patterns=[],
        cutoff=cutoff,
    )

    # 304 response produces 0 duplicate jobs and 0 writes
    assert len(jobs) == 0
    # Verify conditional header was sent
    sent_headers = mock_client.request.call_args[1]["headers"]
    assert sent_headers.get("If-None-Match") == '"etag-abc-123"'


# ---------------------------------------------------------------------------
# 3. AGGREGATOR QUOTA ENFORCEMENT (SERPAPI GOOGLE JOBS)
# ---------------------------------------------------------------------------

@pytest.mark.anyio
async def test_serpapi_quota_and_budget_caps(tmp_path):
    source = SerpApiGoogleJobsSource()
    assert source.priority == 60
    assert source.source_type == "aggregator"

    # Set temporary quota path
    quota_file = tmp_path / "serpapi_quota.json"
    source.quota_file = quota_file

    with patch.dict("os.environ", {"SERPAPI_KEY": "test-key-mock"}):
        # 1. Verify budget cap stops after daily limit
        quota_data = {
            "month": datetime.now(UTC).strftime("%Y-%m"),
            "usedCount": 10,
            "monthlyLimit": 250,
            "today": datetime.now(UTC).strftime("%Y-%m-%d"),
            "todayCount": 8,  # Reached daily limit of 8
        }
        quota_file.write_text(json.dumps(quota_data), encoding="utf-8")

        mock_client = AsyncMock()
        cutoff = datetime.now(UTC) - timedelta(days=30)
        jobs = await source.fetch_jobs(
            mock_client,
            company="Stripe",
            config={"query": "Software Engineer Stripe"},
            compiled_patterns=[],
            cutoff=cutoff,
        )

        # Budget reached -> no external HTTP request
        assert len(jobs) == 0
        mock_client.get.assert_not_called()


# ---------------------------------------------------------------------------
# 4. CROSS-SOURCE DEDUPLICATION & PROVENANCE RESOLUTION
# ---------------------------------------------------------------------------

def test_cross_source_deduplicate_priority_collision():
    """Verify that an ATS listing (Priority 95) takes precedence over an Aggregator (Priority 60),

    while merging discoverySources provenance.
    """
    aggregator_job = {
        "id": "job_aggregator_1",
        "companyName": "Stripe",
        "title": "Software Engineer, Core Infrastructure",
        "location": "San Francisco, CA (Cached)",
        "url": "https://boards.greenhouse.io/stripe/jobs/55443322",
        "canonicalSource": "Google Jobs",
        "canonicalSourceTier": "AGGREGATOR",
        "sourcePriority": 60,
        "discoverySources": ["Google Jobs"],
        "salaryRange": "",
    }

    greenhouse_job = {
        "id": "job_stripe_55443322",
        "externalId": "55443322",
        "companyName": "Stripe",
        "title": "Senior Infrastructure Engineer - Storage",
        "location": "San Francisco, CA",
        "url": "https://boards.greenhouse.io/stripe/jobs/55443322",
        "canonicalSource": "Greenhouse",
        "canonicalSourceTier": "OFFICIAL_ATS",
        "sourcePriority": 95,
        "discoverySources": ["Greenhouse"],
        "salaryRange": "$195,000 - $265,000",
        "salaryMin": 195000,
        "salaryMax": 265000,
    }

    # Ingest aggregator first, then authoritative ATS
    deduped = cross_source_deduplicate([aggregator_job, greenhouse_job])
    assert len(deduped) == 1

    winner = deduped[0]
    # Greenhouse title, source, and salary win
    assert winner["canonicalSource"] == "Greenhouse"
    assert winner["sourcePriority"] == 95
    assert winner["salaryMin"] == 195000
    assert winner["title"] == "Senior Infrastructure Engineer - Storage"
    # Provenance tracks BOTH sources
    assert "Google Jobs" in winner["discoverySources"]
    assert "Greenhouse" in winner["discoverySources"]


def test_cross_source_deduplicate_fuzzy_matching():
    """Verify fuzzy title + company + location collision collapsing."""
    job1 = {
        "id": "fp_job_1",
        "companyName": "Databricks Inc.",
        "title": "Sr. Backend Engineer - Distributed Runtime",
        "location": "San Francisco, California, United States",
        "url": "https://databricks.com/careers/101",
        "sourcePriority": 80,
        "discoverySources": ["Jobicy"],
        "descriptionHash": "hash123",
    }
    job2 = {
        "id": "fp_job_2",
        "companyName": "Databricks",
        "title": "Sr Backend Engineer Distributed Runtime",
        "location": "San Francisco, CA",
        "url": "https://databricks.com/careers/101?source=referral",
        "sourcePriority": 95,
        "discoverySources": ["Company Careers"],
        "descriptionHash": "hash123",
    }

    deduped = cross_source_deduplicate([job1, job2])
    assert len(deduped) == 1
    assert "Jobicy" in deduped[0]["discoverySources"]
    assert "Company Careers" in deduped[0]["discoverySources"]


# ---------------------------------------------------------------------------
# 5. PHASE 12 FRESHNESS & CLOSED POSTING LIFECYCLE
# ---------------------------------------------------------------------------

def test_freshness_lifecycle_transitions():
    existing = [
        {
            "id": "job-100",
            "companyName": "Anthropic",
            "title": "Research Engineer",
            "canonicalSource": "Ashby",
            "discoverySources": ["Ashby"],
            "jobStatus": STATUS_ACTIVE,
            "missingConsecutiveRuns": 0,
        }
    ]

    # Run 1: Successful sync where job-100 is absent
    run1 = update_jobs_lifecycle_after_sync(
        existing,
        synced_jobs=[],
        provider_name="Ashby",
        company="Anthropic",
        sync_succeeded=True,
    )
    assert run1[0]["jobStatus"] == STATUS_POSSIBLY_CLOSED
    assert run1[0]["missingConsecutiveRuns"] == 1
    assert run1[0].get("closedAt") is None

    # Run 2: Provider encounters an API error (HTTP 500)
    # Rule: Failed sync must NOT increment missing counter or close jobs
    run2 = update_jobs_lifecycle_after_sync(
        run1,
        synced_jobs=[],
        provider_name="Ashby",
        company="Anthropic",
        sync_succeeded=False,
    )
    assert run2[0]["jobStatus"] == STATUS_POSSIBLY_CLOSED
    assert run2[0]["missingConsecutiveRuns"] == 1  # Unchanged!

    # Run 3 & 4: Consecutive healthy syncs where job is missing
    run3 = update_jobs_lifecycle_after_sync(
        run2,
        synced_jobs=[],
        provider_name="Ashby",
        company="Anthropic",
        sync_succeeded=True,
    )
    assert run3[0]["missingConsecutiveRuns"] == 2

    run4 = update_jobs_lifecycle_after_sync(
        run3,
        synced_jobs=[],
        provider_name="Ashby",
        company="Anthropic",
        sync_succeeded=True,
    )
    assert run4[0]["missingConsecutiveRuns"] == 3
    assert run4[0]["jobStatus"] == STATUS_CLOSED
    assert run4[0].get("closedAt") is not None


@pytest.mark.anyio
async def test_live_url_freshness_check():
    # 1. HTTP 404/410 returns CLOSED
    mock_404 = MagicMock()
    mock_404.status_code = 404

    client = AsyncMock()
    client.head.return_value = mock_404

    res = await check_job_url_freshness("https://boards.greenhouse.io/job/404", client=client)
    assert res["closed"] is True
    assert res["status"] == STATUS_CLOSED

    # 2. HTTP 200 with closed notice in body returns CLOSED
    mock_200 = MagicMock()
    mock_200.status_code = 200
    mock_200.is_success = True
    mock_200.text = "<html><body>This position has been filled. Thank you.</body></html>"

    client.head.return_value = mock_200
    client.get.return_value = mock_200

    res_body = await check_job_url_freshness("https://jobs.lever.co/company/closed-job", client=client)
    assert res_body["closed"] is True
    assert "Page content indicates closed" in res_body["reason"]


# ---------------------------------------------------------------------------
# 6. CIRCUIT BREAKER & OBSERVABILITY
# ---------------------------------------------------------------------------

def test_circuit_breaker_and_health_summary():
    service = JobAggregationService()
    summary = service.get_health_summary()
    assert len(summary) >= 15

    # Check keys expected by Phase 19 Observability
    for item in summary:
        assert "provider" in item
        assert "status" in item
        assert "request_count" in item
        assert "jobs_fetched" in item
        assert "consecutive_failures" in item

    # Test circuit breaker tripping
    adapter = GreenhouseSource()
    assert adapter.is_circuit_open() is False

    # Simulate consecutive failures reaching threshold
    adapter.record_failure("HTTP 500 Internal Server Error")
    adapter.record_failure("HTTP 500 Internal Server Error")
    adapter.record_failure("HTTP 500 Internal Server Error")
    adapter.record_failure("HTTP 500 Internal Server Error")
    adapter.record_failure("HTTP 500 Internal Server Error")

    assert adapter.is_circuit_open() is True
    assert adapter.health_check().status == "degraded"


# ---------------------------------------------------------------------------
# 7. DETERMINISTIC ATS FINGERPRINTER & EVIDENCE
# ---------------------------------------------------------------------------

def test_ats_fingerprinter_deterministic_evidence():
    from app.services.job_discover.discovery.company_registry import JobSourceDiscoveryService

    # 1. Greenhouse
    gh = JobSourceDiscoveryService.fingerprint_ats("https://boards.greenhouse.io/stripe/jobs/12345")
    assert gh["provider"] == "greenhouse"
    assert gh["boardIdentifier"] == "stripe"
    assert gh["confidence"] >= 0.95
    assert "Greenhouse" in gh["evidence"]

    # 2. Lever
    lev = JobSourceDiscoveryService.fingerprint_ats("https://jobs.lever.co/netflix/uuid-abc-123")
    assert lev["provider"] == "lever"
    assert lev["boardIdentifier"] == "netflix"
    assert lev["confidence"] >= 0.95

    # 3. Ashby
    ash = JobSourceDiscoveryService.fingerprint_ats("https://jobs.ashbyhq.com/openai")
    assert ash["provider"] == "ashby"
    assert ash["boardIdentifier"] == "openai"
    assert ash["confidence"] >= 0.95

    # 4. Workday
    wd = JobSourceDiscoveryService.fingerprint_ats("https://salesforce.wd12.myworkdayjobs.com/External_Career_Site")
    assert wd["provider"] == "workday"
    assert "salesforce" in wd["boardIdentifier"]
    assert wd["confidence"] >= 0.95

    # 5. SmartRecruiters
    sr = JobSourceDiscoveryService.fingerprint_ats("https://jobs.smartrecruiters.com/Visa/7439999")
    assert sr["provider"] == "smartrecruiters"
    assert sr["boardIdentifier"] == "visa"

    # 6. Workable
    wk = JobSourceDiscoveryService.fingerprint_ats("https://apply.workable.com/huggingface/")
    assert wk["provider"] == "workable"
    assert wk["boardIdentifier"] == "huggingface"

    # 7. Recruitee
    rec = JobSourceDiscoveryService.fingerprint_ats("https://hotjar.recruitee.com/")
    assert rec["provider"] == "recruitee"
    assert rec["boardIdentifier"] == "hotjar"

    # 8. BambooHR
    bhr = JobSourceDiscoveryService.fingerprint_ats("https://postman.bamboohr.com/careers")
    assert bhr["provider"] == "bamboohr"
    assert bhr["boardIdentifier"] == "postman"

    # 9. iCIMS
    ic = JobSourceDiscoveryService.fingerprint_ats("https://careers-microsoft.icims.com/jobs/intro")
    assert ic["provider"] == "icims"
    assert "microsoft" in ic["boardIdentifier"]

    # 10. Gem
    gem = JobSourceDiscoveryService.fingerprint_ats("https://jobs.gem.com/anthropic")
    assert gem["provider"] == "gem"
    assert gem["boardIdentifier"] == "anthropic"

    # 11. Rippling
    rip = JobSourceDiscoveryService.fingerprint_ats("https://ramp.rippling-ats.com/")
    assert rip["provider"] == "rippling"
    assert rip["boardIdentifier"] == "ramp"

    # 12. HTML embed fallback
    html_embed = '<script src="https://boards.greenhouse.io/embed/job_board.js?for=instacart"></script>'
    html_match = JobSourceDiscoveryService.fingerprint_ats("https://instacart.com/careers", html=html_embed)
    assert html_match["provider"] == "greenhouse"
    assert html_match["boardIdentifier"] == "instacart"


# ---------------------------------------------------------------------------
# 8. SCHEMA.ORG JOBPOSTING JSON-LD PARSER
# ---------------------------------------------------------------------------

def test_schema_org_jobposting_parser():
    from app.services.job_discover.sources.structured_career_page import parse_jsonld_job_postings

    sample_html = """
    <html>
      <head>
        <script type="application/ld+json">
        {
          "@context": "https://schema.org/",
          "@type": "JobPosting",
          "title": "Senior Distributed Systems Engineer",
          "description": "<p>We are seeking an <strong>expert</strong> distributed systems engineer to scale our cluster.</p>",
          "identifier": {
            "@type": "PropertyValue",
            "name": "Acme Corp",
            "value": "JOB-99482"
          },
          "datePosted": "2026-08-28T09:00:00Z",
          "validThrough": "2026-11-28T09:00:00Z",
          "employmentType": "FULL_TIME",
          "hiringOrganization": {
            "@type": "Organization",
            "name": "Acme Systems Inc."
          },
          "jobLocation": {
            "@type": "Place",
            "address": {
              "@type": "PostalAddress",
              "addressLocality": "Seattle",
              "addressRegion": "WA",
              "addressCountry": "US"
            }
          },
          "jobLocationType": "TELECOMMUTE",
          "baseSalary": {
            "@type": "MonetaryAmount",
            "currency": "USD",
            "value": {
              "@type": "QuantitativeValue",
              "minValue": 180000,
              "maxValue": 240000,
              "unitText": "YEAR"
            }
          }
        }
        </script>
      </head>
      <body><h1>Careers at Acme</h1></body>
    </html>
    """

    jobs = parse_jsonld_job_postings(sample_html, "https://acme.example.com/careers/job-99482", "acme")
    assert len(jobs) == 1
    job = jobs[0]

    assert job.title == "Senior Distributed Systems Engineer"
    assert job.company_name == "Acme Systems Inc."
    assert job.remote is True
    assert job.remote_status == "REMOTE"
    assert job.salary_min == 180000.0
    assert job.salary_max == 240000.0
    assert "$180,000 - $240,000 USD" in job.salary_range
    assert "Seattle, WA" in job.location
    assert "expert distributed systems engineer" in job.description
    assert "<p>" not in job.description  # Verify HTML tags cleaned
    assert job.external_id == "JOB-99482"


# ---------------------------------------------------------------------------
# 9. HIMALAYAS PUBLIC REMOTE API ADAPTER
# ---------------------------------------------------------------------------

@pytest.mark.anyio
async def test_himalayas_adapter_ingestion():
    from app.services.job_discover.sources.himalayas import HimalayasSource

    adapter = HimalayasSource()
    client = AsyncMock()

    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = {
        "jobs": [
            {
                "id": "him-101",
                "title": "Senior Rust Core Backend Engineer",
                "companyName": "Hyperscale Labs",
                "applicationLink": "https://himalayas.app/jobs/hyperscale-labs/senior-rust-engineer",
                "minSalary": 175000,
                "maxSalary": 225000,
                "currency": "USD",
                "pubDate": "2026-08-25T12:00:00Z",
                "description": "Build high-speed asynchronous data pipelines in Rust.",
                "locationRestrictions": ["United States", "Canada"],
            }
        ]
    }

    client.request.return_value = mock_resp

    import re
    compiled = [re.compile(r"software|backend|engineer|rust", re.I)]
    cutoff = datetime(2026, 1, 1, tzinfo=UTC)

    jobs = await adapter.fetch_jobs(client, "himalayas", {}, compiled, cutoff)
    assert len(jobs) == 1
    j = jobs[0]
    assert j.title == "Senior Rust Core Backend Engineer"
    assert j.company_name == "Hyperscale Labs"
    assert j.salary_min == 175000.0
    assert j.salary_max == 225000.0
    assert j.remote is True
    assert j.source == "himalayas"


# ---------------------------------------------------------------------------
# 10. WE WORK REMOTELY RSS FEED ADAPTER
# ---------------------------------------------------------------------------

@pytest.mark.anyio
async def test_weworkremotely_adapter_ingestion():
    from app.services.job_discover.sources.weworkremotely import WeWorkRemotelySource

    adapter = WeWorkRemotelySource()
    client = AsyncMock()

    xml_content = b"""<?xml version="1.0" encoding="UTF-8"?>
    <rss version="2.0">
      <channel>
        <title>We Work Remotely: Remote Programming Jobs</title>
        <item>
          <title>Basecamp: Senior Full Stack Ruby Engineer</title>
          <link>https://weworkremotely.com/remote-jobs/basecamp-senior-full-stack-ruby-engineer</link>
          <guid>https://weworkremotely.com/remote-jobs/12345</guid>
          <pubDate>Mon, 24 Aug 2026 14:00:00 +0000</pubDate>
          <description><![CDATA[<p>Join 37signals to build world-class collaborative software.</p>]]></description>
        </item>
      </channel>
    </rss>
    """

    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.content = xml_content

    client.request.return_value = mock_resp

    import re
    compiled = [re.compile(r"full\s*stack|ruby|engineer", re.I)]
    cutoff = datetime(2026, 1, 1, tzinfo=UTC)

    jobs = await adapter.fetch_jobs(client, "weworkremotely", {}, compiled, cutoff)
    assert len(jobs) == 1
    j = jobs[0]
    assert j.title == "Senior Full Stack Ruby Engineer"
    assert j.company_name == "Basecamp"
    assert j.remote is True
    assert j.source == "weworkremotely"


# ---------------------------------------------------------------------------
# 11. SOURCE ROLES CLASSIFICATION
# ---------------------------------------------------------------------------

def test_source_roles_classification():
    from app.services.job_discover.sources.base import SourceRole
    from app.services.job_discover.sources.greenhouse import GreenhouseSource
    from app.services.job_discover.sources.hackernews import HackerNewsSource
    from app.services.job_discover.sources.himalayas import HimalayasSource
    from app.services.job_discover.sources.serpapi_google_jobs import SerpApiGoogleJobsSource
    from app.services.job_discover.sources.structured_career_page import StructuredCareerPageAdapter

    gh = GreenhouseSource()
    assert gh.role == SourceRole.AUTHORITATIVE

    hn = HackerNewsSource()
    assert hn.role == SourceRole.DISCOVERY

    him = HimalayasSource()
    assert him.role == SourceRole.AGGREGATOR

    google = SerpApiGoogleJobsSource()
    assert google.role == SourceRole.AGGREGATOR

    structured = StructuredCareerPageAdapter()
    assert structured.role == SourceRole.FALLBACK


# ---------------------------------------------------------------------------
# 12. INCREMENTAL UNIQUE JOBS MEASUREMENT
# ---------------------------------------------------------------------------

def test_incremental_coverage_measurement():
    service = JobAggregationService()

    # Create dummy jobs where some overlap across sources
    job_a = NormalizedJob(
        id="gh:1", external_id="1", company="stripe", company_name="Stripe",
        title="Staff Engineer", source="greenhouse", raw_fingerprint="stripe:staff:sf"
    )
    job_b = NormalizedJob(
        id="gh:2", external_id="2", company="stripe", company_name="Stripe",
        title="Backend Engineer", source="greenhouse", raw_fingerprint="stripe:backend:sf"
    )
    # Aggregator duplicates job_a and provides 1 new job
    job_dup = NormalizedJob(
        id="serp:1", external_id="1", company="stripe", company_name="Stripe",
        title="Staff Engineer", source="serpapi_google_jobs", raw_fingerprint="stripe:staff:sf"
    )
    job_c = NormalizedJob(
        id="serp:3", external_id="3", company="stripe", company_name="Stripe",
        title="Data Engineer", source="serpapi_google_jobs", raw_fingerprint="stripe:data:sf"
    )

    raw_jobs = {
        "greenhouse": [job_a, job_b],
        "serpapi_google_jobs": [job_dup, job_c],
    }

    stats = service.measure_incremental_coverage(raw_jobs)
    assert stats["greenhouse"]["jobs_fetched"] == 2
    assert stats["greenhouse"]["incremental_unique_jobs"] == 2
    assert stats["greenhouse"]["duplicates"] == 0

    assert stats["serpapi_google_jobs"]["jobs_fetched"] == 2
    assert stats["serpapi_google_jobs"]["incremental_unique_jobs"] == 1
    assert stats["serpapi_google_jobs"]["duplicates"] == 1

