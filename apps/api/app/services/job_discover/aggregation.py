"""JobAggregationService orchestrator for CareerOS multi-source ingestion."""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta
from typing import Any, Callable

import httpx

from app.services.job_discover.dedup import deduplicate_jobs
from app.services.job_discover.discovery.company_registry import CompanyRegistry
from app.services.job_discover.sources.ashby import AshbySource
from app.services.job_discover.sources.base import JobSource, NormalizedJob
from app.services.job_discover.sources.generic_jsonld import GenericCareerPageSource
from app.services.job_discover.sources.greenhouse import GreenhouseSource
from app.services.job_discover.sources.lever import LeverSource
from app.services.job_discover.sources.playwright_fallback import PlaywrightCareerPageSource
from app.services.job_discover.sources.workday import WorkdaySource


class JobAggregationService:
    """Orchestrate ingestion across registered JobSources with bounded concurrency."""

    def __init__(self) -> None:
        self.sources: list[JobSource] = [
            GreenhouseSource(),
            LeverSource(),
            AshbySource(),
            WorkdaySource(),
            GenericCareerPageSource(),
            PlaywrightCareerPageSource(),
        ]
        self.registry = CompanyRegistry()

    def get_source_adapter(self, source_type: str, config: dict[str, Any] | None = None) -> JobSource | None:
        for adapter in self.sources:
            if adapter.supports(source_type, config):
                return adapter
        return None

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
        except Exception:
            return []
