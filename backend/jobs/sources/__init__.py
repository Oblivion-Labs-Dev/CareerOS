"""CareerOS Job Ingestion V2 Source Adapters."""

from backend.jobs.sources.arbeitnow import ArbeitnowSource
from backend.jobs.sources.ashby import AshbySource
from backend.jobs.sources.base import (
    SOURCE_QUALITY_TIERS,
    JobSource,
    JobSourceAdapter,
    NormalizedJob,
    SourceHealth,
    SourceRole,
)
from backend.jobs.sources.bigtech import BigTechSourceAdapter
from backend.jobs.sources.github_feed import GitHubFeedSource
from backend.jobs.sources.greenhouse import GreenhouseSource
from backend.jobs.sources.hackernews import HackerNewsSource
from backend.jobs.sources.himalayas import HimalayasSource
from backend.jobs.sources.icims import ICIMSSource
from backend.jobs.sources.jobicy import JobicySource
from backend.jobs.sources.lever import LeverSource
from backend.jobs.sources.oracle import OracleSource
from backend.jobs.sources.personio import PersonioSource
from backend.jobs.sources.playwright_fallback import PlaywrightCareerPageSource
from backend.jobs.sources.recruitee import RecruiteeSource
from backend.jobs.sources.remoteok import RemoteOKSource
from backend.jobs.sources.remotive import RemotiveSource
from backend.jobs.sources.themuse import TheMuseSource
from backend.jobs.sources.serpapi_google_jobs import SerpApiGoogleJobsSource
from backend.jobs.sources.smartrecruiters import SmartRecruitersSource
from backend.jobs.sources.structured_career_page import (
    StructuredCareerPageAdapter,
    parse_jsonld_job_postings,
)
from backend.jobs.sources.weworkremotely import WeWorkRemotelySource
from backend.jobs.sources.workable import WorkableSource
from backend.jobs.sources.workday import WorkdaySource

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
