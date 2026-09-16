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
from app.services.job_discover.sources.base import JobSourceAdapter, NormalizedJob, SourceHealth, SourceRole
from app.services.job_discover.sources.bigtech import BigTechSourceAdapter
from app.services.job_discover.sources.github_feed import GitHubFeedSource
from app.services.job_discover.sources.greenhouse import GreenhouseSource
from app.services.job_discover.sources.hackernews import HackerNewsSource
from app.services.job_discover.sources.himalayas import HimalayasSource
from app.services.job_discover.sources.icims import ICIMSSource
from app.services.job_discover.sources.jobicy import JobicySource
from app.services.job_discover.sources.lever import LeverSource
from app.services.job_discover.sources.oracle import OracleSource
from app.services.job_discover.sources.personio import PersonioSource
from app.services.job_discover.sources.playwright_fallback import PlaywrightCareerPageSource
from app.services.job_discover.sources.recruitee import RecruiteeSource
from app.services.job_discover.sources.remoteok import RemoteOKSource
from app.services.job_discover.sources.remotive import RemotiveSource
from app.services.job_discover.sources.themuse import TheMuseSource
from app.services.job_discover.sources.serpapi_google_jobs import SerpApiGoogleJobsSource
from app.services.job_discover.sources.smartrecruiters import SmartRecruitersSource
from app.services.job_discover.sources.structured_career_page import StructuredCareerPageAdapter
from app.services.job_discover.sources.weworkremotely import WeWorkRemotelySource
from app.services.job_discover.sources.workable import WorkableSource
from app.services.job_discover.sources.workday import WorkdaySource

logger = logging.getLogger("career_os.job_discover.aggregation")


class JobAggregationService:
    """Orchestrate ingestion across registered JobSourceAdapters with bounded concurrency, source roles, and incremental coverage metrics."""

    def __init__(self) -> None:
        self.sources: list[JobSourceAdapter] = [
            # Direct Authoritative ATS (Priority 95)
            GreenhouseSource(),
            LeverSource(),
            AshbySource(),
            SmartRecruitersSource(),
            WorkdaySource(),
            WorkableSource(),
            OracleSource(),
            ICIMSSource(),
            RecruiteeSource(),
            PersonioSource(),
            # Direct Authoritative Employer APIs (Priority 100)
            BigTechSourceAdapter(),
            # Curated High-Yield Public APIs (Priority 80)
            JobicySource(),
            HimalayasSource(),
            ArbeitnowSource(),
            RemotiveSource(),
            RemoteOKSource(),
            TheMuseSource(),
            # Discovery Feeds & Community (Priority 70-85)
            WeWorkRemotelySource(),
            HackerNewsSource(),
            GitHubFeedSource(),
            # Aggregator (Priority 60)
            SerpApiGoogleJobsSource(),
            # Universal Structured Fallbacks (Priority 40-75)
            StructuredCareerPageAdapter(),
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

    def measure_incremental_coverage(
        self,
        raw_jobs_by_source: dict[str, list[NormalizedJob]],
    ) -> dict[str, dict[str, Any]]:
        """Compute incremental unique jobs contributed by each source after deduplication."""
        seen_fingerprints: set[str] = set()
        coverage_stats: dict[str, dict[str, Any]] = {}

        # Evaluate sources by descending priority
        sorted_sources = sorted(
            raw_jobs_by_source.keys(),
            key=lambda s: next((a.priority for a in self.sources if a.id == s), 50),
            reverse=True,
        )

        for src_id in sorted_sources:
            jobs = raw_jobs_by_source[src_id]
            total_fetched = len(jobs)
            new_unique = 0
            duplicates = 0

            for j in jobs:
                fp = j.raw_fingerprint or f"{j.company}:{j.title}:{j.location}"
                if fp not in seen_fingerprints:
                    seen_fingerprints.add(fp)
                    new_unique += 1
                else:
                    duplicates += 1

            coverage_stats[src_id] = {
                "jobs_fetched": total_fetched,
                "incremental_unique_jobs": new_unique,
                "duplicates": duplicates,
            }

            # Update adapter health
            adapter = next((a for a in self.sources if a.id == src_id), None)
            if adapter:
                adapter.health.incremental_unique_jobs = new_unique
                adapter.health.duplicates_found = duplicates

        return coverage_stats

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
