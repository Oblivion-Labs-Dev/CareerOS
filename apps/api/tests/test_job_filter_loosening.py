"""Hard-filter loosening (2026-09-15): real SWE title variants, ambiguous US
locations, and an opt-in switch for postings outside the United States.

Every case below is a title or location string taken from postings the filter
was rejecting in the live discovered-job table.
"""

import pytest

from app.services.application_assistant.job_filter_ranker import evaluate_hard_filters


def _job(title="Software Engineer", location="Seattle, WA", company="Acme"):
    return {
        "company": company,
        "title": title,
        "location": location,
        "applicationUrl": "https://job-boards.greenhouse.io/acme/jobs/123456",
    }


def _passes(job, profile=None):
    return evaluate_hard_filters(job, profile or {}, [], {"allowDuplicates": True})


@pytest.mark.parametrize("title", [
    "Software Development Engineer",
    "Software Development Engineer II – Back-End (Mission-Focused)",
    "Staff Software Development Engineer",
    "Sr. Software Development Engineer - Python Automation / Kubernetes",
    "SDE III - Data Engineering",
    "Senior Software Development Engineer Test (SDET)",
    "Software Development Engineer in Test - Buyer Experience",
    "Senior Full-Stack Engineer",
    "Product Engineer II – Web Services",
])
def test_real_software_titles_now_pass(title):
    ok, reason = _passes(_job(title=title))
    assert ok, reason


@pytest.mark.parametrize("title", [
    "Sales Engineer",
    "Senior Solutions Engineer",
    "Principal Presales Engineer",
    "Senior Product Manager, Platform Core Engineering",
    "Senior Product Designer",
    "Product Security Engineer, Programs",
    "Enterprise Sales Engineer",
])
def test_non_software_titles_still_rejected(title):
    ok, reason = _passes(_job(title=title))
    assert not ok
    assert "not a Software Engineering role" in reason


@pytest.mark.parametrize("location", [
    "Remote, Canada; Remote, United States",
    "San Francisco, CA, New York, NY, Portland, OR, or Remote within US/Canada",
    "Remote (Canada, United States)",
    "Bellevue, Washington; San Francisco, California; Toronto, Ontario",
    "Hybrid",
    "2 Locations",
    "In-Office",
    "NYC",
    "SF",
    "SF, NYC",
    "US-CA-Menlo Park",
    "North Carolina - Raleigh",
    "Alabama",
    "Milwaukee, WI",
    "Vienna, Virginia, United States",
    "Indianapolis, IN",
])
def test_ambiguous_or_mixed_us_locations_pass(location):
    ok, reason = _passes(_job(location=location))
    assert ok, reason


@pytest.mark.parametrize("location", [
    "Bengaluru, India",
    "London, UK",
    "Toronto, Ontario, Canada",
    "Warsaw, Poland",
    "Ho Chi Minh, vn",
    "Hyderabad, in",
    "CA-Ontario-Toronto",
    "United Kingdom (Remote)",
])
def test_non_us_locations_rejected_by_default(location):
    ok, _ = _passes(_job(location=location))
    assert not ok


@pytest.mark.parametrize("location", [
    "Bengaluru, India",
    "London, UK",
    "Toronto, Ontario, Canada",
    "Ho Chi Minh, vn",
])
def test_non_us_locations_pass_when_profile_allows_international(location):
    ok, reason = _passes(_job(location=location), {"allowInternationalLocations": True})
    assert ok, reason


def test_uk_inside_a_word_is_not_a_country():
    ok, reason = _passes(_job(title="Software Engineer - Duke Energy Platform", location="Charlotte, NC"))
    assert ok, reason


def test_international_switch_does_not_lift_defense_itar_exclusion():
    ok, reason = _passes(_job(company="SpaceX"), {"allowInternationalLocations": True})
    assert not ok
    assert "Defense/ITAR" in reason


def test_international_switch_does_not_lift_internship_exclusion():
    ok, reason = _passes(_job(title="Software Engineer Intern", location="London, UK"),
                         {"allowInternationalLocations": True})
    assert not ok
    assert "internship" in reason
