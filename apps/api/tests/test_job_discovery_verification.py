"""Test suite for Job Discovery, Extraction, Verification, Freshness, and Deduplication Subsystem."""

import pytest
from app.services.job_discover.job_verification_engine import (
    CanonicalSourceType,
    PostingDateConfidence,
    RemoteStatus,
    detect_remote_status,
    normalize_seniority,
    parse_posting_date,
    resolve_canonical_source,
    verify_and_normalize_job,
)


def test_canonical_source_resolution():
    tier, name = resolve_canonical_source("https://boards.greenhouse.io/workato/jobs/12345")
    assert tier == CanonicalSourceType.OFFICIAL_ATS
    assert name == "Greenhouse"

    tier, name = resolve_canonical_source("https://docusign.wd1.myworkdayjobs.com/Careers/job/123")
    assert tier == CanonicalSourceType.OFFICIAL_ATS
    assert name == "Workday"

    tier, name = resolve_canonical_source("https://www.linkedin.com/jobs/view/99999")
    assert tier == CanonicalSourceType.MAJOR_JOB_BOARD
    assert name == "LinkedIn"


def test_date_provenance_separation():
    # Valid ISO date
    date, conf = parse_posting_date("2026-08-18T10:00:00Z")
    assert conf == PostingDateConfidence.HIGH
    assert "2026-08-18" in str(date)

    # Crawl / aggregator index timestamp should be rejected as posting_date
    date, conf = parse_posting_date("Indexed 2 days ago")
    assert date is None
    assert conf == PostingDateConfidence.UNVERIFIED


def test_remote_and_seniority_normalization():
    assert detect_remote_status(location_raw="San Francisco, CA (Remote)") == RemoteStatus.REMOTE
    assert detect_remote_status(location_raw="Seattle, WA", workplace_type="Hybrid") == RemoteStatus.HYBRID

    assert normalize_seniority("Senior Software Engineer III") == "SENIOR"
    assert normalize_seniority("Staff AI Engineer") == "STAFF"
    assert normalize_seniority("Software Engineering Intern") == "INTERN"


def test_verify_and_normalize_job():
    raw = {
        "company": "Stripe",
        "title": "Software Engineer - Automation & AI",
        "url": "https://stripe.com/jobs/listing/software-engineer-automation/69102",
        "datePosted": "2026-08-18T12:00:00Z",
        "location": "Remote",
        "description": "Build agentic automation pipelines using Python and LLMs.",
    }

    normalized = verify_and_normalize_job(raw, discovery_source="LinkedIn Feed")

    assert normalized["company"] == "Stripe"
    assert normalized["posting_date_confidence"] == PostingDateConfidence.HIGH.value
    assert normalized["remote_status"] == RemoteStatus.REMOTE.value
    assert "LinkedIn Feed" in normalized["discovery_sources"]
    assert normalized["verification_status"] == "FULL"
    assert len(normalized["description_hash"]) == 64
