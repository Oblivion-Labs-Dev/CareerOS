"""CareerOS Job Ingestion V2 Source Adapters."""

from jobs.discovery.sources.arbeitnow import ArbeitnowSource
from jobs.discovery.sources.ashby import AshbySource
from jobs.discovery.sources.base import (
    SOURCE_QUALITY_TIERS,
    JobSource,
    JobSourceAdapter,
    NormalizedJob,
    SourceHealth,
    SourceRole,
)
from jobs.discovery.sources.bigtech import BigTechSourceAdapter
from jobs.discovery.sources.github_feed import GitHubFeedSource
from jobs.discovery.sources.greenhouse import GreenhouseSource
from jobs.discovery.sources.hackernews import HackerNewsSource
from jobs.discovery.sources.himalayas import HimalayasSource
from jobs.discovery.sources.icims import ICIMSSource
from jobs.discovery.sources.jobicy import JobicySource
from jobs.discovery.sources.lever import LeverSource
from jobs.discovery.sources.oracle import OracleSource
from jobs.discovery.sources.personio import PersonioSource
from jobs.discovery.sources.playwright_fallback import PlaywrightCareerPageSource
from jobs.discovery.sources.recruitee import RecruiteeSource
from jobs.discovery.sources.remoteok import RemoteOKSource
from jobs.discovery.sources.remotive import RemotiveSource
from jobs.discovery.sources.themuse import TheMuseSource
from jobs.discovery.sources.serpapi_google_jobs import SerpApiGoogleJobsSource
from jobs.discovery.sources.smartrecruiters import SmartRecruitersSource
from jobs.discovery.sources.structured_career_page import (
    StructuredCareerPageAdapter,
    parse_jsonld_job_postings,
)
from jobs.discovery.sources.weworkremotely import WeWorkRemotelySource
from jobs.discovery.sources.workable import WorkableSource
from jobs.discovery.sources.workday import WorkdaySource

# Backwards compatibility alias
GenericCareerPageSource = StructuredCareerPageAdapter

__all__ = [
    "SOURCE_QUALITY_TIERS",
    "SourceRole",
    "JobSource",
    "JobSourceAdapter",
    "NormalizedJob",
    "SourceHealth",
    "GreenhouseSource",
    "LeverSource",
    "AshbySource",
    "SmartRecruitersSource",
    "WorkdaySource",
    "WorkableSource",
    "OracleSource",
    "ICIMSSource",
    "RecruiteeSource",
    "PersonioSource",
    "BigTechSourceAdapter",
    "JobicySource",
    "ArbeitnowSource",
    "RemotiveSource",
    "RemoteOKSource",
    "TheMuseSource",
    "HimalayasSource",
    "WeWorkRemotelySource",
    "HackerNewsSource",
    "GitHubFeedSource",
    "SerpApiGoogleJobsSource",
    "StructuredCareerPageAdapter",
    "GenericCareerPageSource",
    "parse_jsonld_job_postings",
    "PlaywrightCareerPageSource",
]
