"""AI role coverage regression tests (issue #94).

Covers the two scrape-time gaps that dropped AI Engineer / AI Product Manager
roles before this change, and the Fast AI Jobs aggregator adapter:

1. ROLE_FILTERS had empty pm/product groups, so roles="pm" compiled zero
   patterns and matches_title() rejected every title; the swe group had no
   AI-specialized engineer patterns, so "AI Engineer" / "Machine Learning
   Engineer" were dropped even for the roles="swe" night loop.
2. FastAIJobsSource parses the Schema.org ItemList embedded in fastaijobs.com
   role pages into NormalizedJob rows carrying canonical ATS apply URLs.
"""

from __future__ import annotations

import httpx
import pytest

from app.services.job_discover.role_classifier import classify_role
from app.services.job_discover.scraper_service import (
    ROLE_FILTERS,
    compile_role_patterns,
    matches_title,
)
from app.services.job_discover.sources.fastaijobs import (
    FastAIJobsSource,
    parse_item_list_jobs,
)

# ── Role filter: AI engineering titles ───────────────────────────────────────


@pytest.mark.parametrize(
    "title",
    [
        "AI Engineer",
        "Senior AI Engineer",
        "Machine Learning Engineer",
        "Staff ML Engineer",
        "Research Engineer, Post-Training",
        "Applied Scientist, Foundation Models",
        "Inference Engineer",
        "Software Engineer, AI Agents",
    ],
)
def test_ai_engineering_titles_pass_scrape_filter(title):
    compiled = compile_role_patterns(["swe"])
    assert matches_title(title, compiled), f"{title!r} should survive the swe scrape filter"


def test_swe_filter_still_rejects_non_engineering_titles():
    compiled = compile_role_patterns(["swe"])
    assert not matches_title("Executive Assistant", compiled)
    assert not matches_title("Recruiter", compiled)


# ── Role filter: PM titles (the empty-group bug) ─────────────────────────────


def test_pm_group_is_no_longer_empty():
    """roles="pm" used to compile zero patterns, dropping every PM job."""
    assert ROLE_FILTERS["pm"], "pm group must not be empty"
    assert ROLE_FILTERS["product"], "product group must not be empty"


@pytest.mark.parametrize(
    "title",
    [
        "AI Product Manager",
        "Senior Product Manager, Agents",
        "Product Manager II, Generative AI",
        "Staff Product Manager, Agentic Platform",
        "Group Product Manager, AI Models",
        "Technical Product Manager",
        "Head of Product",
        "Product Owner, LLM Platform",
    ],
)
def test_ai_pm_titles_pass_scrape_filter(title):
    compiled = compile_role_patterns(["pm"])
    assert matches_title(title, compiled), f"{title!r} should survive the pm scrape filter"


def test_pm_filter_rejects_project_managers_and_excluded_titles():
    compiled = compile_role_patterns(["pm"])
    assert not matches_title("Construction Project Manager", compiled)
    assert not matches_title("Marketing Director", compiled)


def test_default_scrape_all_groups_keeps_both_tracks():
    """The UI sends roles="" (all groups) - both tracks must survive."""
    compiled = compile_role_patterns(None)
    assert matches_title("AI Engineer", compiled)
    assert matches_title("AI Product Manager", compiled)


# ── Classifier taxonomy ──────────────────────────────────────────────────────


@pytest.mark.parametrize(
    "title,expected",
    [
        ("AI Engineer", "swe"),
        ("Machine Learning Engineer", "swe"),
        ("Applied Scientist, Foundation Models", "swe"),
        ("AI Product Manager", "pm"),
        ("Senior Product Manager, Agents", "pm"),
    ],
)
def test_classify_role_maps_ai_titles(title, expected):
    assert classify_role(title) == expected


# ── Fast AI Jobs adapter ─────────────────────────────────────────────────────

_FIXTURE_HTML = """
<html><head>
<script type="application/ld+json">
{"@context":"https://schema.org","@graph":[
 {"@type":"CollectionPage","@id":"https://www.fastaijobs.com/jobs/role/ai-engineer#page"},
 {"@type":"ItemList","itemListElement":[
  {"@type":"ListItem","position":1,"url":"https://job-boards.greenhouse.io/anthropic/jobs/5445760008","name":"Applied AI Engineer, Beneficial Deployments at Anthropic"},
  {"@type":"ListItem","position":2,"url":"https://jobs.ashbyhq.com/certa/da4d5879-d94d-4f8c-ada4-24bd55520e3","name":"AI Engineer at Certa"},
  {"@type":"ListItem","position":3,"url":"https://jobs.lever.co/tryjeeves/979022dd-3330-404b-ad21-48cede3cd780","name":"Senior AI Engineer at Jeeves"}
 ]}
]}
</script>
<script type="application/ld+json">
{"@type":"BreadcrumbList","itemListElement":[{"@type":"ListItem","position":1,"name":"Home"}]}
</script>
</head><body></body></html>
"""

# The flat shape (ItemList at the JSON-LD root, no @graph wrapper) also parses.
_FLAT_FIXTURE_HTML = """
<script type="application/ld+json">
{"@type":"ItemList","itemListElement":[
 {"@type":"ListItem","position":1,"url":"https://job-boards.greenhouse.io/acme/jobs/9","name":"Backend Engineer at Acme"}
]}
</script>
"""


def test_parse_item_list_extracts_title_company_url():
    rows = parse_item_list_jobs(_FIXTURE_HTML, "ai-engineer")
    assert len(rows) == 3
    title, company, url = rows[0]
    assert title == "Applied AI Engineer, Beneficial Deployments"
    assert company == "Anthropic"
    assert url == "https://job-boards.greenhouse.io/anthropic/jobs/5445760008"


def test_parse_item_list_handles_flat_shape():
    rows = parse_item_list_jobs(_FLAT_FIXTURE_HTML, "ai-engineer")
    assert rows == [("Backend Engineer", "Acme", "https://job-boards.greenhouse.io/acme/jobs/9")]


def test_parse_item_list_tolerates_broken_jsonld():
    html = '<script type="application/ld+json">{"@type":"ItemList","itemListElement":[broken</script>'
    assert parse_item_list_jobs(html, "ai-engineer") == []


def test_parse_item_list_handles_empty_page():
    assert parse_item_list_jobs("<html><body>no data</body></html>", "ai-engineer") == []


class _FakeClient:
    """Stands in for httpx.AsyncClient; serves the fixture for every page."""

    def __init__(self, html: str, status_code: int = 200):
        self.html = html
        self.status_code = status_code
        self.urls: list[str] = []

    async def request(self, *, method, url, headers=None, json=None, params=None, timeout=None):
        self.urls.append(url)
        return httpx.Response(
            self.status_code,
            text=self.html,
            request=httpx.Request(method or "GET", url),
        )


@pytest.mark.anyio
async def test_fastaijobs_adapter_builds_normalized_jobs_with_ats_urls():
    from datetime import UTC, datetime, timedelta

    client = _FakeClient(_FIXTURE_HTML)
    compiled = compile_role_patterns(["swe"])
    jobs = await FastAIJobsSource().fetch_jobs(
        client,
        company="all",
        config={},
        compiled_patterns=compiled,
        cutoff=datetime.now(UTC) - timedelta(hours=24),
    )

    # "Senior AI Engineer at Jeeves" also matches swe; all three are AI titles.
    assert len(jobs) == 3
    first = jobs[0]
    assert first.source == "fastaijobs"
    assert first.source_type == "aggregator"
    assert first.company_name == "Anthropic"
    assert first.apply_url == "https://job-boards.greenhouse.io/anthropic/jobs/5445760008"
    assert first.canonical_url == first.apply_url
    assert first.external_id == "5445760008"
    # One fetch per configured role page.
    assert len(client.urls) == len(FastAIJobsSource.ROLE_PAGES)


@pytest.mark.anyio
async def test_fastaijobs_adapter_filters_non_matching_titles():
    """A page full of non-engineering titles must yield no jobs, not errors."""
    from datetime import UTC, datetime, timedelta

    html = (
        '<script type="application/ld+json">{"@type":"ItemList","itemListElement":['
        '{"@type":"ListItem","position":1,"url":"https://job-boards.greenhouse.io/acme/jobs/1",'
        '"name":"Executive Assistant at Acme"}'
        "]}</script>"
    )
    client = _FakeClient(html)
    jobs = await FastAIJobsSource().fetch_jobs(
        client,
        company="all",
        config={},
        compiled_patterns=compile_role_patterns(["swe"]),
        cutoff=datetime.now(UTC) - timedelta(hours=24),
    )
    assert jobs == []


@pytest.mark.anyio
async def test_fastaijobs_adapter_reports_failure_on_http_error():
    from datetime import UTC, datetime

    client = _FakeClient("", status_code=404)
    source = FastAIJobsSource()
    jobs = await source.fetch_jobs(
        client,
        company="all",
        config={},
        compiled_patterns=compile_role_patterns(["swe"]),
        cutoff=datetime.now(UTC),
    )
    assert jobs == []
    assert source.health.status in ("failing", "degraded")
    assert "404" in (source.health.last_error or "")
