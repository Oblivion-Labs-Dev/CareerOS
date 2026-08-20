"""Unit and normalization test suite for CareerOS Multi-Source Job Aggregation."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from app.services.job_discover.dedup import canonicalize_url, compute_job_fingerprint, deduplicate_jobs
from app.services.job_discover.discovery.company_registry import JobSourceDiscoveryService
from app.services.job_discover.sources.ashby import AshbySource
from app.services.job_discover.sources.base import NormalizedJob
from app.services.job_discover.sources.generic_jsonld import parse_jsonld_job_postings
from app.services.job_discover.sources.greenhouse import GreenhouseSource
from app.services.job_discover.sources.lever import LeverSource
from app.services.job_discover.sources.workday import WorkdaySource


def test_canonicalize_url():
    url = "https://boards.greenhouse.io/stripe/jobs/12345?utm_source=linkedin&utm_medium=cpc&ref=xyz"
    clean = canonicalize_url(url)
    assert clean == "https://boards.greenhouse.io/stripe/jobs/12345"


def test_compute_job_fingerprint():
    fp1 = compute_job_fingerprint("Stripe", "Senior Software Engineer", "San Francisco, CA", "https://stripe.com/jobs/1")
    fp2 = compute_job_fingerprint("stripe", "Senior Software Engineer", "San Francisco, CA", "https://stripe.com/jobs/1?utm_source=test")
    assert fp1 == fp2


def test_deduplicate_jobs():
    jobs = [
        {"id": "j1", "companyName": "Stripe", "title": "SWE", "url": "https://stripe.com/jobs/1?utm_source=a"},
        {"id": "j2", "companyName": "Stripe", "title": "SWE", "url": "https://stripe.com/jobs/1?utm_source=b"},
    ]
    deduped = deduplicate_jobs(jobs)
    assert len(deduped) == 1
    assert deduped[0]["url"] == "https://stripe.com/jobs/1"


def test_source_discovery_urls():
    res_gh = JobSourceDiscoveryService.detect_from_url("https://boards.greenhouse.io/stripe")
    assert res_gh is not None
    assert res_gh.detected_source == "greenhouse"
    assert res_gh.source_config["boardId"] == "stripe"

    res_lever = JobSourceDiscoveryService.detect_from_url("https://jobs.lever.co/netflix")
    assert res_lever is not None
    assert res_lever.detected_source == "lever"

    res_ashby = JobSourceDiscoveryService.detect_from_url("https://jobs.ashbyhq.com/openai")
    assert res_ashby is not None
    assert res_ashby.detected_source == "ashby"

    res_wd = JobSourceDiscoveryService.detect_from_url("https://nvidia.wd5.myworkdayjobs.com/NVIDIAExternalCareerSite")
    assert res_wd is not None
    assert res_wd.detected_source == "workday"


def test_parse_jsonld_job_postings():
    html = """
    <html>
      <head>
        <script type="application/ld+json">
        {
          "@context": "https://schema.org/",
          "@type": "JobPosting",
          "title": "Backend Infrastructure Engineer",
          "description": "<p>Build distributed systems at scale.</p>",
          "datePosted": "2026-08-15T10:00:00Z",
          "identifier": {
            "@type": "PropertyValue",
            "name": "Acme",
            "value": "JOB-9988"
          },
          "jobLocation": {
            "@type": "Place",
            "address": {
              "@type": "PostalAddress",
              "addressLocality": "San Francisco",
              "addressRegion": "CA",
              "addressCountry": "US"
            }
          },
          "url": "/careers/job-9988"
        }
        </script>
      </head>
    </html>
    """
    jobs = parse_jsonld_job_postings(html, "https://acme.com/careers", "acme")
    assert len(jobs) == 1
    job = jobs[0]
    assert job.title == "Backend Infrastructure Engineer"
    assert job.external_id == "JOB-9988"
    assert job.location == "San Francisco, CA, US"
    assert job.source_url == "https://acme.com/careers/job-9988"
    assert "distributed systems" in job.description
