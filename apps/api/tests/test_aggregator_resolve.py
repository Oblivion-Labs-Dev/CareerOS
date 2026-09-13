"""Aggregator listings must resolve to the employer's own application URL.

The matching parts are pure functions, so they are pinned here without any
network. The one test that does reach the public board APIs is marked so it can
be skipped offline — it is the only way to catch an API whose shape changed.
"""

import pytest

from app.services.job_discover.aggregator_resolve import (
    _board_tokens,
    _match_job,
    _parse_himalayas,
    is_aggregator_url,
    resolve_aggregator_url,
)

HIMALAYAS = (
    "https://himalayas.app/companies/torc-robotics/jobs/"
    "senior-software-engineer-fleet-enablement-insights-map-validation-annotati"
)


def test_recognises_aggregator_hosts():
    assert is_aggregator_url(HIMALAYAS)
    assert not is_aggregator_url("https://job-boards.greenhouse.io/torcrobotics/jobs/8783552002")
    assert not is_aggregator_url("")


def test_parses_company_and_job_slug():
    company, job = _parse_himalayas(HIMALAYAS)
    assert company == "torc-robotics"
    assert job.startswith("senior-software-engineer-fleet-enablement")


def test_board_tokens_drop_the_hyphen_greenhouse_uses():
    # Himalayas writes "torc-robotics"; the Greenhouse board is "torcrobotics".
    assert "torcrobotics" in _board_tokens("torc-robotics", "Torc Robotics")


def test_match_requires_a_convincing_overlap():
    jobs = [
        {"title": "Senior Software Engineer: Fleet Enablement & Insights (Map Validation)",
         "absolute_url": "https://job-boards.greenhouse.io/torcrobotics/jobs/8783552002"},
        {"title": "Staff Accountant", "absolute_url": "https://example.com/2"},
    ]
    wanted = "senior software engineer fleet enablement insights map validation annotati"
    assert _match_job(jobs, wanted)["absolute_url"].endswith("8783552002")

    # A posting that shares nothing must not be matched: pointing an
    # application at the wrong job is worse than leaving it unresolved.
    assert _match_job([{"title": "Staff Accountant", "absolute_url": "x"}], wanted) is None


def test_non_aggregator_urls_are_left_alone():
    assert resolve_aggregator_url("https://job-boards.greenhouse.io/x/jobs/1") is None


@pytest.mark.network
def test_resolves_a_real_listing_end_to_end():
    found = resolve_aggregator_url(HIMALAYAS, company_name="Torc Robotics")
    assert found is not None
    assert found["applicationUrl"] == (
        "https://job-boards.greenhouse.io/torcrobotics/jobs/8783552002"
    )
    assert found["source"].startswith("greenhouse:")
