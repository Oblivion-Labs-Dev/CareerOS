"""Filtering the Applications list by ATS, e.g. every Workday posting to apply to by hand."""

from __future__ import annotations

import pytest

from app.db.store import session_scope
from app.routers.application_assistant.autopilot import get_autopilot_jobs_list
from app.services.application_assistant.ats_plugin_reference import ats_from_url
from app.services.application_assistant.persistence import delete_autopilot_job, save_autopilot_job


@pytest.mark.parametrize(
    ("url", "expected"),
    [
        ("https://nvidia.wd5.myworkdayjobs.com/NVIDIAExternalCareerSite/job/Santa-Clara/SWE_JR1", "workday"),
        ("https://acme.wd1.myworkdaysite.com/recruiting/acme/careers/job/1", "workday"),
        ("https://boards.greenhouse.io/acme/jobs/123", "greenhouse"),
        ("https://careers.acme.com/open-roles?gh_jid=123", "greenhouse"),
        ("https://jobs.lever.co/acme/abc", "lever"),
        ("https://jobs.ashbyhq.com/acme/abc", "ashby"),
        ("https://careers.acme.com/jobs/1", "other"),
        ("", "other"),
        (None, "other"),
    ],
)
def test_ats_from_url(url, expected):
    assert ats_from_url(url) == expected


JOBS = [
    {"id": "apjob_ats_wd_manual", "status": "MANUAL_REVIEW", "company": "Nvidia", "title": "Senior SWE",
     "applicationUrl": "https://nvidia.wd5.myworkdayjobs.com/External/job/1"},
    {"id": "apjob_ats_wd_review", "status": "NEEDS_REVIEW", "company": "Acme", "title": "Senior SWE",
     "applicationUrl": "https://acme.wd1.myworkdaysite.com/recruiting/acme/job/2"},
    {"id": "apjob_ats_gh_manual", "status": "MANUAL_REVIEW", "company": "Stripe", "title": "Senior SWE",
     "applicationUrl": "https://boards.greenhouse.io/stripe/jobs/3"},
    # No applicationUrl, only the legacy `url` field: still classified.
    {"id": "apjob_ats_wd_legacy", "status": "MANUAL_REVIEW", "company": "Legacy", "title": "Senior SWE",
     "url": "https://legacy.wd3.myworkdayjobs.com/x/job/4"},
]


@pytest.fixture
def seeded_jobs():
    with session_scope() as db:
        for job in JOBS:
            save_autopilot_job(db, dict(job))
    yield
    with session_scope() as db:
        for job in JOBS:
            delete_autopilot_job(db, job["id"])


def _ids(result):
    return {job["id"] for job in result["jobs"] if job["id"].startswith("apjob_ats_")}


def test_ats_filter_returns_only_that_ats_within_the_status(seeded_jobs):
    result = get_autopilot_jobs_list(status="MANUAL_REVIEW", ats="workday", limit=1000, offset=0)

    assert _ids(result) == {"apjob_ats_wd_manual", "apjob_ats_wd_legacy"}
    assert result["atsCounts"]["workday"] >= 2
    assert result["atsCounts"]["greenhouse"] >= 1
    assert result["atsLabels"]["workday"] == "Workday"


def test_ats_filter_composes_with_a_multi_status_selection(seeded_jobs):
    result = get_autopilot_jobs_list(status="MANUAL_REVIEW,NEEDS_REVIEW", ats="Workday", limit=1000, offset=0)

    assert _ids(result) == {"apjob_ats_wd_manual", "apjob_ats_wd_review", "apjob_ats_wd_legacy"}


def test_no_ats_filter_leaves_the_list_unchanged(seeded_jobs):
    result = get_autopilot_jobs_list(status="MANUAL_REVIEW", ats=None, limit=1000, offset=0)

    assert {"apjob_ats_wd_manual", "apjob_ats_gh_manual", "apjob_ats_wd_legacy"} <= _ids(result)
