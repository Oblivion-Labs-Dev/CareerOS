"""Hard-filter loosening (2026-09-15): real SWE title variants, ambiguous US
locations, and an opt-in switch for postings outside the United States.

Every case below is a title or location string taken from postings the filter
was rejecting in the live discovered-job table.
"""

import pytest

from app.services.application_assistant.job_filter_ranker import evaluate_hard_filters


def _job(title="Senior Software Engineer", location="Seattle, WA", company="Acme"):
    return {
        "company": company,
        "title": title,
        "location": location,
        "applicationUrl": "https://job-boards.greenhouse.io/acme/jobs/123456",
    }


def _passes(job, profile=None):
    return evaluate_hard_filters(job, profile or {}, [], {"allowDuplicates": True})


@pytest.mark.parametrize("title", [
    "Staff Software Development Engineer",
    "Sr. Software Development Engineer - Python Automation / Kubernetes",
    "SDE III - Data Engineering",
    "Senior Software Development Engineer Test (SDET)",
    "Senior Full-Stack Engineer",
])
def test_real_software_titles_now_pass(title):
    ok, reason = _passes(_job(title=title))
    assert ok, reason


# Mid-level software roles are applied to as well (owner, 2026-10-06; supersedes #59).
@pytest.mark.parametrize("title", [
    "Software Development Engineer",
    "Software Development Engineer II – Back-End (Mission-Focused)",
    "Software Development Engineer in Test - Buyer Experience",
    "Product Engineer II – Web Services",
    "Software Engineer",
])
def test_mid_level_software_titles_pass(title):
    ok, reason = _passes(_job(title=title))
    assert ok, reason


@pytest.mark.parametrize("location", ["Anywhere", "Remote (Worldwide)"])
def test_anywhere_remote_does_not_read_as_outside_the_us(location):
    ok, reason = _passes(_job(location=location))
    assert ok, reason


@pytest.mark.parametrize("title", [
    "Principal Software Engineer",
    "Staff Backend Engineer",
    "Senior Machine Learning Engineer",
])
def test_senior_staff_and_principal_software_titles_pass(title):
    ok, reason = _passes(_job(title=title))
    assert ok, reason


@pytest.mark.parametrize("title", [
    "Sales Engineer",
    "Senior Solutions Engineer",
    "Principal Presales Engineer",
    "Senior Product Manager, Platform Core Engineering",
    "Senior Product Designer",
    "Enterprise Sales Engineer",
])
def test_non_software_titles_still_rejected(title):
    ok, reason = _passes(_job(title=title))
    assert not ok
    assert "not a Software Engineering role" in reason


# Security engineering is applied to as well (owner, 2026-10-07).
def test_security_engineer_titles_pass():
    ok, reason = _passes(_job(title="Product Security Engineer, Programs"))
    assert ok, reason


# OpenAI recruiting roles name the team they hire for ("SWE", "Applications Engineering").
@pytest.mark.parametrize("title", [
    "Technical Sourcer, Research SWE",
    "Senior Technical Sourcer, Applications Engineering",
    "Technical Recruiter, Software Engineering",
])
def test_recruiting_titles_naming_an_engineering_team_are_rejected(title):
    ok, reason = _passes(_job(title=title))
    assert not ok
    assert "not a Software Engineering role" in reason


@pytest.mark.parametrize("title", [
    "Senior Electrical Infrastructure Engineer",
    "Mechanical Systems Engineer",
    "Staff Civil Infrastructure Engineer",
])
def test_physical_engineering_disciplines_are_rejected(title):
    ok, reason = _passes(_job(title=title))
    assert not ok
    assert "not a Software Engineering role" in reason


def test_software_role_naming_a_physical_discipline_passes():
    ok, reason = _passes(_job(title="Senior Software Engineer, Electrical Systems"))
    assert ok, reason


@pytest.mark.parametrize("title", [
    "Senior Member of Technical Staff",
    "Member of Technical Staff - Software",
    "Principal Member of the Technical Staff",
])
def test_member_of_technical_staff_titles_pass(title):
    ok, reason = _passes(_job(title=title))
    assert ok, reason


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
    ok, reason = _passes(_job(title="Senior Software Engineer - Duke Energy Platform", location="Charlotte, NC"))
    assert ok, reason


def test_international_switch_does_not_lift_defense_itar_exclusion():
    ok, reason = _passes(_job(company="SpaceX"), {"allowInternationalLocations": True})
    assert not ok
    assert "Defense/ITAR" in reason


@pytest.mark.parametrize("company", ["Alaska Airlines", "alaska airlines inc", "Alaska Airlines, Inc."])
def test_alaska_airlines_excluded_per_user_preference(company):
    ok, reason = _passes(_job(company=company))
    assert not ok
    assert "excluded per user preference" in reason


def test_other_airlines_still_pass():
    ok, reason = _passes(_job(company="Delta Air Lines"))
    assert ok, reason


def test_international_switch_does_not_lift_internship_exclusion():
    ok, reason = _passes(_job(title="Software Engineer Intern", location="London, UK"),
                         {"allowInternationalLocations": True})
    assert not ok
    assert "internship" in reason


# A region named in the title outranks US-looking text in the location field
# (owner, 2026-10-06: US/remote-US only). Both were submitted overnight.
@pytest.mark.parametrize("title,location", [
    ("LATAM Software Engineer(s) (React/Node)",
     "Remote (Argentina, Brazil, Mexico, Puerto Rico, Virgin Islands, U.S.)"),
    ("Staff Backend Engineer - Core Product (Europe)", "Remote (United States)"),
    ("Senior Software Engineer, EMEA", "Remote, United States"),
])
def test_title_naming_a_non_us_region_is_rejected(title, location):
    ok, _reason = _passes(_job(title=title, location=location))
    assert not ok


def test_us_title_with_us_location_still_passes():
    ok, reason = _passes(_job(title="Senior Software Engineer, Americas Platform", location="Remote (United States)"))
    assert ok, reason


@pytest.mark.parametrize("title", [
    "Senior Software Engineer (US / Canada)",
    "Senior Software Engineer - Seattle or Dublin, Ireland",
])
def test_title_naming_the_us_alongside_another_region_passes(title):
    ok, reason = _passes(_job(title=title, location="Remote (United States)"))
    assert ok, reason
