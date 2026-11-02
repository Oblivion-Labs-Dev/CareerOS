"""Core provider architecture and normalized job model for CareerOS Job Ingestion V2."""

from __future__ import annotations

import asyncio
import hashlib
import logging
import re
from abc import ABC, abstractmethod
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from typing import Any
from urllib.parse import urlparse

import httpx

from enum import Enum

logger = logging.getLogger("career_os.job_discover.sources")


class SourceRole(str, Enum):
    """Architectural classification for job data sources according to Phase 13 specification."""

    AUTHORITATIVE = "AUTHORITATIVE"   # Direct employer ATS or official company APIs
    DISCOVERY = "DISCOVERY"           # Company directories, YC, sitemaps, RSS, community feeds
    AGGREGATOR = "AGGREGATOR"         # Multi-employer job boards and search aggregators
    ENRICHMENT = "ENRICHMENT"         # DOL H-1B/LCA, tech stack extraction, company metadata
    FALLBACK = "FALLBACK"             # Universal Schema.org JSON-LD, Playwright browser fallback, JobSpy


# ── Source Priority & Quality Tiers ──────────────────────────────────────────
SOURCE_QUALITY_TIERS: dict[str, int] = {
    "company_api": 100,      # Direct official employer API
    "ats": 95,              # Official ATS API (Greenhouse, Lever, Ashby, Workday, etc.)
    "direct_feed": 90,      # Verified company-published feed
    "public_api": 80,       # Curated public job API (Jobicy, Arbeitnow, Remotive, Himalayas)
    "community": 70,        # Community threads (Hacker News)
    "github_feed": 70,      # Structured GitHub-maintained feeds
    "aggregator": 60,       # Aggregator search engines (Google Jobs via SerpApi)
    "scraper": 40,          # Fragile browser/HTML scrapers
}


@dataclass
class SourceHealth:
    """Runtime observability metrics for an ingestion source."""

    provider: str
    role: str = SourceRole.AUTHORITATIVE.value
    status: str = "healthy"  # "healthy" | "degraded" | "failing" | "disabled"
    last_run: str | None = None
    last_success: str | None = None
    jobs_fetched: int = 0
    jobs_inserted: int = 0
    jobs_updated: int = 0
    duplicates_found: int = 0
    incremental_unique_jobs: int = 0
    request_count: int = 0
    duration_ms: float = 0.0
    consecutive_failures: int = 0
    last_error: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class NormalizedJob:
    """Standardized canonical CareerOS job model across all ingestion channels."""

    id: str
    external_id: str
    company: str
    company_name: str
    title: str
    normalized_title: str = ""
    department: str = ""
    team: str = ""
    location: str = ""
    locations: list[str] = field(default_factory=list)
    city: str = ""
    state: str = ""
    country: str = "US"
    remote: bool = False
    hybrid: bool = False
    remote_status: str = "UNKNOWN"  # "REMOTE" | "HYBRID" | "ONSITE" | "UNKNOWN"
    workplace_type: str = ""
    employment_type: str = ""
    seniority: str = "MID"  # "ENTRY" | "MID" | "SENIOR" | "STAFF" | "PRINCIPAL" | "LEAD" | "MANAGER" | "DIRECTOR" | "VP"
    salary_min: float | None = None
    salary_max: float | None = None
    salary_currency: str = "USD"
    salary_range: str = ""
    salary_interval: str = "YEAR"
    description: str = ""
    description_format: str = "text"
    source: str = "generic"
    source_type: str = "ats"
    source_url: str = ""
    apply_url: str = ""
    canonical_url: str = ""
    updated_at: str = ""
    first_published: str = ""
    first_seen_at: str = field(default_factory=lambda: datetime.now(UTC).isoformat())
    last_seen_at: str = field(default_factory=lambda: datetime.now(UTC).isoformat())
    closed_at: str | None = None
    active: bool = True
    source_priority: int = 95
    source_quality: int = 95
    extraction_method: str = "ats"
    sponsorship_mention: bool = False
    sponsorship_status: str | None = None
    skills: list[str] = field(default_factory=list)
    provenance_sources: list[str] = field(default_factory=list)
    source_metadata: dict[str, Any] = field(default_factory=dict)
    raw_fingerprint: str = ""

    def __post_init__(self) -> None:
        if not self.normalized_title and self.title:
            cleaned = re.sub(r"\b(iii|ii|i|iv|v|level\s*\d+|sr\.?|jr\.?)\b", "", self.title, flags=re.I)
            self.normalized_title = re.sub(r"\s+", " ", cleaned).strip() or self.title

        if not self.provenance_sources and self.source:
            self.provenance_sources = [self.source]

        if not self.canonical_url:
            self.canonical_url = self.source_url

        if not self.apply_url:
            self.apply_url = self.source_url

        if self.source_type in SOURCE_QUALITY_TIERS:
            self.source_quality = SOURCE_QUALITY_TIERS[self.source_type]

        if not self.raw_fingerprint:
            comp = re.sub(r"[^\w]", "", self.company.lower())
            titl = re.sub(r"[^\w]", "", self.title.lower())
            loc = re.sub(r"[^\w]", "", self.location.lower())
            u = self.canonical_url.split("?")[0].rstrip("/").lower()
            key = f"{comp}:{titl}:{loc}:{u}"
            self.raw_fingerprint = hashlib.sha256(key.encode("utf-8")).hexdigest()[:16]

    def to_dict(self) -> dict[str, Any]:
        """Convert normalized job to CareerOS store format for backward compatibility."""
        return {
            "id": self.id,
            "greenhouse_id": self.external_id,
            "externalId": self.external_id,
            "company": self.company,
            "companyName": self.company_name or self.company,
            "title": self.title,
            "normalizedTitle": self.normalized_title or self.title,
            "department": self.department,
            "team": self.team,
            "location": self.location,
            "locations": self.locations,
            "city": self.city,
            "state": self.state,
            "country": self.country,
            "remote": self.remote,
            "hybrid": self.hybrid,
            "remoteStatus": self.remote_status,
            "seniority": self.seniority,
            "employment_type": self.employment_type,
            "employmentType": self.employment_type,
            "salary_range": self.salary_range,
            "salaryRange": self.salary_range,
            "salaryMin": self.salary_min,
            "salaryMax": self.salary_max,
            "salaryCurrency": self.salary_currency,
            "url": self.source_url,
            "applyUrl": self.apply_url or self.source_url,
            "canonicalUrl": self.canonical_url or self.source_url,
            "description": self.description,
            "updated_at": self.updated_at,
            "updatedAt": self.updated_at,
            "first_published": self.first_published,
            "first_seen_at": self.first_seen_at,
            "firstSeenDate": self.first_seen_at,
            "last_seen_at": self.last_seen_at,
            "lastSeenDate": self.last_seen_at,
            "closedAt": self.closed_at,
            "active": self.active,
            "source": self.source,
            "sourceType": self.source_type,
            "sourcePriority": self.source_priority,
            "sourceQuality": self.source_quality,
            "extraction_method": self.extraction_method,
            "discoverySources": self.provenance_sources,
            "canonicalSource": self.source,
            "skills": self.skills,
            "rawFingerprint": self.raw_fingerprint,
            "source_metadata": self.source_metadata,
        }


class JobSource(ABC):
    """Abstract interface for all ATS and career page sources (legacy compatibility)."""

    id: str = "base"
    name: str = "Base Job Source"

    @abstractmethod
    def supports(self, source_type: str, config: dict[str, Any] | None = None) -> bool:
        """Return whether this job source supports the company source configuration."""
        pass

    @abstractmethod
    async def fetch_jobs(
        self,
        client: httpx.AsyncClient,
        company: str,
        config: dict[str, Any],
        compiled_patterns: list[Any],
        cutoff: datetime,
        role_keys: list[str] | None = None,
    ) -> list[NormalizedJob]:
        """Fetch and normalize jobs for a single company or target."""
        pass

    def health_check(self) -> SourceHealth:
        return SourceHealth(provider=getattr(self, "id", "generic"), status="healthy")


class JobSourceAdapter(JobSource):
    """Extended first-class provider adapter with rate limiting, retries, health, and error handling."""

    id: str = "base_adapter"
    name: str = "Base Adapter"
    role: SourceRole = SourceRole.AUTHORITATIVE
    source_type: str = "ats"  # "ats" | "company_api" | "public_api" | "community" | "github_feed" | "aggregator" | "scraper"
    priority: int = 95
    enabled: bool = True
    supports_incremental_sync: bool = True

    # Rate limiting & circuit breaker
    max_retries: int = 3
    base_backoff_sec: float = 1.0
    rate_limit_delay_sec: float = 0.0
    failure_threshold: int = 5  # Consecutive failures before temporary disable

    def __init__(self) -> None:
        role_val = self.role.value if hasattr(self.role, "value") else str(self.role)
        self.health = SourceHealth(provider=self.id, role=role_val)
        if self.source_type in SOURCE_QUALITY_TIERS:
            self.priority = SOURCE_QUALITY_TIERS[self.source_type]

    def supports(self, source_type: str, config: dict[str, Any] | None = None) -> bool:
        return source_type.lower() == self.id.lower()

    def health_check(self) -> SourceHealth:
        return self.health

    def record_success(self, jobs_count: int, duration_ms: float) -> None:
        self.health.last_run = datetime.now(UTC).isoformat()
        self.health.last_success = self.health.last_run
        self.health.jobs_fetched += jobs_count
        self.health.duration_ms = duration_ms
        self.health.consecutive_failures = 0
        self.health.last_error = None
        self.health.status = "healthy"

    def record_failure(self, error: Exception | str, duration_ms: float = 0.0) -> None:
        self.health.last_run = datetime.now(UTC).isoformat()
        self.health.duration_ms = duration_ms
        self.health.consecutive_failures += 1
        self.health.last_error = str(error)
        if self.health.consecutive_failures >= self.failure_threshold:
            self.health.status = "degraded"
        else:
            self.health.status = "failing"

    def is_circuit_open(self) -> bool:
        """Return True if consecutive failures have reached failure_threshold (circuit is open)."""
        return self.health.consecutive_failures >= self.failure_threshold

    async def execute_request(
        self,
        client: httpx.AsyncClient,
        url: str,
        *,
        method: str = "GET",
        headers: dict[str, str] | None = None,
        json_data: Any | None = None,
        params: dict[str, Any] | None = None,
        timeout: float = 15.0,
    ) -> httpx.Response | None:
        """Execute HTTP request with exponential backoff, 429 Retry-After handling, and bounded retries."""
        if not self.enabled or self.is_circuit_open():
            return None

        if self.rate_limit_delay_sec > 0:
            await asyncio.sleep(self.rate_limit_delay_sec)

        backoff = self.base_backoff_sec
        for attempt in range(1, self.max_retries + 1):
            try:
                self.health.request_count += 1
                resp = await client.request(
                    method=method,
                    url=url,
                    headers=headers,
                    json=json_data,
                    params=params,
                    timeout=timeout,
                )

                if resp.status_code == 429:
                    retry_after = resp.headers.get("Retry-After")
                    delay = float(retry_after) if retry_after and retry_after.isdigit() else backoff * 2
                    logger.warning(
                        "Rate limited (429) on %s [%s]. Backing off for %.1fs (attempt %d/%d)",
                        self.id, url, delay, attempt, self.max_retries,
                    )
                    await asyncio.sleep(min(delay, 30.0))
                    backoff *= 2
                    continue

                if resp.status_code >= 500:
                    logger.warning(
                        "Server error (%d) on %s [%s] (attempt %d/%d)",
                        resp.status_code, self.id, url, attempt, self.max_retries,
                    )
                    await asyncio.sleep(backoff)
                    backoff *= 2
                    continue

                return resp

            except (httpx.TimeoutException, httpx.NetworkError) as err:
                logger.warning(
                    "Network error on %s [%s]: %s (attempt %d/%d)",
                    self.id, url, err, attempt, self.max_retries,
                )
                if attempt == self.max_retries:
                    self.record_failure(err)
                    return None
                await asyncio.sleep(backoff)
                backoff *= 2
            except Exception as ex:
                self.record_failure(ex)
                return None

        return None
