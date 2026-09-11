"""Cross-source deduplication: one posting listed on several boards is one job."""

from __future__ import annotations

from app.services.job_discover.dedup import (
    compute_cross_source_key,
    cross_source_deduplicate,
    locations_compatible,
)


def _job(**kwargs):
    base = {
        "companyName": "Vercel",
        "title": "Software Engineer, Backend",
        "location": "San Francisco, CA",
        "url": "https://example.com/1",
        "description": "Build things.",
        "source": "greenhouse",
        "sourcePriority": 95,
    }
    base.update(kwargs)
    return base


def test_ats_and_aggregator_relist_collapse_to_one():
    """The same role on Greenhouse and Jobicy is a single opportunity.

    The aggregator rewrites the URL and truncates the description, so neither
    the canonical-URL index nor the description-hashed fuzzy signature can
    match it — only the company+title cross-source key can.
    """
    jobs = [
        _job(id="gh", url="https://boards.greenhouse.io/vercel/jobs/123", externalId="123"),
        _job(
            id="jb",
            location="USA",
            url="https://jobicy.com/jobs/152938",
            description="Vercel is hiring a backend engineer.",
            source="jobicy",
            sourcePriority=80,
            externalId="152938",
        ),
    ]
    result = cross_source_deduplicate(jobs)
    assert len(result) == 1
    # The authoritative ATS record wins, so Autopilot still gets an apply URL
    # it can actually drive.
    assert "greenhouse.io" in result[0]["url"]
    assert "jobicy" in result[0]["discoverySources"]


def test_same_board_duplicates_are_not_collapsed():
    """Two requisitions on one board sharing a title are two real openings.

    Descriptions differ, as two genuine reqs' would — identical descriptions
    are matched by the older fuzzy-signature tier, which is not what this
    test is about.
    """
    jobs = [
        _job(id="a", location="New York, NY", description="Own ingestion.",
             url="https://boards.greenhouse.io/datadog/jobs/1", externalId="1"),
        _job(id="b", location="New York, NY", description="Own the query engine.",
             url="https://boards.greenhouse.io/datadog/jobs/2", externalId="2"),
    ]
    assert len(cross_source_deduplicate(jobs)) == 2


def test_different_cities_stay_separate():
    jobs = [
        _job(id="a", location="San Francisco, CA", url="https://u/1", source="greenhouse"),
        _job(id="b", location="New York, NY", url="https://u/2", source="jobicy", sourcePriority=80),
    ]
    assert len(cross_source_deduplicate(jobs)) == 2


def test_three_sources_merge_and_keep_all_provenance():
    jobs = [
        _job(id="w", companyName="Fastly", title="Senior SRE - Networks", location="Remote",
             url="https://weworkremotely.com/remote-jobs/fastly", source="weworkremotely", sourcePriority=70),
        _job(id="g", companyName="Fastly", title="SRE - Networks", location="Denver, CO",
             url="https://boards.greenhouse.io/fastly/jobs/9", source="greenhouse", externalId="9"),
        _job(id="j", companyName="Fastly", title="Senior SRE, Networks", location="USA",
             url="https://jobicy.com/jobs/777", source="jobicy", sourcePriority=80),
    ]
    result = cross_source_deduplicate(jobs)
    assert len(result) == 1
    assert set(result[0]["discoverySources"]) == {"weworkremotely", "greenhouse", "jobicy"}


def test_different_companies_never_merge():
    jobs = [
        _job(id="a", companyName="Asana", url="https://u/1"),
        _job(id="b", companyName="Airbnb", url="https://u/2", source="jobicy", sourcePriority=80),
    ]
    assert len(cross_source_deduplicate(jobs)) == 2


def test_cross_source_key_ignores_seniority_prefix():
    assert compute_cross_source_key("fastly", "Senior SRE - Networks") == compute_cross_source_key(
        "fastly", "SRE - Networks"
    )


def test_cross_source_key_empty_without_company_or_title():
    assert compute_cross_source_key("", "Software Engineer") == ""
    assert compute_cross_source_key("stripe", "") == ""


def test_generic_locations_are_compatible_with_anything():
    assert locations_compatible("Remote", "Denver, CO")
    assert locations_compatible("USA", "New York, NY")
    assert locations_compatible("", "Austin, TX")


def test_distinct_cities_are_incompatible():
    assert not locations_compatible("Denver, CO", "Austin, TX")
