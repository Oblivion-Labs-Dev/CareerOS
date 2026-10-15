"""Tests for US location filtering in Job Discover."""

import pytest
from app.services.job_discover.location_filter import US_STATES_ABBR, is_us_location


def test_us_location_empty_or_whitespace():
    assert is_us_location("") is True
    assert is_us_location("   ") is True
    assert is_us_location(None) is True


def test_us_location_country_names():
    assert is_us_location("San Francisco, United States") is True
    assert is_us_location("Austin, USA") is True
    assert is_us_location("Seattle, U.S.A.") is True
    assert is_us_location("New York, U.S.") is True


def test_us_location_state_abbreviations():
    assert is_us_location("San Francisco, CA") is True
    assert is_us_location("Seattle, WA") is True
    assert is_us_location("New York, NY") is True
    assert is_us_location("Austin, TX") is True
    assert is_us_location("Denver, CO | Remote") is True
    assert is_us_location("Washington, DC") is True


def test_us_location_full_state_names():
    assert is_us_location("Austin, Texas") is True
    assert is_us_location("Seattle, Washington") is True
    assert is_us_location("Miami, Florida") is True
    assert is_us_location("Chicago, Illinois") is True


def test_us_location_remote():
    assert is_us_location("Remote") is True
    assert is_us_location("Remote - US") is True
    assert is_us_location("US Remote") is True
    assert is_us_location("Remote, United States") is True
    assert is_us_location("Remote - Canada") is False
    assert is_us_location("Remote - UK") is False
    assert is_us_location("Remote, Germany") is False


def test_us_location_foreign():
    assert is_us_location("London, United Kingdom") is False
    assert is_us_location("Toronto, Canada") is False
    assert is_us_location("Berlin, Germany") is False
    assert is_us_location("Bangalore, India") is False
    assert is_us_location("Tokyo, Japan") is False
    assert is_us_location("Sydney, Australia") is False
    assert is_us_location("Paris, France") is False


def test_re_exported_imports():
    from app.services.job_discover.bigtech_scrapers import is_us_location as bt_loc
    from app.services.job_discover.scraper_service import is_us_location as sc_loc
    from app.services.job_discover.apify_service import is_us_location as ap_loc

    assert bt_loc("San Francisco, CA") is True
    assert sc_loc("San Francisco, CA") is True
    assert ap_loc("San Francisco, CA") is True
