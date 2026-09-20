"""Discovery through the search index must yield applyable, correctly-attributed postings.

One discovery query returns up to ten postings that were not in the pipeline at
all, where a per-job lookup spends the same quota unit on one already-known job.
That only holds if the result URL is genuinely applyable and the employer is
recovered correctly, since a search result gives a page title rather than a
structured company field.
"""

from __future__ import annotations

import pytest

from app.services.job_discover.google_cse_resolver import company_from_ats_url
from app.services.job_discover.sources.google_cse import GoogleCseJobSource


@pytest.mark.parametrize(
    ("url", "expected"),
    [
        # First path segment on the board-style ATSs.
        ("https://job-boards.greenhouse.io/affirm/jobs/7636414003", "affirm"),
        ("https://boards.greenhouse.io/nice/jobs/4862935101", "nice"),
        ("https://jobs.lever.co/2brains/4ce74e51-df88-42a5-afa8", "2brains"),
        ("https://jobs.ashbyhq.com/makai-labs/f64bb7f7", "makai-labs"),
        # Subdomain on the enterprise tenants.
        ("https://gm.wd5.myworkdayjobs.com/en-US/careers/job/X", "gm"),
        ("https://usbank.taleo.net/careersection/jobdetail.ftl", "usbank"),
        ("https://careers-collins.icims.com/jobs/12345/job", "collins"),
        # Greenhouse's embed endpoint carries no company in the path.
        ("https://job-boards.greenhouse.io/embed/job_app?token=x", ""),
    ],
)
def test_company_recovered_from_url_shape(url, expected):
    assert company_from_ats_url(url) == expected


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("Senior Software Engineer - Affirm - Greenhouse", "Senior Software Engineer"),
        ("Job Application for Staff Software Engineer at Acme", "Staff Software Engineer"),
        ("Senior Backend Engineer | Lever", "Senior Backend Engineer"),
        ("Machine Learning Engineer", "Machine Learning Engineer"),
    ],
)
def test_board_furniture_is_stripped_from_titles(raw, expected):
    """Result titles carry board branding the role filters should never see."""
    assert GoogleCseJobSource._clean_title(raw) == expected


def test_normalized_posting_is_marked_applyable():
    item = {
        "url": "https://job-boards.greenhouse.io/affirm/jobs/7636414003",
        "title": "Senior Software Engineer",
        "snippet": "Affirm is hiring a remote Senior Software Engineer",
        "company": "affirm",
    }
    job = GoogleCseJobSource._normalize(item, "Senior Software Engineer")
    assert job.apply_url == item["url"]
    assert job.company_name == "Affirm"
    assert job.source_metadata["hasDirectEmployerUrl"] is True
    assert job.remote is True


def test_source_is_inert_without_credentials(monkeypatch):
    """No credentials must mean no quota spent and no error raised."""
    import asyncio

    monkeypatch.delenv("GOOGLE_CSE_API_KEY", raising=False)
    monkeypatch.delenv("GOOGLE_CSE_ENGINE_ID", raising=False)
    jobs = asyncio.run(GoogleCseJobSource().fetch_jobs(client=None))  # type: ignore[arg-type]
    assert jobs == []
