"""Request mechanics for Indeed and LinkedIn, adapted from JobSpy (MIT).

Vendored rather than taken as a dependency because `python-jobspy` pins
`NUMPY==1.26.3` and `regex<2025.0.0`, which directly conflict with the
`scipy`/`transformers` versions the local resume matching needs — installing it
silently downgraded both and broke that stack. Only two of its scrapers are
wanted here, and neither needs the parts that carry those pins:

  * `numpy` was used for a single `np.round(x, 2)` call  -> builtin `round`
  * `tls_client` is only used when `is_tls=True`; both the Indeed and LinkedIn
    scrapers ask for `is_tls=False`, so it is not needed at all
  * `pandas` only backs JobSpy's top-level DataFrame wrapper, which is replaced
    here by the project's own `NormalizedJob`

What is kept is the part that is genuinely hard-won: Indeed's mobile GraphQL
endpoint, key and headers, and LinkedIn's guest search endpoint and card markup.
Requests go through the project's own `JobSourceAdapter.execute_request`, which
already provides retry, backoff and 429 handling.

Upstream: https://github.com/speedyapply/JobSpy
Copyright (c) 2023 Cullen Watson — MIT, full text in LICENSE-jobspy alongside
this file.
"""

from __future__ import annotations

# ── Indeed ───────────────────────────────────────────────────────────────────
# The mobile app's public GraphQL surface. The key below is the one shipped in
# Indeed's own iOS client; the accompanying app-info headers have to match it or
# the endpoint answers 403.
INDEED_API_URL = "https://apis.indeed.com/graphql"

INDEED_API_HEADERS = {
    "Host": "apis.indeed.com",
    "content-type": "application/json",
    "indeed-api-key": "161092c2017b5bbab13edb12461a62d5a833871e7cad6d9d475304573de67ac8",
    "accept": "application/json",
    "indeed-locale": "en-US",
    "accept-language": "en-US,en;q=0.9",
    "user-agent": (
        "Mozilla/5.0 (iPhone; CPU iPhone OS 16_6_1 like Mac OS X) "
        "AppleWebKit/605.1.15 (KHTML, like Gecko) Mobile/15E148 Indeed App 193.1"
    ),
    "indeed-app-info": "appv=193.1; appid=com.indeed.jobsearch; osv=16.6.1; os=ios; dtype=phone",
}

# Trimmed to the fields that map onto NormalizedJob. `recruit.viewJobUrl` is the
# one that matters most here: it is the employer's own application URL, which is
# what lets an Indeed hit be handed to the ATS scrapers instead of being applied
# to through Indeed.
INDEED_JOB_SEARCH_QUERY = """
query GetJobData {{
    jobSearch(
    {what}
    {location}
    limit: {limit}
    {cursor}
    sort: RELEVANCE
    {filters}
    ) {{
    pageInfo {{
        nextCursor
    }}
    results {{
        trackingKey
        job {{
        source {{ name }}
        key
        title
        datePublished
        dateOnIndeed
        description {{ html }}
        location {{
            countryName
            countryCode
            admin1Code
            city
            postalCode
            formatted {{ short long }}
        }}
        compensation {{
            baseSalary {{
                unitOfWork
                range {{ ... on Range {{ min max }} }}
            }}
            currencyCode
        }}
        attributes {{ key label }}
        employer {{
            relativeCompanyPageUrl
            name
        }}
        recruit {{
            viewJobUrl
            detailedSalary
            workSchedule
        }}
        }}
    }}
    }}
}}
"""


def build_indeed_date_filter(hours_old: int | None) -> str:
    """Indeed's date filter cannot be combined with the job-type filters."""
    if not hours_old:
        return ""
    return (
        "filters: {{ date: {{ field: \"dateOnIndeed\", start: \"{start}h\" }} }}"
    ).format(start=int(hours_old))


# ── LinkedIn ─────────────────────────────────────────────────────────────────
# The logged-out "see more jobs" endpoint. It returns HTML cards, ten per
# request, and refuses past a start offset of 1000. It carries no external
# apply URL — that lives on the per-job detail page, one extra request each,
# which is why this source is treated as discovery-only.
LINKEDIN_SEARCH_URL = "https://www.linkedin.com/jobs-guest/jobs/api/seeMoreJobPostings/search"

LINKEDIN_HEADERS = {
    "authority": "www.linkedin.com",
    "accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
    "accept-language": "en-US,en;q=0.9",
    "user-agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36"
    ),
}

LINKEDIN_RESULTS_PER_PAGE = 10
LINKEDIN_MAX_START_OFFSET = 1000
