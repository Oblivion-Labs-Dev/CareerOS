"""The same posting must dedupe to one key across every host shape it is served under.

Found by grouping the live 5,003-job queue by ATS posting id: 54 id groups held
more than one job record, and the cross-host ones were all the same posting
counted twice because the dedup key was built from netloc+path. Greenhouse alone
serves a posting as `boards.greenhouse.io/<co>/jobs/<id>`,
`job-boards.greenhouse.io/<co>/jobs/<id>`, the regional `boards.eu.greenhouse.io/...`,
and the employer's own branded mirror carrying `?gh_jid=<id>`.
"""

from __future__ import annotations

import pytest

from app.services.application_assistant.job_filter_ranker import (
    canonical_ats_posting_id,
    generate_composite_job_key,
)


@pytest.mark.parametrize(
    ("left", "right"),
    [
        # Observed live: NICE, regional board vs. the .com board.
        (
            "https://boards.eu.greenhouse.io/nice/jobs/4862935101",
            "https://boards.greenhouse.io/nice/jobs/4862935101",
        ),
        # Observed live: Zuora, Greenhouse's old host vs. its current one.
        (
            "https://boards.greenhouse.io/zuora/jobs/7822157",
            "https://job-boards.greenhouse.io/zuora/jobs/7822157",
        ),
        # The employer's branded mirror against the direct board URL.
        (
            "https://www.coinbase.com/careers/positions/7847431?gh_jid=7847431",
            "https://job-boards.greenhouse.io/coinbase/jobs/7847431",
        ),
        # Tracking parameters must not make a second copy of the same job.
        (
            "https://job-boards.greenhouse.io/zuora/jobs/7822157",
            "https://job-boards.greenhouse.io/zuora/jobs/7822157?utm_source=aggregator&gh_src=x",
        ),
    ],
)
def test_host_variants_of_one_posting_share_a_key(left, right):
    company, title = "Zuora", "Senior Software Engineer"
    assert generate_composite_job_key(company, title, left) == generate_composite_job_key(
        company, title, right
    )


def test_different_postings_on_the_same_board_stay_distinct():
    """Canonicalising must not collapse two genuinely different openings."""
    company, title = "Nice", "Senior Software Engineer"
    a = generate_composite_job_key(company, title, "https://boards.greenhouse.io/nice/jobs/4862935101")
    b = generate_composite_job_key(company, title, "https://boards.greenhouse.io/nice/jobs/9999999999")
    assert a != b


def test_non_ats_urls_keep_the_netloc_path_key():
    """A career page with no ATS id still keys on its URL, as before."""
    key = generate_composite_job_key("Acme", "SWE", "https://acme.com/careers/swe-123")
    assert key == "acme::swe::acme.com/careers/swe-123"


@pytest.mark.parametrize(
    ("url", "expected"),
    [
        ("https://boards.greenhouse.io/nice/jobs/4862935101", "gh:4862935101"),
        ("https://www.esri.com/careers/5167707007?gh_jid=5167707007", "gh:5167707007"),
        (
            "https://jobs.lever.co/2brains/4ce74e51-df88-42a5-afa8-7a4c4934d3e8",
            "lever:4ce74e51-df88-42a5-afa8-7a4c4934d3e8",
        ),
        # No id to read: callers fall back to the URL shape.
        ("https://acme.com/careers/swe", ""),
        ("", ""),
    ],
)
def test_canonical_id_extraction(url, expected):
    assert canonical_ats_posting_id(url) == expected


def test_jobvite_collapses_one_posting_listed_per_location():
    """Jobvite repeats a posting once per location, differing only in `loc=`.

    Observed live: a single AppFolio opening came back from Indeed as nine rows,
    all sharing `j=of3MAfwo`. Without this the same job is applied to nine times.
    """
    base = "https://app.jobvite.com/CompanyJobs/Job.aspx?j=of3MAfwo&loc={loc}&s=Indeed"
    a = generate_composite_job_key("AppFolio", "Sr. Software Engineer", base.format(loc="CwbKYfw9"))
    b = generate_composite_job_key("AppFolio", "Sr. Software Engineer", base.format(loc="CxbKYfwa"))
    assert a == b
    assert canonical_ats_posting_id(base.format(loc="CwbKYfw9")) == "jobvite:of3mafwo"


def test_distinct_jobvite_postings_stay_distinct():
    base = "https://app.jobvite.com/CompanyJobs/Job.aspx?j={j}&loc=X"
    assert canonical_ats_posting_id(base.format(j="aaa111")) != canonical_ats_posting_id(
        base.format(j="bbb222")
    )


# ── Aggregator listing URLs are not application forms ────────────────────────

def test_aggregator_listing_urls_are_rejected_as_unapplyable():
    """Indeed/LinkedIn serve a description with no form on it.

    Storing one guarantees the executor opens the page, fills nothing and parks
    the job in MANUAL_REVIEW. 326 autopilot jobs reached the pipeline this way —
    241 already parked — before the hard filter enforced it.
    """
    from app.services.application_assistant.job_filter_ranker import _is_unapplyable_listing_url

    for url in (
        "https://www.indeed.com/viewjob?jk=abc123",
        "https://www.linkedin.com/jobs/view/4467780167",
        "https://jaabz.com/jobs/273961-member-of-technical-staff",
        "https://himalayas.app/companies/acme/jobs/engineer",
    ):
        assert _is_unapplyable_listing_url(url) is True, url


def test_real_employer_and_ats_urls_are_still_allowed():
    from app.services.application_assistant.job_filter_ranker import _is_unapplyable_listing_url

    for url in (
        "https://job-boards.greenhouse.io/acme/jobs/123",
        "https://jobs.uber.com/en/jobs/302443/",
        "https://careers.humana.com/us/en/job/HUM429469",
        "https://gm.wd5.myworkdayjobs.com/en-US/careers/job/X",
        "",
    ):
        assert _is_unapplyable_listing_url(url) is False, url
