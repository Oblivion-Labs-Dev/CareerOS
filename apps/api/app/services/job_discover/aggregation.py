"""JobAggregationService orchestrator for CareerOS Job Ingestion V2."""

from __future__ import annotations

import asyncio
import logging
import time
from datetime import UTC, datetime, timedelta
from typing import Any, Callable

import httpx

from app.services.job_discover.dedup import cross_source_deduplicate
from app.services.job_discover.discovery.company_registry import CompanyRegistry
from app.services.job_discover.sources.arbeitnow import ArbeitnowSource
from app.services.job_discover.sources.ashby import AshbySource
from app.services.job_discover.sources.base import JobSourceAdapter, NormalizedJob, SourceHealth
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

logger = logging.getLogger("career_os.job_discover.aggregation")


class JobAggregationService:
    """Orchestrate ingestion across registered JobSourceAdapters with bounded concurrency and observability."""

    def __init__(self) -> None:
        self.sources: list[JobSourceAdapter] = [
            # Direct ATS (Priority 95)
            GreenhouseSource(),
            LeverSource(),
            AshbySource(),
            SmartRecruitersSource(),
            WorkdaySource(),
            WorkableSource(),
            OracleSource(),
            ICIMSSource(),
            # Direct Company (Priority 100)
            BigTechSourceAdapter(),
            # Curated Public APIs (Priority 80)
            JobicySource(),
            ArbeitnowSource(),
            RemotiveSource(),
            # Community & Feeds (Priority 70)
            HackerNewsSource(),
            GitHubFeedSource(),
            # Aggregator (Priority 60)
            SerpApiGoogleJobsSource(),
            # Fallbacks (Priority 40-50)
            GenericCareerPageSource(),
            PlaywrightCareerPageSource(),
        ]
        self.registry = CompanyRegistry()

    def get_source_adapter(self, source_type: str, config: dict[str, Any] | None = None) -> JobSourceAdapter | None:
        for adapter in self.sources:
            if adapter.supports(source_type, config):
                return adapter
        return None

    def get_health_summary(self) -> list[dict[str, Any]]:
        """Return runtime health status for all registered ingestion adapters."""
        return [adapter.health_check().to_dict() for adapter in self.sources]

    async def sync_company(
        self,
        client: httpx.AsyncClient,
        company: str,
        source_type: str,
        config: dict[str, Any],
        compiled_patterns: list[Any],
        cutoff: datetime,
        role_keys: list[str] | None = None,
    ) -> list[NormalizedJob]:
        adapter = self.get_source_adapter(source_type, config)
        if not adapter:
            logger.warning("No adapter found for source type: %s", source_type)
            return []
        try:
            return await adapter.fetch_jobs(
                client=client,
                company=company,
                config=config,
                compiled_patterns=compiled_patterns,
                cutoff=cutoff,
                role_keys=role_keys,
            )
        except Exception as exc:
            logger.error("Error running adapter %s for %s: %s", source_type, company, exc)
            return []


# Global singleton instance
job_aggregation_service = JobAggregationService()
