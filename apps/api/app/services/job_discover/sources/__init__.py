"""CareerOS Job Ingestion V2 Source Adapters."""

from app.services.job_discover.sources.arbeitnow import ArbeitnowSource
from app.services.job_discover.sources.ashby import AshbySource
from app.services.job_discover.sources.base import (
    SOURCE_QUALITY_TIERS,
    JobSource,
    JobSourceAdapter,
    NormalizedJob,
    SourceHealth,
)
from app.services.job_discover.sources.bigtech import BigTechSourceAdapter
from app.services.job_discover.sources.generic_jsonld import GenericCareerPageSource
from app.services.job_discover.sources.github_feed import GitHubFeedSource
from app.services.job_discover.sources.greenhouse import GreenhouseSource
from app.services.job_discover.sources.hackernews import HackerNewsSource
from app.services.job_discover.sources.icims import ICIMSSource
from app.services.job_discover.sources.jobicy import JobicySource
from app.services.job_discover.sources.lever import LeverSource
from app.services.job_discover.sources.oracle import OracleSource
from app.services.job_discover.sources.playwright_fallback import PlaywrightCareerPageSource
from app.services.job_discover.sources.remotive import RemotiveSource
from app.services.job_discover.sources.serpapi_google_jobs import SerpApiGoogleJobsSource
from app.services.job_discover.sources.smartrecruiters import SmartRecruitersSource
from app.services.job_discover.sources.workable import WorkableSource
from app.services.job_discover.sources.workday import WorkdaySource

__all__ = [
    "SOURCE_QUALITY_TIERS",
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
    "BigTechSourceAdapter",
    "JobicySource",
    "ArbeitnowSource",
    "RemotiveSource",
    "HackerNewsSource",
    "GitHubFeedSource",
    "SerpApiGoogleJobsSource",
    "GenericCareerPageSource",
    "PlaywrightCareerPageSource",
]
