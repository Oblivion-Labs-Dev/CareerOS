"""Base abstraction for multi-source job aggregation in CareerOS."""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

import httpx


@dataclass
class NormalizedJob:
    """Standardized CareerOS job model across all ATS sources and generic web pages."""

    id: str
    external_id: str
    company: str
    company_name: str
    title: str
    location: str = ""
    locations: list[str] = field(default_factory=list)
    remote: bool = False
    hybrid: bool = False
    department: str = ""
    team: str = ""
    description: str = ""
    employment_type: str = ""
    salary_min: float | None = None
    salary_max: float | None = None
    salary_currency: str = "USD"
    salary_range: str = ""
    source: str = "generic"
    source_url: str = ""
    updated_at: str = ""
    first_published: str = ""
    first_seen_at: str = field(default_factory=lambda: datetime.now(UTC).isoformat())
    last_seen_at: str = field(default_factory=lambda: datetime.now(UTC).isoformat())
    active: bool = True
    extraction_method: str = "ats"
    source_metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        """Convert normalized job to CareerOS store format for backward compatibility."""
        return {
            "greenhouse_id": self.external_id,
            "company": self.company,
            "companyName": self.company_name or self.company,
            "title": self.title,
            "location": self.location,
            "department": self.department,
            "url": self.source_url,
            "description": self.description,
            "updated_at": self.updated_at,
            "first_published": self.first_published,
            "employment_type": self.employment_type,
            "salary_range": self.salary_range,
            "source": self.source,
            "extraction_method": self.extraction_method,
            "remote": self.remote,
            "hybrid": self.hybrid,
            "first_seen_at": self.first_seen_at,
            "last_seen_at": self.last_seen_at,
            "active": self.active,
            "source_metadata": self.source_metadata,
        }


class JobSource(ABC):
    """Abstract interface for all ATS and generic career page sources."""

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
        """Fetch and normalize jobs for a single company."""
        pass
